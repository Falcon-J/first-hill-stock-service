"""Read safe proof counters inside the order owner's isolated container only."""
import json
import os
import sqlite3
import sys
from pathlib import Path


def main():
    if os.environ.get('ALLOW_TEST_FIXTURES') != '1':
        raise SystemExit('Test inspection operator is disabled')
    key = json.load(sys.stdin)['idempotency_key']
    path = Path(os.environ['ORDERS_DB']).resolve()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute('SELECT id,status,phase FROM attempts WHERE key=?', (key,)).fetchall()
        if len(rows) != 1:
            raise ValueError('Expected exactly one isolated order attempt')
        row = rows[0]
        result = {'order_id': row['id'], 'status': row['status'], 'phase': row['phase']}
        for table, label in [('development_payments', 'payment_rows'), ('outbox', 'outbox_rows')]:
            result[label] = connection.execute(
                f'SELECT count(*) FROM {table} WHERE order_id=?', (row['id'],)).fetchone()[0]
    print(json.dumps(result))


if __name__ == '__main__':
    main()
