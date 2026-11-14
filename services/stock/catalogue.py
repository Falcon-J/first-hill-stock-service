"""Explicit demo catalogue and snapshot loader owned only by inventory.

Recipe units are demo units, not claimed historical Starbucks recipes.
Unsupported drinks/components fail closed rather than inventing stock.
"""
import csv
from pathlib import Path

COMPONENTS = {
    'espresso_signature': ('Signature Espresso Roast', 'drink_base'),
    'oat_milk': ('Oatmilk', 'drink_base'),
    'almond_milk': ('Almondmilk', 'drink_base'),
    'two_pct_milk': ('2% Milk', 'drink_base'),
    'brown_sugar_syrup': ('Brown Sugar Syrup', 'add_in'),
    'vanilla_syrup': ('Vanilla Syrup', 'add_in'),
    'vanilla_sweet_cream_cold_foam': ('Vanilla Sweet Cream Cold Foam', 'add_in'),
    'matcha_powder': ('Matcha Tea Powder', 'drink_base'),
    'caramel_drizzle': ('Caramel Drizzle', 'add_in'),
    'cups_ice': ('Cups & Ice', 'drink_base'),
}
MILKS = {'Oatmilk': 'oat_milk', 'Almondmilk': 'almond_milk', '2% Milk': 'two_pct_milk'}
ADD_INS = {name: component for component, (name, kind) in COMPONENTS.items() if kind == 'add_in'}
DRINKS = {
    'Caffè Latte': {'espresso_signature': 1},
    'Iced Brown Sugar Oatmilk Shaken Espresso': {'espresso_signature': 1, 'brown_sugar_syrup': 1},
    'Matcha Latte': {'matcha_powder': 1},
    'Iced Matcha Latte': {'matcha_powder': 1},
}
SIZES = {'Tall', 'Grande', 'Venti'}


def recipe_key(line):
    return '|'.join([line['drink_name'], line['size'], line['milk'], ','.join(sorted(line['add_ins']))])


def demo_recipe(line):
    if line['drink_name'] not in DRINKS or line['size'] not in SIZES:
        raise ValueError('Unsupported drink or size')
    if line['milk'] not in {*MILKS, 'None'} or any(add not in ADD_INS for add in line['add_ins']):
        raise ValueError('Unsupported milk or add-in')
    result = dict(DRINKS[line['drink_name']])
    if line['milk'] != 'None':
        result[MILKS[line['milk']]] = 1
    for add in line['add_ins']:
        result[ADD_INS[add]] = 1
    # This recipe inherently requires oat milk; a client cannot silently remove it.
    if line['drink_name'] == 'Iced Brown Sugar Oatmilk Shaken Espresso':
        result['oat_milk'] = 1
    return result


def load_snapshot(path=None):
    path = Path(path) if path else Path(__file__).resolve().parents[2] / 'data/stock_snapshot.csv'
    stores = {}
    with path.open(newline='', encoding='utf-8-sig') as source:
        for row in csv.DictReader(source):
            if row['store_open'] not in {'true', 'false'}:
                raise ValueError('Invalid store open state')
            store = stores.setdefault(row['store_id'], {'store_name': row['store_name'],
                'store_open': row['store_open'] == 'true', 'components': {}})
            if store['store_open'] != (row['store_open'] == 'true') or store['store_name'] != row['store_name']:
                raise ValueError('Inconsistent store metadata')
            component = row['component_id']
            if component in store['components']:
                raise ValueError('Duplicate component')
            counts = {field: int(row[field]) for field in ['quantity_on_hand', 'reserved_quantity']}
            if any(value < 0 for value in counts.values()):
                raise ValueError('Negative inventory')
            store['components'][component] = {**counts, 'component_name': row['component_name'],
                'component_type': row['component_type'], 'last_updated_at': row['last_updated_at']}
    if not stores:
        raise ValueError('Empty snapshot')
    return {'stores': stores, 'aliases': {'SB-10482': '10482'}, 'recipes': {}}
