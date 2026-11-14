"""All three real providers interact through HTTP request/response adapters."""
from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient
import httpx

from services.gateway.app import create_app as gateway_app
from services.order.app import create_app as order_app
from services.stock.app import create_app as stock_app


def chain(tmp_path, monkeypatch):
    monkeypatch.setenv('ORDERS_DB', str(tmp_path / 'orders.sqlite'))
    monkeypatch.setenv('STOCK_SERVICE_TOKEN', 'chain-test')
    calls = []
    payments = []
    clock = lambda: datetime(2025, 3, 7, 14, 31, tzinfo=timezone.utc)
    def transport(target, name):
        def send(request):
            calls.append((name, request.method, request.url.path))
            response = target.request(request.method, request.url.path,
                                      headers=request.headers, content=request.content)
            return httpx.Response(response.status_code, json=response.json())
        return httpx.MockTransport(send)
    stock = TestClient(stock_app(clock=clock, authenticate=lambda token: token == 'chain-test'))
    def payment(request):
        payments.append(request.url.path)
        return httpx.Response(200, json={'status': 'captured' if request.url.path == '/capture' else 'authorized', 'payment_id': 'chain-payment'})
    order = TestClient(order_app(
        stock_client=httpx.Client(base_url='http://stock', transport=transport(stock, 'stock')),
        payment_client=httpx.Client(base_url='http://payment', transport=httpx.MockTransport(payment)),
        clock=clock, authenticate=lambda token: token == 'chain-test'))
    gateway = TestClient(gateway_app(
        order_client=httpx.Client(base_url='http://order', transport=transport(order, 'order')),
        clock=clock, authenticate=lambda token: token == 'chain-test'))
    return gateway, calls, payments


def request(milk):
    return {'store_id': 'SB-10482', 'items': [{'line_item_number': 1,
        'drink_name': 'Caffè Latte', 'size': 'Grande', 'milk': milk,
        'add_ins': [], 'quantity': 1}], 'payment_method_token': 'test-only'}


def headers(key):
    return {'Authorization': 'Bearer chain-test', 'Idempotency-Key': key,
            'X-Request-ID': 'req-chain-' + key}


def test_real_chain_refuses_snapshot_oat_without_payment(tmp_path, monkeypatch):
    gateway, calls, payments = chain(tmp_path, monkeypatch)
    response = gateway.post('/v1/orders', headers=headers('oat'), json=request('Oatmilk'))
    assert response.status_code == 409
    assert response.json() == {'error': {'code': 'BASE_OUT_OF_STOCK',
        'message': 'Line 1, Grande Caffè Latte: Oatmilk is unavailable at this store right now.',
        'line_item_number': 1, 'missing_component': 'Oatmilk',
        'details': [{'code': 'BASE_OUT_OF_STOCK', 'line_item_number': 1, 'missing_component': 'Oatmilk'}],
        'retryable': False}, 'request_id': 'req-chain-oat'}
    assert calls == [('order', 'POST', '/v1/orders'), ('stock', 'POST', '/v1/reservations')]
    assert payments == []


def test_real_chain_accepts_snapshot_almond_at_explicit_alias(tmp_path, monkeypatch):
    gateway, calls, payments = chain(tmp_path, monkeypatch)
    first = gateway.post('/v1/orders', headers=headers('almond'), json=request('Almondmilk'))
    assert first.status_code == 201, first.text
    assert first.json()['store_id'] == 'SB-10482'
    assert first.json()['status'] == 'accepted'
    assert payments == ['/authorize', '/capture']
    assert calls[0:2] == [('order', 'POST', '/v1/orders'), ('stock', 'POST', '/v1/reservations')]
    assert calls[2][1] == 'POST' and calls[2][2].endswith('/confirm')
    replay = gateway.post('/v1/orders', headers=headers('almond'), json=request('Almondmilk'))
    assert json.loads(replay.content) == first.json()
    assert payments == ['/authorize', '/capture']
