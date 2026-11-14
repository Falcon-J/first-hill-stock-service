"""Order-owned durable saga. Inventory is accessed exclusively over HTTP."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError


class Line(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    line_item_number: StrictInt = Field(ge=1)
    drink_name: str = Field(min_length=1)
    size: str = Field(min_length=1)
    milk: str = Field(min_length=1)
    add_ins: list[str]
    quantity: StrictInt = Field(ge=1)


class OrderInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    store_id: str = Field(min_length=1)
    items: list[Line] = Field(min_length=1)
    submitted_at: str | None = None
    payment_method_token: str = Field(min_length=1)
    availability_token: str | None = Field(default=None, min_length=1)


class Unavailable(Exception):
    pass


def envelope(code, request_id, message='Unable to complete this request.', retryable=False):
    return {'error': {'code': code, 'message': message, 'line_item_number': None,
                      'missing_component': None, 'details': [], 'retryable': retryable},
            'request_id': request_id}


def create_app(stock_client=None, payment_client=None, queue=None, clock=None, authenticate=None):
    injected = stock_client is not None
    gateway_authentication = authenticate is None
    clock = clock or (lambda: datetime.now(timezone.utc))
    stock_secret = os.getenv('STOCK_SERVICE_TOKEN', '')
    payment_secret = os.getenv('PAYMENT_SERVICE_TOKEN', '')
    development_payment = os.getenv('PAYMENT_ADAPTER') == 'development'
    inbound_secret = os.getenv('ORDER_SERVICE_TOKEN', '')
    if authenticate is None:
        authenticate = lambda token: bool(inbound_secret) and hmac.compare_digest(token, inbound_secret)
    stock_client = stock_client or httpx.Client(base_url=os.getenv('STOCK_URL', 'http://stock:8000'))
    payment_client = payment_client or httpx.Client(base_url=os.getenv('PAYMENT_URL', 'http://payment:8000'))
    db_path = os.getenv('ORDERS_DB')
    if not db_path:
        db_path = (tempfile.mktemp(prefix='orders-', suffix='.sqlite3') if injected
                   else str(Path(tempfile.gettempdir()) / 'first-hill-orders.sqlite3'))
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def connect():
        conn = sqlite3.connect(db_path, timeout=3)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        conn.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS attempts (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, key TEXT NOT NULL,
            fingerprint TEXT NOT NULL, basket TEXT NOT NULL, availability TEXT,
            request_id TEXT NOT NULL, phase TEXT NOT NULL, reservation TEXT,
            payment TEXT, response TEXT, status INTEGER, lease REAL DEFAULT 0,
            UNIQUE(owner,key));
        CREATE TABLE IF NOT EXISTS outbox (
            spot INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT UNIQUE NOT NULL,
            dispatched INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS development_payments (
            order_id TEXT PRIMARY KEY, status TEXT NOT NULL);
        ''')

    if development_payment and not injected:
        def development_transport(request):
            """Explicitly opt-in local demo adapter: never makes financial requests."""
            if request.method == 'GET':
                oid = request.url.path.rsplit('/', 1)[-1].removesuffix(':authorize')
                with connect() as conn:
                    payment = conn.execute('SELECT status FROM development_payments WHERE order_id=?', (oid,)).fetchone()
                return httpx.Response(200, json={'status': payment['status'] if payment else 'unknown', 'payment_id': oid})
            body = json.loads(request.content)
            oid = body['order_id']
            state = 'captured' if request.url.path == '/capture' else 'authorized'
            with connect() as conn:
                conn.execute('INSERT INTO development_payments(order_id,status) VALUES(?,?) ON CONFLICT(order_id) DO UPDATE SET status=CASE WHEN status=\'captured\' THEN status ELSE excluded.status END', (oid, state))
                state = conn.execute('SELECT status FROM development_payments WHERE order_id=?', (oid,)).fetchone()['status']
            return httpx.Response(200, json={'status': state, 'payment_id': oid})
        payment_client = httpx.Client(base_url='http://development-payment', transport=httpx.MockTransport(development_transport))

    stop_worker = threading.Event()

    @asynccontextmanager
    async def lifespan(runtime):
        stop_worker.clear()
        worker = threading.Thread(target=reconcile_worker, name='order-reconciliation', daemon=True)
        runtime.state.reconciliation_worker = worker
        worker.start()
        try:
            yield
        finally:
            stop_worker.set()
            worker.join(timeout=4)

    app = FastAPI(title='Order service', version='1.0.0', lifespan=lifespan)
    app.state.db_path = db_path

    def reconcile_worker():
        # Only payment-started sagas are resumed without a customer token.
        # Pre-payment uncertain reservations remain stock-owned expiring holds.
        while not stop_worker.wait(2):
            with connect() as conn:
                candidates = conn.execute("SELECT id FROM attempts WHERE phase IN ('authorizing','capturing','captured','declined') AND lease<? LIMIT 10", (time.time(),)).fetchall()
            for candidate in candidates:
                with connect() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    row = conn.execute('SELECT * FROM attempts WHERE id=?', (candidate['id'],)).fetchone()
                    if row['lease'] > time.time() or row['phase'] == 'done':
                        continue
                    conn.execute('UPDATE attempts SET lease=? WHERE id=?', (time.time() + 10, row['id']))
                headers = [(b'x-request-id', row['request_id'].encode()),
                           (b'x-request-deadline', (clock() + timedelta(seconds=3)).isoformat().encode())]
                try:
                    process(row, Request({'type': 'http', 'headers': headers}), is_get=True)
                except Exception:
                    # No dependency response or credential is logged. Durable
                    # phase remains available for the next reconciliation pass.
                    pass
                finally:
                    save(row['id'], lease=0)

    def save(order_id, **values):
        with connect() as conn:
            conn.execute('UPDATE attempts SET ' + ','.join(f'{key}=?' for key in values) + ' WHERE id=?',
                         [*values.values(), order_id])

    def identity(request):
        auth = request.headers.get('authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else ''
        principal = authenticate(token) if token else None
        if not principal:
            return None
        if gateway_authentication:
            # This endpoint trusts only the authenticated gateway credential. The
            # gateway must overwrite this header from its authenticated principal.
            return 'gateway:' + (request.headers.get('x-customer-id') or 'configured-customer')
        # Authentication callbacks can return a stable subject, or simply validate a token.
        return str(principal) if not isinstance(principal, bool) else hashlib.sha256(token.encode()).hexdigest()

    def unavailable(rid):
        return JSONResponse(envelope('STOCK_CHECK_UNAVAILABLE', rid,
            "We can't confirm this store's stock right now. Please try again.", True), 503)

    def pending(row, code='PAYMENT_PENDING'):
        return {'status': 'pending', 'order_id': row['id'], 'code': code,
                'message': 'Payment confirmation is pending.' if code == 'PAYMENT_PENDING' else 'Order confirmation is pending.',
                'request_id': row['request_id']}

    def terminal(row, status, body):
        save(row['id'], status=status, response=json.dumps(body), phase='done')
        return JSONResponse(body, status)

    def process(row, request, payment_token=None, is_get=False):
        rid = row['request_id']
        try:
            absolute = datetime.fromisoformat(request.headers['x-request-deadline'].replace('Z', '+00:00'))
            if absolute.tzinfo is None:
                raise ValueError()
            deadline = min(absolute, clock() + timedelta(seconds=3))
        except (KeyError, ValueError, TypeError):
            return unavailable(rid)
        started = time.monotonic()
        initial_budget = (deadline - clock()).total_seconds()

        def call(client, method, path, cap, key, body=None):
            remaining = min((deadline - clock()).total_seconds(), initial_budget - (time.monotonic() - started))
            if remaining <= 0:
                raise Unavailable()
            secret = stock_secret if client is stock_client else payment_secret
            if not injected and not secret and not (client is payment_client and development_payment):
                raise Unavailable()
            headers = {'X-Request-ID': rid, 'X-Request-Deadline': deadline.isoformat(), 'Idempotency-Key': key}
            if secret:
                headers['Authorization'] = f'Bearer {secret}'
            try:
                response = client.request(method, path, json=body, headers=headers, timeout=min(cap, remaining))
                data = response.json()
                if not isinstance(data, dict):
                    raise Unavailable()
                return response.status_code, data
            except (httpx.HTTPError, ValueError):
                raise Unavailable() from None

        def stock(method, path, key, body=None):
            status, data = call(stock_client, method, path, .4 if '/confirm' in path else .6, key, body)
            if status in (404, 409, 422):
                error = data.get('error', {})
                allowed = {404: {'STORE_NOT_FOUND', 'RESERVATION_NOT_FOUND'},
                           409: {'STORE_CLOSED', 'BASE_OUT_OF_STOCK', 'ADD_IN_OUT_OF_STOCK',
                                 'INSUFFICIENT_QUANTITY', 'STOCK_CHANGED', 'RESERVATION_EXPIRED',
                                 'IDEMPOTENCY_CONFLICT', 'INVALID_RESERVATION_STATE'},
                           422: {'INVALID_ORDER', 'UNKNOWN_ITEM'}}
                detail_keys = {'code', 'line_item_number', 'missing_component'}
                error_keys = detail_keys | {'message', 'details', 'retryable'}

                def valid_detail(detail):
                    return (isinstance(detail, dict) and detail_keys <= set(detail)
                            and (detail['line_item_number'] is None or
                                 (type(detail['line_item_number']) is int and detail['line_item_number'] >= 1))
                            and (detail['missing_component'] is None or isinstance(detail['missing_component'], str)))

                if (isinstance(error, dict) and isinstance(error.get('message'), str)
                        and error.get('message') and error.get('code') in allowed[status] and error.get('retryable') is False
                        and set(error) == error_keys and valid_detail(error)
                        and isinstance(error.get('details'), list) and all(valid_detail(detail) for detail in error['details'])
                        and set(data) == {'error', 'request_id'} and data.get('request_id') == rid):
                    if error['code'] == 'STOCK_CHANGED' and (error['line_item_number'] is None
                            or not error['missing_component'] or not error['details']):
                        raise Unavailable()
                    return status, data
                raise Unavailable()
            if status not in (200, 201) or any(field not in data for field in
                    ('reservation_id', 'order_id', 'store_id', 'status', 'created_at', 'expires_at', 'allocations')):
                raise Unavailable()
            if (data['order_id'] != row['id'] or data['store_id'] != json.loads(row['basket'])['store_id']
                    or not isinstance(data['reservation_id'], str) or not data['reservation_id']
                    or data['status'] not in ('reserved', 'confirmed', 'released', 'expired')
                    or not isinstance(data['allocations'], list) or not data['allocations']):
                raise Unavailable()
            try:
                created = datetime.fromisoformat(data['created_at'].replace('Z', '+00:00'))
                expires = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
                if expires <= created:
                    raise ValueError()
                if created.tzinfo is None or expires.tzinfo is None:
                    raise ValueError()
                for allocation in data['allocations']:
                    if (not isinstance(allocation['component_id'], str) or not allocation['component_id'] or type(allocation['units']) is not int
                            or allocation['units'] <= 0 or not allocation['line_item_numbers']
                            or any(type(line) is not int or line < 1 for line in allocation['line_item_numbers'])):
                        raise ValueError()
            except (ValueError, KeyError, TypeError, AttributeError):
                raise Unavailable() from None
            return status, data

        oid = row['id']
        phase = row['phase']
        reservation = row['reservation']
        try:
            if phase in ('new', 'reserving', 'confirming'):
                if phase == 'new':
                    save(oid, phase='reserving')
                    body = {'order_id': oid, 'basket': json.loads(row['basket'])}
                    if row['availability']:
                        body['availability_token'] = row['availability']
                    try:
                        status, data = stock('POST', '/v1/reservations', oid, body)
                    except Unavailable:
                        # Query original key after an uncertain write, never create a new hold.
                        try:
                            _, recovered = stock('GET', f'/v1/reservations/by-key/{oid}', oid)
                            if recovered.get('reservation_id'):
                                save(oid, reservation=recovered['reservation_id'])
                        except Unavailable:
                            pass
                        return unavailable(rid)
                else:
                    status, data = stock('GET', f'/v1/reservations/by-key/{oid}', oid)
                    if status == 404 and data['error']['code'] == 'RESERVATION_NOT_FOUND' and phase == 'reserving':
                        # Authoritative absence permits retrying the SAME write key;
                        # never manufacture a second order/hold identity.
                        body = {'order_id': oid, 'basket': json.loads(row['basket'])}
                        if row['availability']:
                            body['availability_token'] = row['availability']
                        try:
                            status, data = stock('POST', '/v1/reservations', oid, body)
                        except Unavailable:
                            try:
                                stock('GET', f'/v1/reservations/by-key/{oid}', oid)
                            except Unavailable:
                                pass
                            return unavailable(rid)
                if status in (404, 409, 422):
                    return terminal(row, status, data)
                reservation = data['reservation_id']
                save(oid, reservation=reservation, phase='confirming')
                if data['status'] != 'confirmed':
                    try:
                        status, data = stock('POST', f'/v1/reservations/{reservation}/confirm', oid + ':confirm')
                    except Unavailable:
                        try:
                            stock('GET', f'/v1/reservations/by-key/{oid}', oid)
                        except Unavailable:
                            pass
                        return unavailable(rid)
                    if status in (404, 409, 422):
                        return terminal(row, status, data)
                if data['status'] != 'confirmed':
                    return unavailable(rid)
                phase = 'confirmed'
                save(oid, phase=phase)

            if phase in ('confirmed', 'authorizing', 'capturing'):
                payment_id = row['payment']
                if phase != 'confirmed':
                    # Reconcile provider state before any further payment write.
                    lookup_status, pay = call(payment_client, 'GET', f'/payments/by-key/{oid}:authorize', 1, oid + ':authorize')
                    if lookup_status != 200:
                        raise Unavailable()
                    if pay.get('status') == 'captured':
                        phase = 'captured'
                    elif pay.get('status') == 'declined':
                        phase = 'declined'
                    elif pay.get('status') == 'authorized':
                        payment_id = pay.get('payment_id')
                    elif pay.get('status') == 'unknown' and phase == 'authorizing' and payment_token:
                        # The provider has authoritatively found no authorization.
                        # Only a customer replay supplies the original token; retry
                        # the same stable key, never a second payment identity.
                        phase = 'confirmed'
                    else:
                        return JSONResponse(pending(row), 200 if is_get else 202)
                if phase == 'confirmed':
                    if not payment_token:
                        return JSONResponse(pending(row), 200 if is_get else 202)
                    save(oid, phase='authorizing')
                    status, pay = call(payment_client, 'POST', '/authorize', 1, oid + ':authorize',
                                       {'order_id': oid, 'payment_method_token': payment_token})
                    if status == 402 or pay.get('status') == 'declined':
                        phase = 'declined'
                    elif status == 200 and pay.get('status') == 'authorized' and pay.get('payment_id'):
                        payment_id = pay['payment_id']
                        save(oid, payment=payment_id)
                    else:
                        return JSONResponse(pending(row), 200 if is_get else 202)
                if phase not in ('captured', 'declined'):
                    save(oid, phase='capturing', payment=payment_id)
                    status, pay = call(payment_client, 'POST', '/capture', 1, oid + ':capture',
                                       {'order_id': oid, 'payment_id': payment_id})
                    if status == 402 or pay.get('status') == 'declined':
                        phase = 'declined'
                    elif status == 200 and pay.get('status') == 'captured':
                        phase = 'captured'
                    else:
                        return JSONResponse(pending(row), 200 if is_get else 202)
                save(oid, phase=phase)
            if phase == 'declined':
                try:
                    _, released = stock('POST', f'/v1/reservations/{reservation}/release', oid + ':release')
                    if released.get('status') != 'released':
                        raise Unavailable()
                except Unavailable:
                    return JSONResponse(pending(row), 200 if is_get else 202)
                return terminal(row, 402, envelope('PAYMENT_DECLINED', rid))
            if phase == 'captured':
                with connect() as conn:
                    conn.execute('INSERT OR IGNORE INTO outbox(order_id) VALUES(?)', (oid,))
                    entry = conn.execute('SELECT * FROM outbox WHERE order_id=?', (oid,)).fetchone()
                spot = entry['spot']
                if not entry['dispatched']:
                    if queue is not None:
                        try:
                            queue.enqueue(oid)
                        except Exception:
                            return JSONResponse(pending(row, 'ORDER_PENDING'), 200 if is_get else 202)
                    with connect() as conn:
                        conn.execute('UPDATE outbox SET dispatched=1 WHERE order_id=?', (oid,))
                return terminal(row, 201, {'status': 'accepted', 'order_id': oid,
                    'store_id': json.loads(row['basket'])['store_id'], 'queue_spot': spot, 'request_id': rid})
        except Unavailable:
            with connect() as conn:
                current = conn.execute('SELECT phase FROM attempts WHERE id=?', (oid,)).fetchone()['phase']
            if current in ('authorizing', 'capturing', 'captured', 'declined'):
                return JSONResponse(pending(row), 200 if is_get else 202)
            return unavailable(rid)
        return unavailable(rid)

    async def handle(request, order_id=None):
        rid = request.headers.get('x-request-id') or str(uuid4())
        owner = identity(request)
        if owner is None:
            return JSONResponse(envelope('UNAUTHORIZED', rid), 401)
        if order_id is None:
            try:
                raw = await request.json()
                if any(key in raw and raw[key] is None for key in ('submitted_at', 'availability_token')):
                    raise ValueError()
                model = OrderInput.model_validate(raw)
                key = request.headers.get('idempotency-key', '')
                if not key or not request.headers.get('x-request-id'):
                    raise ValueError()
                payload = model.model_dump(exclude_none=True)
                for item in payload['items']:
                    if any(not value for value in item['add_ins']):
                        raise ValueError()
                if model.submitted_at:
                    if datetime.fromisoformat(model.submitted_at.replace('Z', '+00:00')).tzinfo is None:
                        raise ValueError()
            except (ValidationError, ValueError, TypeError):
                return JSONResponse(envelope('INVALID_ORDER', rid,
                    'Provide a valid store, basket, and idempotency key.'), 422)
            # Tokens are fingerprinted only; no plaintext token is persisted.
            canonical = dict(payload)
            canonical['items'] = sorted(
                [{**item, 'add_ins': sorted(item['add_ins'])} for item in payload['items']],
                key=lambda item: item['line_item_number'])
            fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            basket = {k: v for k, v in payload.items() if k in ('store_id', 'items', 'submitted_at')}
        with connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if order_id is None:
                conn.execute('INSERT OR IGNORE INTO attempts(id,owner,key,fingerprint,basket,availability,request_id,phase) VALUES(?,?,?,?,?,?,?,?)',
                    (str(uuid4()), owner, key, fingerprint, json.dumps(basket), payload.get('availability_token'), rid, 'new'))
                row = conn.execute('SELECT * FROM attempts WHERE owner=? AND key=?', (owner, key)).fetchone()
                if row['fingerprint'] != fingerprint:
                    return JSONResponse(envelope('IDEMPOTENCY_CONFLICT', rid), 409)
            else:
                row = conn.execute('SELECT * FROM attempts WHERE id=?', (order_id,)).fetchone()
                if row is None:
                    return JSONResponse(envelope('RESERVATION_NOT_FOUND', rid), 404)
                if row['owner'] != owner:
                    return JSONResponse(envelope('FORBIDDEN', rid), 403)
            if row['response']:
                return JSONResponse(json.loads(row['response']), 200 if order_id and row['status'] == 201 else row['status'])
            if row['lease'] > time.time():
                return unavailable(rid)
            conn.execute('UPDATE attempts SET lease=? WHERE id=?', (time.time() + 10, row['id']))
        try:
            return process(row, request, None if order_id else model.payment_method_token, is_get=bool(order_id))
        finally:
            save(row['id'], lease=0)

    @app.post('/v1/orders')
    async def place_order(request: Request):
        return await handle(request)

    @app.get('/v1/health')
    def health():
        with connect() as conn:
            conn.execute('SELECT 1').fetchone()
        configured = bool(injected or (inbound_secret and stock_secret and (payment_secret or development_payment)))
        return JSONResponse({'status': 'ok' if configured else 'unconfigured'}, 200 if configured else 503)

    @app.get('/v1/orders/{order_id}')
    async def get_order(order_id: str, request: Request):
        return await handle(request, order_id)

    return app


app = create_app()
