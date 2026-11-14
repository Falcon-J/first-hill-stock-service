"""Isolated Compose test operator, executed inside the stock owner's container.

Never use against production state. No production HTTP fixture endpoint exists.
"""
from datetime import datetime, timezone
import json
import os
import sys

sys.path.insert(0, '/app')
from services.stock.inventory import Inventory  # noqa: E402


def main():
    if os.environ.get('ALLOW_TEST_FIXTURES') != '1':
        raise SystemExit('Test fixture operator is disabled')
    path = os.environ['STOCK_STORAGE_PATH']
    inventory = Inventory({}, lambda: datetime.now(timezone.utc), path)
    with inventory.transaction():
        if sys.argv[1:] == ['--inspect']:
            result = {'state': inventory.data['state'], 'reservations': [
                hold['public'] for hold in inventory.data['reservations'].values()]}
        elif not sys.argv[1:]:
            state = json.load(sys.stdin)
            if not isinstance(state, dict) or not {'stores', 'recipes'} <= state.keys():
                raise ValueError('Expected synthetic stock state')
            inventory.data = {'state': state, 'reservations': {}, 'keys': {}, 'tokens': {}}
            result = {'seeded': True}
        else:
            raise SystemExit('Unsupported fixture operation')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
