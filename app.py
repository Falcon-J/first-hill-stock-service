"""Read-only stock API for the supplied historical Seattle snapshot."""

import csv
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DATA = Path(__file__).resolve().parent / 'data' / 'stock_snapshot.csv'
MILKS = {'oat_milk', 'almond_milk', 'two_pct_milk'}


class Stock(BaseModel):
    store_id: str
    store_name: str
    store_open: bool
    component_id: str
    component_name: str
    component_type: str
    quantity_on_hand: int
    reserved_quantity: int
    available_quantity: int
    sold_out: bool
    orderable: bool
    last_updated_at: str


def load_snapshot(path: Path) -> dict[tuple[str, str], Stock]:
    required = set(Stock.model_fields) - {'available_quantity', 'sold_out', 'orderable'}
    result = {}
    stores = {}
    with path.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Snapshot is missing required columns')
        for line, row in enumerate(reader, start=2):
            try:
                values = {key: row[key] for key in required}
                if any(value is None or not value.strip() for value in values.values()):
                    raise ValueError('Empty required value')
                if row['store_open'] not in {'true', 'false'}:
                    raise ValueError('store_open must be true or false')
                quantity = int(row['quantity_on_hand'])
                reserved = int(row['reserved_quantity'])
                if quantity < 0 or reserved < 0:
                    raise ValueError('Stock counts must be nonnegative')
                timestamp = datetime.fromisoformat(row['last_updated_at'])
                if timestamp.tzinfo is None:
                    raise ValueError('Timestamp must include timezone')
                key = (row['store_id'], row['component_id'])
                if key in result:
                    raise ValueError('Duplicate store/component pair')
                metadata = (row['store_name'], row['store_open'])
                if row['store_id'] in stores and stores[row['store_id']] != metadata:
                    raise ValueError('Inconsistent store metadata')
                stores[row['store_id']] = metadata
                available = max(0, quantity - reserved)
                result[key] = Stock(**values, available_quantity=available,
                    sold_out=available == 0,
                    orderable=row['store_open'] == 'true' and available > 0)
            except (ValueError, TypeError) as error:
                raise ValueError(f'Invalid snapshot at CSV line {line}: {error}') from error
    if not result:
        raise ValueError('Snapshot contains no stock rows')
    return result


stock = load_snapshot(DATA)
app = FastAPI(title='Seattle Snapshot Stock Service', version='1.0.0',
    description='Historical snapshot, 7 March 2025 06:45. '
                'Available = max(0, quantity_on_hand - reserved_quantity). '
                'Read-only; does not reserve stock or accept orders.')


@app.get('/health')
def health():
    return {'status': 'ok', 'rows': len(stock),
            'stores': len({key[0] for key in stock})}


def store_rows(store_id: str) -> list[Stock]:
    rows = [row for (store, _), row in stock.items() if store == store_id]
    if not rows:
        raise HTTPException(404, 'Store not found')
    return rows


@app.get('/stores/{store_id}/stock', response_model=list[Stock])
def get_store_stock(store_id: str):
    return store_rows(store_id)


@app.get('/stores/{store_id}/milks', response_model=list[Stock])
def get_store_milks(store_id: str):
    return [row for row in store_rows(store_id) if row.component_id in MILKS]


@app.get('/stores/{store_id}/stock/{component_id}', response_model=Stock)
def get_component_stock(store_id: str, component_id: str):
    row = stock.get((store_id, component_id))
    if row is None:
        raise HTTPException(404, 'Store/component not found')
    return row
