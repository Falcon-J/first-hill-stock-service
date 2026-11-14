"""Test replay operator inside the stock boundary; no fixture seeding."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import urllib.request
import urllib.error

sys.path.insert(0, '/app')
from services.stock.inventory import Inventory  # noqa: E402


def main():
    if os.environ.get('ALLOW_REPLAY_EVENTS') != '1':
        raise SystemExit('Replay event operator disabled')
    request = json.load(sys.stdin)
    action, data = request['action'], request['data']
    if action == 'menu':
        headers = {'Authorization': 'Bearer ' + os.environ['STOCK_SERVICE_TOKEN'],
                   'Content-Type': 'application/json', 'X-Request-ID': 'final-replay-menu',
                   'X-Request-Deadline': (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat()}
        req = urllib.request.Request('http://127.0.0.1:8000/v1/availability',
                                     data=json.dumps(data).encode(), headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            result = {'status': response.code, 'body': json.load(response)}
    elif action == 'feed':
        path = os.environ['STOCK_STORAGE_PATH']
        if not Path(path).is_file():
            raise ValueError('Existing stock database required')
        inventory = Inventory({}, lambda: datetime.now(timezone.utc), path)
        try:
            inventory.apply_feed(data['store_id'], {'components': data['components']})
        finally:
            inventory.connection.close()
        result = {'applied': True}
    else:
        raise ValueError('Unsupported replay operation')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
