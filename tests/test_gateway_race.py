"""Designed last-unit race through real gateway, order and stock HTTP apps.

The historical oat snapshot stays zero. Only this isolated synthetic fixture has
one oat unit; payment is a recording adapter, not a real financial provider.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
from threading import Barrier, Lock

from fastapi.testclient import TestClient
import httpx

from services.gateway.app import create_app as gateway_app
from services.order.app import create_app as order_app
from services.stock.app import create_app as stock_app
from services.stock.catalogue import load_snapshot


def test_gateway_concurrent_last_oat_unit_with_shared_stock_sqlite(tmp_path, monkeypatch):
    token = 'gateway-race-test'
    monkeypatch.setenv('STOCK_SERVICE_TOKEN', token)
    monkeypatch.setenv('ORDERS_DB', str(tmp_path / 'orders.sqlite'))
    now = datetime(2025, 3, 7, 14, 31, tzinfo=timezone.utc)
    clock = lambda: now
    authenticate = lambda supplied: supplied == token
    state = load_snapshot()
    components = state['stores']['10482']['components']
    assert components['oat_milk']['quantity_on_hand'] == 0
    assert components['espresso_signature']['quantity_on_hand'] == 142
    assert components['espresso_signature']['reserved_quantity'] == 4
    components['oat_milk']['quantity_on_hand'] = 1  # Synthetic override, never a CSV edit.
    basket = {'store_id': 'SB-10482', 'items': [{'line_item_number': 1,
        'drink_name': 'Caffè Latte', 'size': 'Grande', 'milk': 'Oatmilk',
        'add_ins': [], 'quantity': 1}]}
    stock_headers = {'Authorization': f'Bearer {token}', 'X-Request-ID': 'menu-race',
        'X-Request-Deadline': (now + timedelta(seconds=3)).isoformat()}
    payments, queued, events = [], [], []
    guard = Lock()

    class Queue:
        def enqueue(self, order_id):
            queued.append(order_id)

    def payment(request):
        body = json.loads(request.content)
        with guard:
            payments.append((request.url.path, body['order_id']))
            events.append((request.url.path, body['order_id']))
        return httpx.Response(200, json={
            'status': 'captured' if request.url.path == '/capture' else 'authorized',
            'payment_id': 'recorded-' + body['order_id']})

    with ExitStack() as stack:
        stock_path = str(tmp_path / 'stock.sqlite')
        stock_apps = [stock_app(initial_state=state, clock=clock,
            authenticate=authenticate, storage_path=stock_path)]
        stocks = [stack.enter_context(TestClient(stock_apps[0]))]
        menu = stocks[0].post('/v1/availability', headers=stock_headers, json=basket)
        assert menu.status_code == 200, menu.text
        assert menu.json()['available'] is True
        # A second process-equivalent instance reads the same token and initial
        # unit from SQLite. Its private Python lock cannot serialize the first.
        stock_apps.append(stock_app(initial_state=state, clock=clock,
            authenticate=authenticate, storage_path=stock_path))
        stocks.append(stack.enter_context(TestClient(stock_apps[1])))
        order_routes, reservation_routes = {}, {}

        def stock_send(request):
            path = request.url.path
            with guard:
                if path == '/v1/reservations':
                    oid = json.loads(request.content)['order_id']
                    index = order_routes.setdefault(oid, len(order_routes) % 2)
                elif '/by-key/' in path:
                    index = order_routes[path.rsplit('/', 1)[-1]]
                else:
                    reservation_id = path.split('/')[3]
                    index = reservation_routes[reservation_id]
            response = stocks[index].request(request.method, path,
                headers=request.headers, content=request.content)
            data = response.json()
            with guard:
                if response.status_code in (200, 201) and 'reservation_id' in data:
                    reservation_routes[data['reservation_id']] = index
                    events.append((data['status'], data['order_id']))
            return httpx.Response(response.status_code, json=data)

        orders = []
        for _ in range(2):
            orders.append(stack.enter_context(TestClient(order_app(
                stock_client=stack.enter_context(httpx.Client(base_url='http://stock',
                    transport=httpx.MockTransport(stock_send))),
                payment_client=stack.enter_context(httpx.Client(base_url='http://payment',
                    transport=httpx.MockTransport(payment))),
                queue=Queue(), clock=clock, authenticate=authenticate))))
        # Separate real order app event loops prevent synchronous downstream I/O
        # in one request from serializing the competing checkout in this harness.
        def order_send(request):
            index = 0 if request.headers['Idempotency-Key'] == 'race-a' else 1
            response = orders[index].request(request.method, request.url.path,
                headers=request.headers, content=request.content)
            return httpx.Response(response.status_code, json=response.json())

        gateway = stack.enter_context(TestClient(gateway_app(
            order_client=stack.enter_context(httpx.Client(base_url='http://order',
                transport=httpx.MockTransport(order_send))),
            clock=clock, authenticate=authenticate)))
        payload = {**basket, 'payment_method_token': 'test-only',
            'availability_token': menu.json()['availability_token']}
        start = Barrier(2)

        def checkout(key, concurrent=False):
            if concurrent:
                start.wait(timeout=5)
            return gateway.post('/v1/orders', headers={'Authorization': f'Bearer {token}',
                'Idempotency-Key': key, 'X-Request-ID': 'req-' + key}, json=payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {key: pool.submit(checkout, key, True) for key in ('race-a', 'race-b')}
            results = {key: future.result(timeout=10) for key, future in futures.items()}
        assert sorted(response.status_code for response in results.values()) == [201, 409], {
            key: (response.status_code, response.json()) for key, response in results.items()}
        winner_key = next(key for key, response in results.items() if response.status_code == 201)
        loser_key = next(key for key in results if key != winner_key)
        winner = results[winner_key].json()
        assert winner['status'] == 'accepted'
        assert results[loser_key].json() == {'error': {'code': 'STOCK_CHANGED',
            'message': 'Line 1, Grande Caffè Latte: Oatmilk is unavailable at this store right now.',
            'line_item_number': 1, 'missing_component': 'Oatmilk',
            'details': [{'code': 'STOCK_CHANGED', 'line_item_number': 1,
                'missing_component': 'Oatmilk'}], 'retryable': False},
            'request_id': 'req-' + loser_key}
        oid = winner['order_id']
        assert len(order_routes) == 2 and set(order_routes.values()) == {0, 1}
        assert payments == [('/authorize', oid), ('/capture', oid)]
        assert queued == [oid]
        print('Gateway race statuses:', sorted(response.status_code for response in results.values()),
              'captures:', sum(path == '/capture' for path, _ in payments),
              'queue entries:', len(queued), 'missing:', results[loser_key].json()['error']['missing_component'])
        assert events.index(('confirmed', oid)) < events.index(('/authorize', oid))
        for key, original in results.items():
            replay = checkout(key)
            assert (replay.status_code, replay.json()) == (original.status_code, original.json())
        assert payments == [('/authorize', oid), ('/capture', oid)]
        assert queued == [oid]
        # Both independent stock owners must retain the same winning allocation
        # and original espresso reservations after the loser and both replays.
        winning_allocation = None
        for stock in stocks:
            held = stock.get('/v1/reservations/by-key/' + oid, headers=stock_headers)
            assert held.status_code == 200, held.text
            assert held.json()['status'] == 'confirmed'
            if winning_allocation is None:
                winning_allocation = held.json()
            assert held.json() == winning_allocation
            assert held.json()['allocations'] == [
                {'component_id': 'espresso_signature', 'units': 1, 'line_item_numbers': [1]},
                {'component_id': 'oat_milk', 'units': 1, 'line_item_numbers': [1]}]
        for app in stock_apps:
            final = app.state.inventory.snapshot('10482')
            assert final['oat_milk']['quantity_on_hand'] == 0
            assert final['oat_milk']['reserved_quantity'] == 0
            assert final['espresso_signature']['quantity_on_hand'] == 141
            assert final['espresso_signature']['reserved_quantity'] == 4
