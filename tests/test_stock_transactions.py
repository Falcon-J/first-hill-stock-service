"""Independent inventory owners must serialize against the durable stock file."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import multiprocessing
import os
import sqlite3
from threading import Barrier

from fastapi.testclient import TestClient
import pytest

from services.stock.app import create_app
from services.stock.inventory import Inventory

NOW = datetime(2025, 3, 7, 14, 31, tzinfo=timezone.utc)
STATE = {'stores': {'SB-10482': {'store_open': True, 'components': {
    'oat_milk': {'quantity_on_hand': 1, 'reserved_quantity': 0},
    'espresso_signature': {'quantity_on_hand': 142, 'reserved_quantity': 4}}}},
    'recipes': {'Caffè Latte|Grande|Oatmilk|': {'oat_milk': 1, 'espresso_signature': 1}}}
BASKET = {'store_id': 'SB-10482', 'items': [{'line_item_number': 1,
    'drink_name': 'Caffè Latte', 'size': 'Grande', 'milk': 'Oatmilk',
    'add_ins': [], 'quantity': 1}]}


def reserve(inventory, number):
    return inventory.reserve('order-service', f'key-{number}',
        {'order_id': f'order-{number}', 'basket': BASKET}, f'req-{number}')


def test_independent_instances_cannot_reserve_same_last_unit(tmp_path):
    path = tmp_path / 'stock.sqlite'
    inventories = [Inventory(STATE, lambda: NOW, path) for _ in range(2)]
    start = Barrier(2)
    def attempt(number):
        start.wait(timeout=5)
        return reserve(inventories[number], number)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [0, 1]))
    assert sorted(result[0] for result in results) == [201, 409]
    refused = next(result[1] for result in results if result[0] == 409)
    assert refused['error']['missing_component'] == 'Oatmilk'
    assert inventories[0].snapshot('SB-10482')['oat_milk']['reserved_quantity'] == 1
    assert inventories[1].snapshot('SB-10482')['oat_milk']['reserved_quantity'] == 1


def process_reserve(path, barrier, output, number):
    inventory = Inventory(STATE, lambda: NOW, path)
    barrier.wait(timeout=20)
    output.put(reserve(inventory, number))


def test_two_stock_processes_share_atomic_reservation(tmp_path):
    context = multiprocessing.get_context('spawn')
    barrier, output = context.Barrier(2), context.Queue()
    path = str(tmp_path / 'stock.sqlite')
    processes = [context.Process(target=process_reserve, args=(path, barrier, output, n)) for n in range(2)]
    for process in processes:
        process.start()
    results = [output.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    assert sorted(result[0] for result in results) == [201, 409]
    restarted = Inventory(STATE, lambda: NOW, path)
    assert restarted.snapshot('SB-10482')['oat_milk']['reserved_quantity'] == 1


def crash_during_stock_write(path, committed):
    inventory = Inventory(STATE, lambda: NOW, path)
    if committed:
        reserve(inventory, 0)
        os._exit(23)
    with inventory.transaction():
        inventory.data['state']['stores']['SB-10482']['components']['oat_milk']['reserved_quantity'] = 1
        inventory.save()
        os._exit(23)


def test_crash_rolls_back_uncommitted_write_and_expires_committed_hold(tmp_path):
    context = multiprocessing.get_context('spawn')
    uncommitted = str(tmp_path / 'uncommitted.sqlite')
    process = context.Process(target=crash_during_stock_write, args=(uncommitted, False))
    process.start(); process.join(timeout=20)
    assert process.exitcode == 23
    restarted = Inventory(STATE, lambda: NOW, uncommitted)
    assert restarted.snapshot('SB-10482')['oat_milk']['reserved_quantity'] == 0
    committed = str(tmp_path / 'committed.sqlite')
    process = context.Process(target=crash_during_stock_write, args=(committed, True))
    process.start(); process.join(timeout=20)
    assert process.exitcode == 23
    before_expiry = Inventory(STATE, lambda: NOW + timedelta(seconds=119), committed)
    status, hold = before_expiry.get('order-service', key='key-0')
    assert status == 200 and hold['status'] == 'reserved'
    assert datetime.fromisoformat(hold['expires_at']) == NOW + timedelta(seconds=120)
    at_expiry = Inventory(STATE, lambda: NOW + timedelta(seconds=120), committed)
    assert at_expiry.get('order-service', key='key-0')[1]['status'] == 'expired'
    assert at_expiry.snapshot('SB-10482')['oat_milk'] == {'quantity_on_hand': 1, 'reserved_quantity': 0}


def test_database_contention_returns_defined_fail_closed_response(tmp_path):
    path = tmp_path / 'busy.sqlite'
    client = TestClient(create_app(initial_state=STATE, clock=lambda: NOW,
        authenticate=lambda token: token == 'test-only', storage_path=path), raise_server_exceptions=False)
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute('BEGIN IMMEDIATE')
    try:
        result = client.post('/v1/reservations', json={'order_id': 'blocked', 'basket': BASKET}, headers={
            'Authorization': 'Bearer test-only', 'Idempotency-Key': 'blocked',
            'X-Request-ID': 'req-busy', 'X-Request-Deadline': (NOW + timedelta(seconds=3)).isoformat()})
        assert result.status_code == 503
        assert result.json()['error']['code'] == 'STOCK_CHECK_UNAVAILABLE'
    finally:
        blocker.rollback(); blocker.close()
    assert client.app.state.inventory.snapshot('SB-10482')['oat_milk']['reserved_quantity'] == 0


def test_reload_failure_releases_writer_lock_for_same_and_other_worker(tmp_path):
    path = tmp_path / 'reload.sqlite'
    inventory = Inventory(STATE, lambda: NOW, path)
    denied = False
    def authorizer(action, table, *unused):
        nonlocal denied
        if action == sqlite3.SQLITE_READ and table == 'inventory_state' and not denied:
            denied = True
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    inventory.connection.set_authorizer(authorizer)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            inventory.snapshot('SB-10482')
        assert inventory.connection.in_transaction is False
        inventory.connection.set_authorizer(None)
        assert inventory.snapshot('SB-10482')['oat_milk']['reserved_quantity'] == 0
        other = Inventory(STATE, lambda: NOW, path)
        assert reserve(other, 'after-fault')[0] == 201
        assert inventory.snapshot('SB-10482')['oat_milk']['reserved_quantity'] == 1
    finally:
        inventory.connection.set_authorizer(None)
        inventory.connection.rollback()
