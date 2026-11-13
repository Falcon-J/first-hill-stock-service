import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app, load_snapshot

client = TestClient(app)
DATA = Path(__file__).resolve().parents[1] / 'data' / 'stock_snapshot.csv'


@pytest.mark.parametrize('component,on_hand,reserved,available,sold_out', [
    ('oat_milk', 0, 0, 0, True),
    ('almond_milk', 38, 1, 37, False),
    ('two_pct_milk', 96, 3, 93, False),
    ('espresso_signature', 142, 4, 138, False),
])
def test_first_hill(component, on_hand, reserved, available, sold_out):
    response = client.get(f'/stores/10482/stock/{component}')
    assert response.status_code == 200
    body = response.json()
    assert body['component_id'] == component
    assert body['quantity_on_hand'] == on_hand
    assert body['reserved_quantity'] == reserved
    assert body['available_quantity'] == available
    assert body['sold_out'] is sold_out
    assert body['orderable'] is (not sold_out)


def test_every_row_matches_snapshot():
    with DATA.open(newline='', encoding='utf-8-sig') as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 30
    assert len({row['store_id'] for row in rows}) == 3
    for row in rows:
        response = client.get(f"/stores/{row['store_id']}/stock/{row['component_id']}")
        assert response.status_code == 200
        body = response.json()
        expected = max(0, int(row['quantity_on_hand']) - int(row['reserved_quantity']))
        assert body['store_id'] == row['store_id']
        assert body['available_quantity'] == expected
        assert body['sold_out'] is (expected == 0)
        assert body['orderable'] is (row['store_open'] == 'true' and expected > 0)


def test_milks_and_store_listing():
    body = client.get('/stores/10482/milks').json()
    assert {row['component_id']: row['available_quantity'] for row in body} == {
        'oat_milk': 0, 'almond_milk': 37, 'two_pct_milk': 93}
    assert len(client.get('/stores/10482/stock').json()) == 10


@pytest.mark.parametrize('url', ['/stores/99999/stock', '/stores/99999/milks',
    '/stores/10482/stock/not_a_component'])
def test_unknown_key_is_404(url):
    assert client.get(url).status_code == 404


def test_health():
    assert client.get('/health').json() == {'status': 'ok', 'rows': 30, 'stores': 3}


@pytest.mark.parametrize('change', ['duplicate', 'negative', 'bad_bool', 'bad_date', 'missing'])
def test_bad_snapshot_rejected(tmp_path, change):
    with DATA.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        fields = reader.fieldnames
        rows = list(reader)
    if change == 'duplicate':
        rows.append(rows[0].copy())
    elif change == 'negative':
        rows[0]['quantity_on_hand'] = '-1'
    elif change == 'bad_bool':
        rows[0]['store_open'] = 'perhaps'
    elif change == 'bad_date':
        rows[0]['last_updated_at'] = 'yesterday'
    else:
        fields = [field for field in fields if field != 'reserved_quantity']
        rows = [{k: v for k, v in row.items() if k in fields} for row in rows]
    target = tmp_path / 'bad.csv'
    with target.open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError):
        load_snapshot(target)
