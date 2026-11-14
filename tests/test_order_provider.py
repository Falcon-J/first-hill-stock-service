"""Durability and ownership checks beyond the frozen provider examples."""
from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import httpx

from services.order.app import create_app


NOW = datetime(2025, 3, 7, 14, 31, tzinfo=timezone.utc)
BODY = {'store_id': 'SB-10482', 'items': [{'line_item_number': 1,
        'drink_name': 'Caffè Latte', 'size': 'Grande', 'milk': 'Oatmilk',
        'add_ins': [], 'quantity': 1}], 'payment_method_token': 'private-test-token'}


def headers(owner='alice'):
    return {'Authorization': 'Bearer ' + owner, 'Idempotency-Key': 'purchase',
            'X-Request-ID': 'request', 'X-Request-Deadline': (NOW + timedelta(seconds=3)).isoformat()}


def dependencies(events, lose_response=False):
    state = {}

    def stock(request):
        events.append(('stock', request.method, request.url.path))
        if request.method == 'POST' and request.url.path == '/v1/reservations':
            state['order_id'] = json.loads(request.content)['order_id']
            if lose_response and not state.get('lost'):
                state['lost'] = True
                raise httpx.ReadTimeout('response lost')
        return httpx.Response(201 if request.url.path == '/v1/reservations' else 200,
            json={'reservation_id': 'hold', 'order_id': state['order_id'], 'store_id': BODY['store_id'],
                  'status': 'confirmed' if request.url.path.endswith('/confirm') else 'reserved',
                  'created_at': NOW.isoformat(), 'expires_at': (NOW + timedelta(seconds=120)).isoformat(),
                  'allocations': [{'component_id': 'oat', 'units': 1, 'line_item_numbers': [1]}]})

    def payment(request):
        events.append(('payment', request.method, request.url.path))
        return httpx.Response(200, json={'payment_id': 'payment',
            'status': 'captured' if request.url.path == '/capture' else 'authorized'})

    return httpx.Client(base_url='http://stock', transport=httpx.MockTransport(stock)), httpx.Client(
        base_url='http://payment', transport=httpx.MockTransport(payment))


def test_order_restarts_replay_without_dependencies_or_plaintext_token(tmp_path, monkeypatch):
    path = tmp_path / 'orders.sqlite3'
    monkeypatch.setenv('ORDERS_DB', str(path))
    events = []
    stock, payment = dependencies(events)

    def client():
        return TestClient(create_app(stock, payment, clock=lambda: NOW, authenticate=lambda token: token))

    first = client().post('/v1/orders', headers=headers(), json=BODY)
    assert first.status_code == 201
    before = list(events)
    second = client().post('/v1/orders', headers=headers(), json=BODY)
    assert second.json() == first.json()
    assert events == before
    assert b'private-test-token' not in path.read_bytes()
    result = client().get('/v1/orders/' + first.json()['order_id'], headers=headers())
    assert result.status_code == 200 and result.json()['status'] == 'accepted'
    forbidden = client().get('/v1/orders/' + first.json()['order_id'], headers=headers('bob'))
    assert forbidden.status_code == 403
    other = client().post('/v1/orders', headers=headers('bob'), json=BODY)
    assert other.status_code == 201 and other.json()['order_id'] != first.json()['order_id']


def test_order_uncertain_reserve_reconciles_same_key_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('ORDERS_DB', str(tmp_path / 'orders.sqlite3'))
    events = []
    stock, payment = dependencies(events, lose_response=True)

    def client():
        return TestClient(create_app(stock, payment, clock=lambda: NOW, authenticate=lambda token: token))

    first = client().post('/v1/orders', headers=headers(), json=BODY)
    assert first.status_code == 503
    assert not any(event[0] == 'payment' for event in events)
    result = client().post('/v1/orders', headers=headers(), json=BODY)
    assert result.status_code == 201
    assert sum(event[1:] == ('POST', '/v1/reservations') for event in events) == 1
    assert any(event[1] == 'GET' and '/by-key/' in event[2] for event in events)


def test_order_retry_authorizes_original_key_after_authoritative_unknown(tmp_path, monkeypatch):
    path = tmp_path / 'orders.sqlite3'
    monkeypatch.setenv('ORDERS_DB', str(path))
    events = []
    stock, _ = dependencies(events)
    payment_requests = []

    def payment_transport(request):
        payment_requests.append(request)
        if request.method == 'GET':
            return httpx.Response(200, json={'status': 'unknown'})
        if request.url.path == '/authorize':
            authorizations = [entry for entry in payment_requests if entry.url.path == '/authorize']
            if len(authorizations) == 1:
                raise httpx.ConnectError('Connection failed before request was sent')
            assert json.loads(request.content)['payment_method_token'] == BODY['payment_method_token']
            return httpx.Response(200, json={'status': 'authorized', 'payment_id': 'payment'})
        assert request.url.path == '/capture'
        return httpx.Response(200, json={'status': 'captured', 'payment_id': 'payment'})

    payment = httpx.Client(base_url='http://payment', transport=httpx.MockTransport(payment_transport))

    def client():
        return TestClient(create_app(stock, payment, clock=lambda: NOW, authenticate=lambda token: token))

    first = client().post('/v1/orders', headers=headers(), json=BODY)
    assert first.status_code == 202
    oid = first.json()['order_id']
    # GET/background reconciliation has no token and must never invent one.
    pending_result = client().get('/v1/orders/' + oid, headers=headers())
    assert pending_result.status_code == 200 and pending_result.json()['status'] == 'pending'
    assert sum(entry.url.path == '/authorize' for entry in payment_requests) == 1
    # A customer replay carries the original token and can safely retry the key.
    accepted = client().post('/v1/orders', headers=headers(), json=BODY)
    assert accepted.status_code == 201
    assert accepted.json()['order_id'] == oid
    assert client().post('/v1/orders', headers=headers(), json=BODY).json() == accepted.json()
    authorization_keys = [entry.headers['Idempotency-Key'] for entry in payment_requests
                          if entry.url.path == '/authorize']
    assert authorization_keys == [oid + ':authorize', oid + ':authorize']
    assert sum(entry.url.path == '/capture' for entry in payment_requests) == 1
    assert sum(event[1:] == ('POST', '/v1/reservations') for event in events) == 1
    assert b'private-test-token' not in path.read_bytes()
