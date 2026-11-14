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
    'cold_brew': ('cold brew', 'drink_base'),
    'chai_concentrate': ('chai concentrate', 'drink_base'),
    'strawberry_acai_base': ('strawberry açaí base', 'drink_base'),
    'coconut_milk': ('coconut milk', 'drink_base'),
    'whole_milk': ('whole milk', 'drink_base'),
    'soy_milk': ('soy milk', 'drink_base'),
    'classic_syrup': ('classic syrup', 'add_in'),
    'mocha_sauce': ('mocha sauce', 'add_in'),
    'white_chocolate_mocha_sauce': ('white chocolate mocha sauce', 'add_in'),
    'chocolate_cream_cold_foam': ('chocolate cream cold foam', 'add_in'),
}
MILKS = {'Oatmilk': 'oat_milk', 'Almondmilk': 'almond_milk', '2% Milk': 'two_pct_milk',
         'coconut milk': 'coconut_milk', 'whole milk': 'whole_milk', 'soy milk': 'soy_milk'}
ADD_INS = {name: component for component, (name, kind) in COMPONENTS.items() if kind == 'add_in'}
DRINKS = {
    'Caffè Latte': {'espresso_signature': 1},
    'Iced Brown Sugar Oatmilk Shaken Espresso': {'espresso_signature': 1, 'brown_sugar_syrup': 1},
    'Matcha Latte': {'matcha_powder': 1},
    'Iced Matcha Latte': {'matcha_powder': 1},
    # Same demo stock-unit convention as the existing recipes, not commercial
    # size-specific Starbucks quantities. Registration never creates inventory.
    'Cold Brew': {'cold_brew': 1},
    'Caffè Americano': {'espresso_signature': 1},
    'Chai Tea Latte': {'chai_concentrate': 1},
    'Pink Drink': {'strawberry_acai_base': 1, 'coconut_milk': 1},
    'Cappuccino': {'espresso_signature': 1},
    'Flat White': {'espresso_signature': 1},
    'Caramel Macchiato': {'espresso_signature': 1, 'vanilla_syrup': 1, 'caramel_drizzle': 1},
    'Iced Caramel Macchiato': {'espresso_signature': 1, 'vanilla_syrup': 1, 'caramel_drizzle': 1},
    'Caffè Mocha': {'espresso_signature': 1, 'mocha_sauce': 1},
    'White Chocolate Mocha': {'espresso_signature': 1, 'white_chocolate_mocha_sauce': 1},
    'Iced Chai Tea Latte': {'chai_concentrate': 1},
    'Iced Matcha Tea Latte': {'matcha_powder': 1},
}
SIZES = {'Tall', 'Grande', 'Venti'}
MILK_SPELLINGS = {**{name.casefold(): component for name, component in MILKS.items()},
                 'oat': 'oat_milk', 'almond': 'almond_milk', '2%': 'two_pct_milk',
                 'coconut': 'coconut_milk', 'whole': 'whole_milk', 'soy': 'soy_milk'}
ADD_IN_SPELLINGS = {name.casefold(): component for name, component in ADD_INS.items()}
# Explicit semantic names from the supplied stock feed, not inferred ID prefixes.
FEED_NAMES = {'espresso_signature': {'espresso'}, 'oat_milk': {'oat milk'},
              'almond_milk': {'almond milk'}, 'matcha_powder': {'matcha'}}
COMPONENT_TYPES = {'base': 'drink_base', 'milk': 'drink_base',
                   'syrup': 'add_in', 'topping': 'add_in'}


def component_type(value):
    return COMPONENT_TYPES.get(value, value)


def recipe_key(line):
    return '|'.join([line['drink_name'], line['size'], line['milk'], ','.join(sorted(line['add_ins']))])


def demo_recipe(line, components=None):
    if line['drink_name'] not in DRINKS or line['size'] not in SIZES:
        raise ValueError('Unsupported drink or size')
    milk = line['milk'].casefold()
    add_ins = [add.casefold() for add in line['add_ins']]
    if len(set(add_ins)) != len(add_ins):
        raise ValueError('Duplicate add-in spellings')
    if (milk not in {*MILK_SPELLINGS, 'none'} or
            any(add not in ADD_IN_SPELLINGS for add in add_ins)):
        raise ValueError('Unsupported milk or add-in')
    result = dict(DRINKS[line['drink_name']])
    if milk != 'none':
        result[MILK_SPELLINGS[milk]] = 1
    for add in add_ins:
        result[ADD_IN_SPELLINGS[add]] = 1
    # This recipe inherently requires oat milk; a client cannot silently remove it.
    if line['drink_name'] == 'Iced Brown Sugar Oatmilk Shaken Espresso':
        result['oat_milk'] = 1
    if components is None:
        return result
    resolved = {}
    for component, units in result.items():
        if component in components:
            target = component  # An existing explicit catalogue ID remains authoritative.
        else:
            names = {COMPONENTS[component][0].casefold()} | FEED_NAMES.get(component, set())
            matches = [key for key, row in components.items()
                       if row.get('component_name', '').casefold() in names]
            if not matches:
                # Preserve demand()'s UNKNOWN_ITEM response for a known recipe
                # whose ingredient is missing. Do not fabricate a stock row.
                resolved[component] = units
                continue
            if len(matches) > 1:
                raise ValueError('Ambiguous feed component')
            target = matches[0]
            if component_type(components[target].get('component_type')) != COMPONENTS[component][1]:
                raise ValueError('Feed component category does not match recipe')
        resolved[target] = resolved.get(target, 0) + units
    return resolved


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
