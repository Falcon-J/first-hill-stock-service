"""Query the local Compose gateway; save evidence without credentials."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:18080')
parser.add_argument('--output', default=str(ROOT / 'specs/003-build-services/evidence/gateway-oat-refusal.json'))
args = parser.parse_args()
environment = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if line and not line.startswith('#'))
request_id = 'demo-firsthill-' + str(uuid4())
basket = {'store_id': 'SB-10482', 'items': [{'line_item_number': 1,
          'drink_name': 'Caffè Latte', 'size': 'Grande', 'milk': 'Oatmilk',
          'add_ins': [], 'quantity': 1}], 'payment_method_token': 'development-demo-no-real-payment'}
response = httpx.post(args.url + '/v1/orders', json=basket,
    headers={'Authorization': 'Bearer ' + environment['GATEWAY_CUSTOMER_TOKEN'],
             'Idempotency-Key': request_id, 'X-Request-ID': request_id}, timeout=5)
body = response.json()
assert response.status_code == 409, f'Expected a real stock refusal, got {response.status_code}: {body}'
assert body['error']['code'] == 'BASE_OUT_OF_STOCK'
assert body['error']['line_item_number'] == 1
assert body['error']['missing_component'] == 'Oatmilk'
assert body['error']['retryable'] is False
evidence = {'observed_at': datetime.now(timezone.utc).isoformat(),
            'source': 'Live HTTP request through three Docker Compose containers using the historical snapshot',
            'request': {'method': 'POST', 'path': '/v1/orders', 'request_id': request_id,
                        'idempotency_key': request_id, 'body': basket},
            'response': {'status': response.status_code, 'body': body},
            'payment_mode': 'Explicit development adapter, no real charges'}
target = Path(args.output)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps(evidence['response'], indent=2, ensure_ascii=False))
