"""All source spellings resolve demo demand without using expected labels."""
from pathlib import Path
import pytest
from checks.final_replay_support import load_inputs, order_payload
from services.stock.catalogue import demo_recipe

ROOT = Path(__file__).resolve().parents[1]
ROWS, GROUPS, _ = load_inputs(ROOT / 'docs/final-replay')

@pytest.mark.parametrize('row', ROWS, ids=lambda r: r['order_id'] + '/' + r['line_item_number'])
def test_every_final_line_has_a_recipe(row):
    line = next(x for x in order_payload(GROUPS[row['order_id']])['items']
                if x['line_item_number'] == int(row['line_item_number']))
    demand = demo_recipe(line)
    assert demand and all(type(v) is int and v > 0 for v in demand.values())

@pytest.mark.parametrize('drink,required', [
    ('Caramel Macchiato', {'espresso_signature', 'vanilla_syrup', 'caramel_drizzle'}),
    ('Iced Caramel Macchiato', {'espresso_signature', 'vanilla_syrup', 'caramel_drizzle'}),
    ('Caffè Mocha', {'espresso_signature', 'mocha_sauce'}),
    ('White Chocolate Mocha', {'espresso_signature', 'white_chocolate_mocha_sauce'}),
    ('Iced Chai Tea Latte', {'chai_concentrate'}),
    ('Iced Matcha Tea Latte', {'matcha_powder'}),
])
def test_recipe_required_components_cannot_be_removed_with_empty_add_ins(drink, required):
    demand = demo_recipe({'drink_name': drink, 'size': 'Grande', 'milk': '2%', 'add_ins': []})
    assert set(demand) == required | {'two_pct_milk'}
