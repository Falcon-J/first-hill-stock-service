"""All 40 source baskets cross real gateway, order and stock HTTP apps."""
import copy
import csv
from datetime import datetime, timezone
import json
import sqlite3

from fastapi.testclient import TestClient
import httpx

from services.gateway.app import create_app as gateway_app
from services.order.app import create_app as order_app
from services.stock.app import create_app as stock_app
from replay_support import ROOT, expected_refusal, rows, synthetic_fixture


def replay_one(row, directory, monkeypatch):
    state, order_basket, competitor, criterion = synthetic_fixture(row)
    monkeypatch.setenv('ORDERS_DB', str(directory / 'orders.sqlite'))
    monkeypatch.setenv('STOCK_SERVICE_TOKEN', 'replay-test')
    monkeypatch.delenv('STOCK_STORAGE_PATH', raising=False)
    clock = lambda: datetime(2025, 3, 7, 14, 31, tzinfo=timezone.utc)
    payments, queue, events = [], [], []
    service_headers = {'Authorization': 'Bearer replay-test', 'X-Request-ID': 'fixture',
                       'X-Request-Deadline': '2025-03-07T14:32:00+00:00', 'Idempotency-Key': 'competitor'}
    stock = TestClient(stock_app(initial_state=state, clock=clock,
                                authenticate=lambda token: token == 'replay-test'))
    inventory = stock.app.state.inventory
    payload = {**order_basket, 'payment_method_token': 'synthetic-development-payment'}
    winning = None
    token = None
    if competitor:
        menu = stock.post('/v1/availability', headers=service_headers, json=order_basket)
        assert menu.status_code == 200 and menu.json()['available'] is True
        token = menu.json()['availability_token']
        payload['availability_token'] = token
        if criterion == 'AC-R5':
            win = stock.post('/v1/reservations', headers=service_headers,
                json={'order_id': 'synthetic-competitor', 'basket': competitor})
            assert win.status_code == 201, win.text
            winning = copy.deepcopy(inventory.data['reservations'])
    before = inventory.snapshot(row['store_id'])

    def transport(target, name):
        def send(request):
            response = target.request(request.method, request.url.path,
                                      headers=request.headers, content=request.content)
            events.append((name, request.url.path, response.status_code))
            if name == 'stock' and response.status_code in (200, 201):
                assert not payments
                if request.url.path == '/v1/reservations' and criterion == 'AC-P2':
                    # Target owns the last unit before the competitor attempts
                    # its own independent single-component basket.
                    loser = stock.post('/v1/reservations', headers=service_headers,
                        json={'order_id': 'synthetic-competitor', 'basket': competitor})
                    assert loser.status_code == 409
            return httpx.Response(response.status_code, json=response.json())
        return httpx.MockTransport(send)

    def development_payment(request):
        payments.append(request.url.path)
        events.append(('payment', request.url.path, 200))
        return httpx.Response(200, json={'status': 'captured' if request.url.path == '/capture'
                                       else 'authorized', 'payment_id': 'synthetic-payment'})

    class Queue:
        def enqueue(self, order_id):
            queue.append(order_id)

    order = TestClient(order_app(
        stock_client=httpx.Client(base_url='http://stock', transport=transport(stock, 'stock')),
        payment_client=httpx.Client(base_url='http://development-payment', transport=httpx.MockTransport(development_payment)),
        queue=Queue(), clock=clock, authenticate=lambda token: token == 'replay-test'))
    gateway = TestClient(gateway_app(
        order_client=httpx.Client(base_url='http://order', transport=transport(order, 'order')),
        clock=clock, authenticate=lambda token: token == 'replay-test'))
    headers = {'Authorization': 'Bearer replay-test', 'Idempotency-Key': row['order_id'],
               'X-Request-ID': 'req-' + row['order_id']}
    response = gateway.post('/v1/orders', headers=headers, json=payload)
    body = response.json()
    result = {'order_id': row['order_id'], 'csv_line': row['csv_line'],
              'expected': row['expected_outcome'], 'actual': body.get('status', 'refused' if 'error' in body else 'unknown'),
              'http_status': response.status_code, 'component': body.get('error', {}).get('missing_component') or '',
              'criterion': criterion, 'result': 'FAIL', 'mismatch': ''}
    try:
        if row['expected_outcome'] == 'refused':
            expected = expected_refusal(row)
            assert response.status_code == 409, body
            assert body == expected, {'expected': expected, 'actual': body}
            assert payments == [] and queue == []
            assert inventory.snapshot(row['store_id']) == before
            assert inventory.data['reservations'] == (winning or {})
        else:
            assert response.status_code == 201, body
            assert body == {'status': 'accepted', 'order_id': body['order_id'], 'store_id': row['store_id'],
                            'queue_spot': 1, 'request_id': 'req-' + row['order_id']}
            assert body['order_id'] and body['order_id'] != row['order_id']
            assert payments == ['/authorize', '/capture'] and queue == [body['order_id']]
            assert events[0] == ('stock', '/v1/reservations', 201)
            assert events[1][0] == 'stock' and events[1][1].endswith('/confirm')
            assert events[2:4] == [('payment', '/authorize', 200), ('payment', '/capture', 200)]
            assert len(inventory.data['reservations']) == 1
            assert next(iter(inventory.data['reservations'].values()))['public']['status'] == 'confirmed'
            # Replay must preserve the opaque response and all side-effect counts.
            again = gateway.post('/v1/orders', headers=headers, json=payload)
            assert again.status_code == 201 and again.json() == body
            assert payments == ['/authorize', '/capture'] and queue == [body['order_id']]
        with sqlite3.connect(order.app.state.db_path) as conn:
            assert conn.execute('SELECT count(*) FROM outbox').fetchone()[0] == (1 if row['expected_outcome'] == 'accepted' else 0)
        result['result'] = 'PASS'
    except AssertionError as error:
        result['mismatch'] = str(error)
    finally:
        gateway.close()
        order.close()
        stock.close()
    return result


def test_all_40_source_orders_through_real_gateway_order_stock(tmp_path, monkeypatch):
    source_rows = rows()
    assert len(source_rows) == 40
    results = []
    for row in source_rows:
        directory = tmp_path / row['order_id']
        directory.mkdir()
        results.append(replay_one(row, directory, monkeypatch))
    destination = ROOT / 'docs/overselling/replay-results.csv'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    failures = [result for result in results if result['result'] != 'PASS']
    assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)
