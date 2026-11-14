"""Synthetic historical-scenario fixtures, never historical inventory claims.

Only SB-10482 aliases a supplied snapshot ID. Recipes below are deliberately
one test-unit per ingredient, independent of expected outcomes and messages.
"""
import csv
import json
from pathlib import Path

from services.stock.catalogue import recipe_key

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'specs/001-order-refusals/evidence/mobile-orders-2025-03-03-to-09.csv'
BASES = {
    'Pike Place Roast': 'Pike roast test base',
    'Caffè Latte': 'Signature Espresso Roast',
    'Iced Caramel Macchiato': 'Signature Espresso Roast',
    'Iced Brown Sugar Oatmilk Shaken Espresso': 'Signature Espresso Roast',
    'Chai Tea Latte': 'Chai test concentrate',
    'Cold Brew': 'Cold brew test base',
    'Flat White': 'Signature Espresso Roast',
    'Matcha Tea Latte': 'Matcha Tea Powder',
    'Caramel Frappuccino': 'Frappuccino test base',
    'Vanilla Sweet Cream Cold Brew': 'Cold brew test base',
}
IDS = {'Signature Espresso Roast': 'espresso_signature', 'Oatmilk': 'oat_milk',
       'Brown Sugar Syrup': 'brown_sugar_syrup'}
CRITERIA = {'store_closed': 'AC-R1', 'base_out_of_stock': 'AC-R2',
            'add_in_out_of_stock': 'AC-R3', 'insufficient_quantity': 'AC-R4',
            'in_stock': 'AC-P1'}


def rows():
    with SOURCE.open(encoding='utf-8-sig', newline='') as handle:
        return [dict(row, csv_line=line) for line, row in enumerate(csv.DictReader(handle), 2)]


def load_orders():
    """Stable entry point shared by in-process and socket/container replays."""
    return rows()


def expected_refusal(row):
    cases = json.loads((ROOT / 'contracts/refusal-cases.json').read_text(encoding='utf-8'))
    expected = next(case for case in cases if case['order_id'] == row['order_id'])['expected_body']
    assert expected['error']['message'] == row['expected_message']
    assert expected['error']['missing_component'] == row['expected_missing_component']
    assert expected['error']['line_item_number'] == (None if row['scenario_tag'] == 'store_closed'
                                                   else int(row['line_item_number']))
    return expected


def make_fixture(row):
    state, order_basket, competitor, criterion = synthetic_fixture(row)
    return state, order_basket, {'competitor_basket': competitor, 'criterion': criterion,
                                'losing_race': criterion == 'AC-R5',
                                'winning_race': criterion == 'AC-P2',
                                'provenance': 'Synthetic test recipes/counts/hours; CSV is not stock history.'}


def component_id(name):
    return IDS.get(name, 'test_' + name.lower().replace(' ', '_').replace('%', 'pct'))


def basket(row):
    return {'store_id': row['store_id'], 'submitted_at': row['submitted_at'], 'items': [{
        'line_item_number': int(row['line_item_number']), 'drink_name': row['drink_name'],
        'size': row['size'], 'milk': row['milk'],
        'add_ins': row['add_ins'].split(';') if row['add_ins'] else [],
        'quantity': int(row['quantity'])}]}


def synthetic_fixture(row):
    """Build stock conditions from scenario tags, never service outcome switches."""
    order_basket = basket(row)
    line = order_basket['items'][0]
    ingredients = {BASES[line['drink_name']]: 'drink_base'}
    if line['milk'] != 'None':
        ingredients[line['milk']] = 'drink_base'
    ingredients.update({name: 'add_in' for name in line['add_ins']})
    if line['drink_name'] == 'Iced Brown Sugar Oatmilk Shaken Espresso':
        ingredients.update({'Oatmilk': 'drink_base', 'Brown Sugar Syrup': 'add_in'})
    if line['drink_name'] == 'Vanilla Sweet Cream Cold Brew':
        ingredients['Vanilla sweet cream test base'] = 'drink_base'
    recipe = {component_id(name): 1 for name in ingredients}
    components = {component_id(name): {'component_name': name, 'component_type': kind,
        'quantity_on_hand': 100, 'reserved_quantity': 0} for name, kind in ingredients.items()}
    tag = row['scenario_tag']
    # Named shortages are fixture preconditions supplied by source labels. They
    # are not passed to any service or used to select an HTTP response.
    missing = row['expected_missing_component']
    if tag in ('base_out_of_stock', 'add_in_out_of_stock'):
        components[component_id(missing)]['quantity_on_hand'] = 0
    elif tag == 'insufficient_quantity':
        components[component_id(missing)]['quantity_on_hand'] = line['quantity'] - 1
    elif tag == 'stock_runs_out_mid_order':
        # Accepted 0023 has no missing label: use its specified last oat unit.
        components[component_id(missing or 'Oatmilk')]['quantity_on_hand'] = 1
        if 'espresso_signature' in components:
            components['espresso_signature'].update(quantity_on_hand=142, reserved_quantity=4)
        if 'brown_sugar_syrup' in components:
            components['brown_sugar_syrup'].update(quantity_on_hand=64, reserved_quantity=2)
    store_id = '10482' if row['store_id'] == 'SB-10482' else row['store_id']
    state = {'aliases': {'SB-10482': '10482'}, 'recipes': {recipe_key(line): recipe},
             'stores': {store_id: {'store_name': 'Bellevue Square' if store_id == 'SB-20516'
                                 else 'First Hill' if store_id == '10482' else 'Synthetic SB-11937',
                                 'store_open': tag != 'store_closed', 'components': components}}}
    competitor = None
    if tag == 'stock_runs_out_mid_order':
        competitor = {'store_id': row['store_id'], 'items': [{
            'line_item_number': 1, 'drink_name': 'Synthetic competing unit',
            'size': 'Grande', 'milk': 'None', 'add_ins': [], 'quantity': 1}]}
        state['recipes'][recipe_key(competitor['items'][0])] = {component_id(missing or 'Oatmilk'): 1}
    criterion = ('AC-R5' if missing else 'AC-P2') if tag == 'stock_runs_out_mid_order' else CRITERIA[tag]
    return state, order_basket, competitor, criterion
