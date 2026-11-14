"""Explicit socket proofs: pytest -q checks/live_overselling.py.

Requires the isolated first-hill-overselling Compose stack. Never collected by
the normal tests/ suite; missing Docker or an unstarted stack is a failure.
Fixtures are synthetic preconditions, not claims about historical stock.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import csv
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('live_replay_support', ROOT / 'tests/replay_support.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
COMPOSE = ['docker', 'compose', '-p', 'first-hill-overselling', '-f', 'compose.overselling.yaml']
GATEWAY = 'http://127.0.0.1:18081'
STOCK = 'http://127.0.0.1:18082'
REPORTS = ROOT / 'docs/overselling'


def credential(name):
    """Read local configuration without logging or serializing credentials."""
    if os.environ.get(name):
        return os.environ[name]
    for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines():
        key, separator, value = line.partition('=')
        if separator and key.strip() == name:
            return value.strip().strip('\"\'')
    raise RuntimeError(f'Missing local configuration: {name}')


def operator(service, script, payload=None, *args):
    result = subprocess.run(COMPOSE + ['exec', '-T', service, 'python', '/checks/' + script, *args],
        cwd=ROOT, input=json.dumps(payload) if payload is not None else '',
        capture_output=True, text=True, timeout=30, encoding='utf-8')
    assert result.returncode == 0, f'{service} proof operator failed: {result.stderr}'
    return json.loads(result.stdout)


def seed(state):
    assert operator('stock', 'stock_fixture.py', state) == {'seeded': True}


def stock_view():
    return operator('stock', 'stock_fixture.py', None, '--inspect')


def effects(key, status):
    result = operator('order', 'order_inspect.py', {'idempotency_key': key})
    assert result['phase'] == 'done' and result['status'] == status, result
    assert result['payment_rows'] == result['outbox_rows'] == (1 if status == 201 else 0), result
    return result


def headers(key, request_id, stock=False):
    return {'Authorization': 'Bearer ' + credential('STOCK_SERVICE_TOKEN' if stock else 'GATEWAY_CUSTOMER_TOKEN'),
            'Idempotency-Key': key, 'X-Request-ID': request_id,
            'X-Request-Deadline': (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat()}


def post_order(basket, key, request_id, token=None):
    payload = {**basket, 'payment_method_token': 'synthetic-development-payment'}
    if token:
        payload['availability_token'] = token
    with httpx.Client(trust_env=False, timeout=15) as client:
        response = client.post(GATEWAY + '/v1/orders', headers=headers(key, request_id), json=payload)
    return response.status_code, response.json()


def menu(basket, key):
    response = httpx.post(STOCK + '/v1/availability', headers=headers(key, key, True),
                          json=basket, timeout=15, trust_env=False)
    assert response.status_code == 200 and response.json()['available'] is True, response.text
    return response.json()['availability_token']


def rival(basket, key):
    response = httpx.post(STOCK + '/v1/reservations', headers=headers(key, key, True),
        json={'order_id': key, 'basket': basket}, timeout=15, trust_env=False)
    return response.status_code, response.json()


def assert_conservation(before, after):
    """Every live allocation remains reflected in the physical/held counts."""
    for store_id, store in before['stores'].items():
        for component_id, original in store['components'].items():
            reserved = confirmed = 0
            for hold in after['reservations']:
                actual_store = before.get('aliases', {}).get(hold['store_id'], hold['store_id'])
                if actual_store != store_id:
                    continue
                for allocation in hold['allocations']:
                    if allocation['component_id'] == component_id:
                        reserved += allocation['units'] if hold['status'] == 'reserved' else 0
                        confirmed += allocation['units'] if hold['status'] == 'confirmed' else 0
            actual = after['state']['stores'][store_id]['components'][component_id]
            assert actual['quantity_on_hand'] == original['quantity_on_hand'] - confirmed
            assert actual['reserved_quantity'] == original['reserved_quantity'] + reserved
            assert 0 <= actual['reserved_quantity'] <= actual['quantity_on_hand']


def test_live_last_oat_unit_two_customer_race():
    row = next(row for row in support.load_orders() if row['order_id'] == 'MO-250307-0024')
    state, basket, _ = support.make_fixture(row)
    seed(state)
    run = uuid4().hex
    token = menu(basket, 'menu-' + run)
    keys = ['live-race-' + run + '-' + str(i) for i in range(2)]
    request_ids = ['req-live-race-' + str(i) for i in range(2)]
    barrier = Barrier(2)

    def submit(index):
        barrier.wait(timeout=10)
        return post_order(basket, keys[index], request_ids[index], token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert sorted(status for status, _ in results) == [201, 409], results
    evidence = []
    for index, (status, body) in enumerate(results):
        if status == 409:
            expected = copy.deepcopy(support.expected_refusal(row))
            expected['request_id'] = request_ids[index]
            assert body == expected
            assert body['error']['code'] == 'STOCK_CHANGED'
            assert body['error']['line_item_number'] == 1
            assert body['error']['missing_component'] == 'Oatmilk'
        effect = effects(keys[index], status)
        assert post_order(basket, keys[index], request_ids[index], token) == (status, body)
        assert effects(keys[index], status) == effect
        evidence.append({'http_status': status, 'response': body, 'effects': effect, 'replay_stable': True})
    after = stock_view()
    assert len(after['reservations']) == 1 and after['reservations'][0]['status'] == 'confirmed'
    assert_conservation(state, after)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / 'live-race.json').write_text(json.dumps({
        'transport': 'real HTTP sockets; isolated Docker Compose',
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'fixture_provenance': 'Synthetic last oat unit with sufficient espresso; not historical stock.',
        'results': evidence, 'stock': after}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def test_live_all_40_source_orders():
    rows = support.load_orders()
    assert len(rows) == 40
    run = uuid4().hex
    results = []
    accepted = refused = 0
    queue_spots = set()
    for row in rows:
        state, basket, metadata = support.make_fixture(row)
        seed(state)
        key = 'live-' + run + '-' + row['order_id']
        rid = 'req-' + row['order_id']
        token = menu(basket, key) if metadata['competitor_basket'] else None
        winning = None
        if metadata['losing_race']:
            status, winning = rival(metadata['competitor_basket'], key + '-rival')
            assert status == 201, winning
        before = stock_view()
        status, body = post_order(basket, key, rid, token)
        result = {'order_id': row['order_id'], 'csv_line': row['csv_line'],
                  'criterion': metadata['criterion'], 'expected': row['expected_outcome'],
                  'actual': 'accepted' if status == 201 else 'refused', 'http_status': status,
                  'component': body.get('error', {}).get('missing_component') or '',
                  'submitted_at': row['submitted_at'],
                  'response_json': json.dumps(body, ensure_ascii=False, sort_keys=True),
                  'result': 'FAIL', 'mismatch': '', 'provenance': metadata['provenance']}
        try:
            if row['expected_outcome'] == 'refused':
                assert status == 409 and body == support.expected_refusal(row), body
                refused += 1
                assert stock_view() == before
            else:
                assert status == 201, body
                assert body == {'status': 'accepted', 'order_id': body['order_id'],
                    'store_id': row['store_id'], 'queue_spot': body['queue_spot'], 'request_id': rid}
                assert body['order_id'] != row['order_id']
                assert type(body['queue_spot']) is int and body['queue_spot'] >= 1
                assert body['queue_spot'] not in queue_spots
                queue_spots.add(body['queue_spot'])
                accepted += 1
                if metadata['winning_race']:
                    rival_status, rival_body = rival(metadata['competitor_basket'], key + '-rival')
                    assert rival_status == 409, rival_body
            effect = effects(key, status)
            assert post_order(basket, key, rid, token) == (status, body)
            assert effects(key, status) == effect
            after = stock_view()
            assert_conservation(state, after)
            if winning:
                assert after['reservations'] == [winning]
            elif status == 201:
                assert len(after['reservations']) == 1
                assert after['reservations'][0]['status'] == 'confirmed'
            else:
                assert after['reservations'] == []
            result.update(result='PASS', payment_rows=effect['payment_rows'],
                          outbox_rows=effect['outbox_rows'], replay_stable=True)
        except AssertionError as error:
            result['mismatch'] = str(error)
            raise
        finally:
            results.append(result)
            REPORTS.mkdir(parents=True, exist_ok=True)
            fields = ['order_id', 'csv_line', 'criterion', 'expected', 'actual', 'http_status',
                      'component', 'submitted_at', 'response_json', 'result', 'mismatch',
                      'payment_rows', 'outbox_rows', 'replay_stable', 'provenance']
            with (REPORTS / 'live-replay-results.csv').open('w', newline='', encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(results)
    assert (accepted, refused) == (19, 21)


def test_live_stock_outage_refuses_before_payment():
    """Separate AC-E2 fault injection, not a new expected outcome in the CSV."""
    row = next(row for row in support.load_orders() if row['order_id'] == 'MO-250303-0002')
    state, basket, _ = support.make_fixture(row)
    seed(state)
    key = 'live-outage-' + uuid4().hex + '-' + row['order_id']
    rid = 'req-live-stock-outage'
    subprocess.run(COMPOSE + ['stop', 'stock'], cwd=ROOT, check=True, capture_output=True, timeout=60)
    try:
        status, body = post_order(basket, key, rid)
        expected = {'error': {'code': 'STOCK_CHECK_UNAVAILABLE',
            'message': "We can't confirm this store's stock right now. Please try again.",
            'line_item_number': None, 'missing_component': None, 'details': [],
            'retryable': True}, 'request_id': rid}
        assert status == 503 and body == expected, (status, body)
        effect = operator('order', 'order_inspect.py', {'idempotency_key': key})
        assert effect['phase'] == 'reserving' and effect['status'] is None
        assert effect['payment_rows'] == effect['outbox_rows'] == 0
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / 'live-stock-outage.json').write_text(json.dumps({
            'source_order_id': row['order_id'], 'source_normal_expected_outcome': row['expected_outcome'],
            'criterion': 'AC-E2', 'provenance': 'Separate synthetic outage: isolated stock container stopped before checkout.',
            'expected_status': 503, 'actual_status': status, 'response': body,
            'effects': effect, 'result': 'PASS'}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    finally:
        subprocess.run(COMPOSE + ['up', '--detach', '--wait', '--wait-timeout', '180', 'stock'],
            cwd=ROOT, check=True, capture_output=True, timeout=240)
