"""Lost replies after actual stock commits reconcile without charging twice."""
from datetime import datetime, timezone
import json
import sqlite3

from fastapi.testclient import TestClient
import httpx
import pytest

from services.gateway.app import create_app as gateway_app
from services.order.app import create_app as order_app
from services.stock.app import create_app as stock_app


class RecordingQueue:
    def __init__(self):
        self.entries = []

    def enqueue(self, order_id):
        self.entries.append(order_id)


def persisted_inventory(path):
    with sqlite3.connect(path) as connection:
        return json.loads(connection.execute(
            'SELECT payload FROM inventory_state WHERE id=1').fetchone()[0])


@pytest.mark.parametrize('lost_reply', ['reserve', 'confirm'])
def test_committed_stock_reply_lost_then_same_key_reconciles(
        tmp_path, monkeypatch, lost_reply):
    clock = lambda: datetime(2025, 3, 7, 14, 31, tzinfo=timezone.utc)
    stock_path = tmp_path / 'stock.sqlite'
    order_path = tmp_path / 'orders.sqlite'
    monkeypatch.setenv('ORDERS_DB', str(order_path))
    monkeypatch.setenv('STOCK_SERVICE_TOKEN', 'lost-reply-test')
    initial = {'stores': {'SB-10482': {'store_name': 'Test store',
        'store_open': True, 'components': {
            'oat_milk': {'quantity_on_hand': 1, 'reserved_quantity': 0},
            'espresso_signature': {'quantity_on_hand': 142, 'reserved_quantity': 4},
        }}}, 'aliases': {}, 'recipes': {}}
    authenticate = lambda token: 'stable-stock-owner' if token == 'lost-reply-test' else False
    target = [TestClient(stock_app(initial_state=initial, clock=clock,
        authenticate=authenticate, storage_path=stock_path))]
    stock_calls, dropped, payments = [], [], []
    queue = RecordingQueue()

    def forward(client, request):
        response = client.request(request.method, request.url.path,
            headers=request.headers, content=request.content)
        return httpx.Response(response.status_code, json=response.json())

    def stock_transport(request):
        # Always execute the real stock endpoint first, including all lookups.
        response = forward(target[0], request)
        stock_calls.append((request.method, request.url.path, response.status_code))
        is_target = (request.method == 'POST' and
            (request.url.path == '/v1/reservations' if lost_reply == 'reserve'
             else request.url.path.endswith('/confirm')))
        if is_target and not dropped:
            assert response.status_code == (201 if lost_reply == 'reserve' else 200)
            dropped.append(response.json())
            raise httpx.ReadTimeout('Committed stock reply lost in delivery', request=request)
        return response

    def payment_transport(request):
        payments.append((request.method, request.url.path))
        return httpx.Response(200, json={
            'status': 'captured' if request.url.path == '/capture' else 'authorized',
            'payment_id': 'development-lost-reply-payment'})

    stock_http = httpx.Client(base_url='http://stock', transport=httpx.MockTransport(stock_transport))
    payment_http = httpx.Client(base_url='http://payment', transport=httpx.MockTransport(payment_transport))
    order = TestClient(order_app(stock_client=stock_http, payment_client=payment_http,
        queue=queue, clock=clock, authenticate=authenticate))
    order_http = httpx.Client(base_url='http://order',
        transport=httpx.MockTransport(lambda request: forward(order, request)))
    gateway = TestClient(gateway_app(order_client=order_http, clock=clock,
        authenticate=authenticate))
    headers = {'Authorization': 'Bearer lost-reply-test',
        'Idempotency-Key': 'lost-' + lost_reply, 'X-Request-ID': 'req-lost-' + lost_reply}
    body = {'store_id': 'SB-10482', 'items': [{'line_item_number': 1,
        'drink_name': 'Caffè Latte', 'size': 'Grande', 'milk': 'Oatmilk',
        'add_ins': [], 'quantity': 1}], 'payment_method_token': 'test-only'}
    owner_headers = {**headers, 'X-Request-Deadline': '2025-03-07T14:32:00+00:00'}
    try:
        first = gateway.post('/v1/orders', headers=headers, json=body)
        assert first.status_code == 503, first.text
        assert first.json() == {'error': {'code': 'STOCK_CHECK_UNAVAILABLE',
            'message': "We can't confirm this store's stock right now. Please try again.",
            'line_item_number': None, 'missing_component': None, 'details': [],
            'retryable': True}, 'request_id': 'req-lost-' + lost_reply}
        assert len(dropped) == 1
        assert payments == []
        assert queue.entries == []
        first_effects = (len(payments), len(queue.entries))
        with sqlite3.connect(order_path) as connection:
            assert connection.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 0
        hold = dropped[0]
        expected_status = 'reserved' if lost_reply == 'reserve' else 'confirmed'
        assert hold['status'] == expected_status
        lookup_path = '/v1/reservations/by-key/' + hold['order_id']
        lookup = target[0].get(lookup_path, headers=owner_headers)
        assert lookup.status_code == 200
        assert lookup.json() == hold
        assert any(method == 'GET' and '/by-key/' in path and status == 200
                   for method, path, status in stock_calls)
        before_restart = persisted_inventory(stock_path)
        assert len(before_restart['reservations']) == 1
        components = before_restart['state']['stores']['SB-10482']['components']
        expected_components = ({
            'oat_milk': {'quantity_on_hand': 1, 'reserved_quantity': 1},
            'espresso_signature': {'quantity_on_hand': 142, 'reserved_quantity': 5},
        } if lost_reply == 'reserve' else {
            'oat_milk': {'quantity_on_hand': 0, 'reserved_quantity': 0},
            'espresso_signature': {'quantity_on_hand': 141, 'reserved_quantity': 4},
        })
        assert components == expected_components

        # Restart the stock owner against its committed private SQLite state.
        target[0].close()
        target[0].app.state.inventory.connection.close()
        target[0] = TestClient(stock_app(initial_state=initial, clock=clock,
            authenticate=authenticate, storage_path=stock_path))
        restarted = target[0].get(lookup_path, headers=owner_headers)
        assert restarted.status_code == 200
        assert restarted.json() == hold
        assert persisted_inventory(stock_path) == before_restart

        replay = gateway.post('/v1/orders', headers=headers, json=body)
        assert replay.status_code == 201, replay.text
        assert replay.json()['status'] == 'accepted'
        assert replay.json()['order_id'] == hold['order_id']
        assert payments == [('POST', '/authorize'), ('POST', '/capture')]
        assert queue.entries == [hold['order_id']]
        final_lookup = target[0].get(lookup_path, headers=owner_headers)
        assert final_lookup.status_code == 200
        assert final_lookup.json()['status'] == 'confirmed'
        assert final_lookup.json()['reservation_id'] == hold['reservation_id']
        final_state = persisted_inventory(stock_path)
        assert len(final_state['reservations']) == 1
        assert final_state['state']['stores']['SB-10482']['components'] == {
            'oat_milk': {'quantity_on_hand': 0, 'reserved_quantity': 0},
            'espresso_signature': {'quantity_on_hand': 141, 'reserved_quantity': 4},
        }
        calls_before_repeat = list(stock_calls)
        repeat = gateway.post('/v1/orders', headers=headers, json=body)
        assert repeat.status_code == 201
        assert repeat.json() == replay.json()
        assert payments == [('POST', '/authorize'), ('POST', '/capture')]
        assert queue.entries == [hold['order_id']]
        assert stock_calls == calls_before_repeat
        assert persisted_inventory(stock_path) == final_state
        with sqlite3.connect(order_path) as connection:
            assert connection.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 1
            assert connection.execute('SELECT COUNT(*), SUM(dispatched) FROM outbox').fetchone() == (1, 1)
        print(f'{lost_reply}: committed={expected_status}; first=503; restart={restarted.status_code}; '
              f'first_payment_calls={first_effects[0]}; first_queue={first_effects[1]}; '
              f'replay={replay.status_code}; repeat={repeat.status_code}; holds=1; '
              f'authorizations={sum(path == "/authorize" for _, path in payments)}; '
              f'captures={sum(path == "/capture" for _, path in payments)}; queue={len(queue.entries)}')
    finally:
        gateway.close()
        order.close()
        target[0].close()
        target[0].app.state.inventory.connection.close()
        order_http.close()
        stock_http.close()
        payment_http.close()
