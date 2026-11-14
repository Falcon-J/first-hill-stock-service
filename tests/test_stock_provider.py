"""Stock-owned integration tests, independent of sample refusal answers."""
import copy
import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

BASKET = {'store_id': 'SB-10482', 'items': [{'line_item_number': 1,
    'drink_name': 'Caffè Latte', 'size': 'Grande', 'milk': 'Oatmilk',
    'add_ins': [], 'quantity': 1}]}


def client(**kwargs):
    try:
        factory = importlib.import_module('services.stock.app').create_app
    except ModuleNotFoundError:
        pytest.fail('Stock provider implementation missing')
    return TestClient(factory(authenticate=lambda token: token in {'alice', 'bob'}, **kwargs))


def headers(owner='alice', key='attempt'):
    return {'Authorization': f'Bearer {owner}', 'Idempotency-Key': key,
        'X-Request-ID': 'stock-test', 'X-Request-Deadline': (
            datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat()}


def test_default_snapshot_oat_refusal_is_component_specific():
    app = client()
    result = app.post('/v1/reservations', headers=headers(), json={'order_id': 'oat', 'basket': BASKET})
    assert result.status_code == 409
    assert result.json()['error']['code'] == 'BASE_OUT_OF_STOCK'
    assert result.json()['error']['missing_component'] == 'Oatmilk'
    assert result.json()['error']['line_item_number'] == 1
    assert app.app.state.inventory.snapshot('10482')['espresso_signature']['quantity_on_hand'] == 142


def test_owner_isolation_persistence_and_feed_does_not_restore_consumed_stock(tmp_path):
    path = tmp_path / 'stock.sqlite'
    app = client(storage_path=path)
    basket = copy.deepcopy(BASKET)
    basket['items'][0]['milk'] = '2% Milk'
    result = app.post('/v1/reservations', headers=headers(), json={'order_id': 'milk', 'basket': basket})
    assert result.status_code == 201
    reservation_id = result.json()['reservation_id']
    for suffix in ['', '/confirm', '/release']:
        operation = app.get if not suffix else app.post
        response = operation(f'/v1/reservations/{reservation_id}{suffix}', headers=headers('bob'))
        assert response.status_code in {403, 404}
    assert app.get('/v1/reservations/by-key/attempt', headers=headers('bob')).status_code == 404
    assert app.post(f'/v1/reservations/{reservation_id}/confirm', headers=headers(key='confirm')).status_code == 200
    app.app.state.inventory.apply_feed('10482', {'two_pct_milk': {'quantity_on_hand': 96}})
    assert app.app.state.inventory.snapshot('10482')['two_pct_milk']['quantity_on_hand'] == 95
    restarted = client(storage_path=path)
    assert restarted.get(f'/v1/reservations/{reservation_id}', headers=headers()).json()['status'] == 'confirmed'
    assert restarted.app.state.inventory.snapshot('10482')['two_pct_milk']['quantity_on_hand'] == 95
    assert restarted.post(f'/v1/reservations/{reservation_id}/release', headers=headers(key='release')).status_code == 200
    assert restarted.app.state.inventory.snapshot('10482')['two_pct_milk']['quantity_on_hand'] == 96


@pytest.mark.parametrize('field,value', [('size', 'Unknown'), ('drink_name', 'Unknown'),
    ('milk', 'Unknown'), ('add_ins', ['Unknown'])])
def test_unknown_catalogue_is_never_fabricated(field, value):
    app = client()
    basket = copy.deepcopy(BASKET)
    basket['items'][0][field] = value
    result = app.post('/v1/reservations', headers=headers(), json={'order_id': 'unknown', 'basket': basket})
    assert result.status_code == 422
    assert result.json()['error']['code'] in {'INVALID_ORDER', 'UNKNOWN_ITEM'}


def test_success_and_failure_responses_validate_frozen_contract():
    from pathlib import Path
    import yaml
    from jsonschema import Draft202012Validator
    document = yaml.safe_load((Path(__file__).resolve().parents[1] / 'contracts/stock-service.openapi.yaml').read_text(encoding='utf8'))
    app = client()
    for milk, expected in [('Oatmilk', 409), ('2% Milk', 201)]:
        basket = copy.deepcopy(BASKET)
        basket['items'][0]['milk'] = milk
        result = app.post('/v1/reservations', headers=headers(key=milk), json={'order_id': milk, 'basket': basket})
        assert result.status_code == expected
        schema = document['paths']['/v1/reservations']['post']['responses'][str(expected)]['content']['application/json']['schema']
        Draft202012Validator({**schema, 'components': document['components']}).validate(result.json())


@pytest.mark.parametrize('field', ['submitted_at', 'availability_token'])
def test_optional_contract_strings_reject_explicit_null(field):
    app = client()
    payload = {'order_id': 'null-field', 'basket': copy.deepcopy(BASKET)}
    if field == 'submitted_at':
        payload['basket'][field] = None
    else:
        payload[field] = None
    result = app.post('/v1/reservations', headers=headers(), json=payload)
    assert result.status_code == 422
    assert result.json()['error']['code'] == 'INVALID_ORDER'


def test_no_unversioned_public_routes():
    app = client()
    assert app.get('/v1/health').status_code == 200
    for path in ['/health', '/docs', '/redoc', '/openapi.json']:
        assert app.get(path).status_code == 404
