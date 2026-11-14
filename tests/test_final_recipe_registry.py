"""Menu registration is separate from authoritative stock coverage.

Supplemented rows below are synthetic unit fixtures, never replay input.
"""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from checks.final_replay_support import load_inputs, order_payload
from services.stock.app import create_app
from services.stock.catalogue import demo_recipe, load_snapshot

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ('MO-20250310-0302', 0, {'cold_brew': 1}),
    ('MO-20250310-0302', 1, {'espresso_signature': 1}),
    ('MO-20250310-0553', 0, {'strawberry_acai_base': 1, 'coconut_milk': 1}),
    ('MO-20250310-1268', 0, {'chai_concentrate': 1, 'two_pct_milk': 1}),
]


def source_basket(order_id):
    _, groups, _ = load_inputs(ROOT / 'docs/final-replay')
    basket = order_payload(groups[order_id])
    del basket['payment_method_token']
    return basket


@pytest.mark.parametrize('order_id,index,expected', CASES)
def test_all_four_source_lines_resolve_required_demo_recipe(order_id, index, expected):
    assert demo_recipe(source_basket(order_id)['items'][index]) == expected


def reserve(state, order_id, monkeypatch):
    monkeypatch.delenv('STOCK_STORAGE_PATH', raising=False)
    now = datetime(2025, 3, 10, 14, tzinfo=timezone.utc)
    app = create_app(initial_state=state, clock=lambda: now, authenticate=lambda token: True)
    with TestClient(app) as client:
        response = client.post('/v1/reservations',
            json={'order_id': order_id, 'basket': source_basket(order_id)},
            headers={'Authorization': 'Bearer unit-test', 'Idempotency-Key': order_id,
                     'X-Request-ID': 'recipe-proof',
                     'X-Request-Deadline': (now + timedelta(seconds=3)).isoformat()})
    return response, app.state.inventory


@pytest.mark.parametrize('order_id', [case[0] for case in CASES[::2]] + ['MO-20250310-1268'])
def test_real_source_missing_ingredients_are_not_invalid_recipes(order_id, monkeypatch):
    state = load_snapshot(ROOT / 'docs/final-replay/stock.csv')
    before = copy.deepcopy(state)
    response, inventory = reserve(state, order_id, monkeypatch)
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'UNKNOWN_ITEM', response.text
    assert response.json()['error']['message'] == 'Recipe component is not in this store catalogue.'
    assert inventory.data['state'] == before
    assert inventory.data['reservations'] == {}
    assert state == before


@pytest.mark.parametrize('order_id,expected', [
    ('MO-20250310-0302', {'synthetic-cold-brew': 1, 'CMP-201': 1}),
    ('MO-20250310-0553', {'synthetic-acai': 3, 'synthetic-coconut': 3}),
    ('MO-20250310-1268', {'synthetic-chai': 1, 'CMP-101': 1}),
])
def test_registered_baskets_hold_all_components_with_synthetic_stock(order_id, expected, monkeypatch):
    state = load_snapshot(ROOT / 'docs/final-replay/stock.csv')
    components = state['stores']['STB-10342']['components']
    for key, name, kind in [
        ('synthetic-cold-brew', 'cold brew', 'base'),
        ('synthetic-acai', 'strawberry açaí base', 'base'),
        ('synthetic-coconut', 'coconut milk', 'milk'),
        ('synthetic-chai', 'chai concentrate', 'base'),
    ]:
        components[key] = {'component_name': name, 'component_type': kind,
                           'quantity_on_hand': 10, 'reserved_quantity': 0,
                           'last_updated_at': '2025-03-10T06:45:00-07:00'}
    before = copy.deepcopy(components)
    response, inventory = reserve(state, order_id, monkeypatch)
    assert response.status_code == 201, response.text
    allocations = response.json()['allocations']
    assert {item['component_id']: item['units'] for item in allocations} == expected
    after = inventory.components('STB-10342')
    for key, row in before.items():
        assert after[key]['reserved_quantity'] == row['reserved_quantity'] + expected.get(key, 0)
        assert after[key]['quantity_on_hand'] == row['quantity_on_hand']


def test_pink_drink_cannot_omit_its_required_coconut_milk():
    line = source_basket('MO-20250310-0553')['items'][0]
    line['milk'] = 'none'
    assert demo_recipe(line) == {'strawberry_acai_base': 1, 'coconut_milk': 1}
