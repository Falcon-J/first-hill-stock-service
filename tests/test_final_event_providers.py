"""Synthetic sequence proofs using real providers, not historical replay results."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from checks.final_events import prepare_checkout
from checks.final_replay_support import order_payload
from services.stock.catalogue import COMPONENTS, demo_recipe, recipe_key
from services.stock.app import create_app as stock_app
from services.order.app import create_app as order_app
from services.gateway.app import create_app as gateway_app
from test_final_events import GROUPS


@pytest.mark.parametrize('order_id,missing', [
    ('MO-20250310-0371', 'oat_milk'),
    ('MO-20250310-0516', 'chai_concentrate'),
    ('MO-20250310-0731', 'vanilla_sweet_cream_cold_foam'),
    ('MO-20250310-1047', 'vanilla_syrup'),
])
def test_final_mid_checkout_real_providers(order_id, missing, tmp_path, monkeypatch):
    group = GROUPS[order_id]
    basket = order_payload(group)
    recipes = {recipe_key(line): demo_recipe(line) for line in basket['items']}
    components = {key: {'component_name': COMPONENTS[key][0], 'component_type': COMPONENTS[key][1],
                       'quantity_on_hand': 100, 'reserved_quantity': 2}
                  for recipe in recipes.values() for key in recipe}
    state = {'aliases': {}, 'recipes': recipes, 'stores': {basket['store_id']: {
        'store_name': 'Synthetic replay fixture', 'store_open': True, 'components': components}}}
    monkeypatch.setenv('ORDERS_DB', str(tmp_path / 'orders.sqlite'))
    monkeypatch.setenv('STOCK_SERVICE_TOKEN', 'test')
    monkeypatch.delenv('STOCK_STORAGE_PATH', raising=False)
    clock = lambda: datetime(2025, 3, 10, 14, tzinfo=timezone.utc)
    headers = {'Authorization': 'Bearer test', 'X-Request-ID': 'proof',
               'X-Request-Deadline': (clock() + timedelta(seconds=30)).isoformat()}
    checkout = datetime.fromisoformat(group[0]['submitted_at'])
    effective = (checkout - timedelta(seconds=1)).isoformat()
    event = {'store_id': basket['store_id'], 'menu_at': (checkout - timedelta(seconds=2)).isoformat(),
             'effective_at': effective, 'components': {missing: {
                 'quantity_on_hand': 0, 'last_updated_at': effective}}}
    payments, queued = [], []
    class Queue:
        def enqueue(self, value):
            queued.append(value)
    def payment(request):
        payments.append(request.url.path)
        return httpx.Response(500)
    def transport(target):
        def send(request):
            response = target.request(request.method, request.url.path, headers=request.headers, content=request.content)
            return httpx.Response(response.status_code, json=response.json())
        return httpx.MockTransport(send)
    with ExitStack() as stack:
        stock = stack.enter_context(TestClient(stock_app(initial_state=state, clock=clock, authenticate=lambda t: t == 'test')))
        inventory = stock.app.state.inventory
        stock_client = stack.enter_context(httpx.Client(base_url='http://stock', transport=transport(stock)))
        payment_client = stack.enter_context(httpx.Client(base_url='http://payment', transport=httpx.MockTransport(payment)))
        order = stack.enter_context(TestClient(order_app(stock_client=stock_client, payment_client=payment_client,
            queue=Queue(), clock=clock, authenticate=lambda t: t == 'test')))
        order_client = stack.enter_context(httpx.Client(base_url='http://order', transport=transport(order)))
        gateway = stack.enter_context(TestClient(gateway_app(order_client=order_client, clock=clock, authenticate=lambda t: t == 'test')))
        def operator(action, data):
            if action == 'menu':
                response = stock.post('/v1/availability', headers=headers, json=data)
                return {'status': response.status_code, 'body': response.json()}
            inventory.apply_feed(data['store_id'], {'components': data['components']})
            return {'applied': True}
        payload, evidence, failures = prepare_checkout(group, {order_id: event}, operator)
        assert failures == [] and evidence['feed_applied'] is True
        response = gateway.post('/v1/orders', json=payload, headers={**headers, 'Idempotency-Key': order_id})
        assert response.status_code == 409, response.text
        name = COMPONENTS[missing][0]
        line = basket['items'][0]
        assert response.json() == {'error': {'code': 'STOCK_CHANGED',
            'message': f"Line 1, {line['size']} {line['drink_name']}: {name} is unavailable at this store right now.",
            'line_item_number': 1, 'missing_component': name,
            'details': [{'code': 'STOCK_CHANGED', 'line_item_number': 1, 'missing_component': name}],
            'retryable': False}, 'request_id': 'proof'}
        assert payments == queued == []
        assert inventory.data['reservations'] == {}
        assert all(row['reserved_quantity'] == 2 for row in inventory.components(basket['store_id']).values())
        with sqlite3.connect(order.app.state.db_path) as db:
            assert db.execute('SELECT count(*) FROM outbox').fetchone()[0] == 0
