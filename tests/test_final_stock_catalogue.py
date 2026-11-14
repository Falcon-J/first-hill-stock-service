"""Known menu spellings must reach actual final stock, never invented recipes."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from checks.final_replay_support import load_inputs, order_payload
from services.stock.app import create_app
from services.stock.catalogue import load_snapshot

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('order_id', ['MO-20250310-0209', 'MO-20250310-0624'])
def test_final_oat_alias_reaches_real_zero_stock_without_hold(order_id, monkeypatch):
    monkeypatch.delenv('STOCK_STORAGE_PATH', raising=False)
    state = load_snapshot(ROOT / 'docs/final-replay/stock.csv')
    _, groups, _ = load_inputs(ROOT / 'docs/final-replay')
    basket = order_payload(groups[order_id])
    del basket['payment_method_token']
    now = datetime(2025, 3, 10, 14, tzinfo=timezone.utc)
    app = create_app(initial_state=state, clock=lambda: now, authenticate=lambda token: True)
    before = copy.deepcopy(app.state.inventory.data)
    with TestClient(app) as client:
        response = client.post('/v1/reservations', json={'order_id': order_id, 'basket': basket},
            headers={'Authorization': 'Bearer test-only', 'Idempotency-Key': order_id,
                     'X-Request-ID': 'req-oat', 'X-Request-Deadline': (now + timedelta(seconds=3)).isoformat()})
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'BASE_OUT_OF_STOCK'
    assert response.json()['error']['missing_component'] == 'oat milk'
    assert response.json()['error']['line_item_number'] == 1
    assert app.state.inventory.data['state'] == before['state']
    assert app.state.inventory.data['reservations'] == {}
    assert state['stores']['STB-10342']['components']['CMP-104']['quantity_on_hand'] == 0
    assert state['stores']['STB-10342']['components']['CMP-104']['reserved_quantity'] == 0


def test_final_component_name_mapping_rejects_ambiguity():
    from services.stock.catalogue import demo_recipe
    state = load_snapshot(ROOT / 'docs/final-replay/stock.csv')
    components = state['stores']['STB-10342']['components']
    components['duplicate-oat'] = copy.deepcopy(components['CMP-104'])
    line = {'drink_name': 'Caffè Latte', 'size': 'Grande', 'milk': 'oat', 'add_ins': []}
    with pytest.raises(ValueError, match='Ambiguous'):
        demo_recipe(line, components)


def test_final_topping_category_keeps_add_in_refusal(monkeypatch):
    monkeypatch.delenv('STOCK_STORAGE_PATH', raising=False)
    state = load_snapshot(ROOT / 'docs/final-replay/stock.csv')
    now = datetime(2025, 3, 10, 14, tzinfo=timezone.utc)
    app = create_app(initial_state=state, clock=lambda: now, authenticate=lambda token: True)
    basket = {'store_id': 'STB-10518', 'items': [{'line_item_number': 1, 'drink_name': 'Caffè Latte',
        'size': 'Grande', 'milk': '2%', 'add_ins': ['caramel drizzle'], 'quantity': 1}]}
    with TestClient(app) as client:
        response = client.post('/v1/reservations', json={'order_id': 'topping-proof', 'basket': basket},
            headers={'Authorization': 'Bearer test-only', 'Idempotency-Key': 'topping-proof',
                     'X-Request-ID': 'req-topping', 'X-Request-Deadline': (now + timedelta(seconds=3)).isoformat()})
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'ADD_IN_OUT_OF_STOCK'
    assert response.json()['error']['missing_component'] == 'caramel drizzle'
    assert app.state.inventory.data['state'] == state
    assert app.state.inventory.data['reservations'] == {}


def test_aliases_cannot_hide_duplicate_add_ins():
    from services.stock.catalogue import demo_recipe
    line = {'drink_name': 'Caffè Latte', 'size': 'Grande', 'milk': 'oat',
            'add_ins': ['Brown Sugar Syrup', 'brown sugar syrup']}
    with pytest.raises(ValueError, match='Duplicate'):
        demo_recipe(line)


def test_known_recipe_missing_component_preserves_unknown_item():
    from services.stock.inventory import Inventory, Refusal
    state = load_snapshot()
    del state['stores']['10482']['components']['oat_milk']
    inventory = Inventory(state, lambda: datetime(2025, 3, 10, tzinfo=timezone.utc))
    basket = {'store_id': '10482', 'items': [{'line_item_number': 1, 'drink_name': 'Caffè Latte',
        'size': 'Grande', 'milk': 'Oatmilk', 'add_ins': [], 'quantity': 1}]}
    with pytest.raises(Refusal) as refusal:
        inventory.demand(basket)
    assert refusal.value.status == 422
    assert refusal.value.code == 'UNKNOWN_ITEM'
    assert refusal.value.message == 'Recipe component is not in this store catalogue.'
    assert inventory.data['reservations'] == {}
