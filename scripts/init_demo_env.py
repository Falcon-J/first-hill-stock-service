"""Create local, untracked demo credentials without printing them."""
from pathlib import Path
import secrets

path = Path(__file__).resolve().parents[1] / '.env'
if path.exists():
    print('Existing .env retained.')
else:
    text = ''.join(f'{key}={secrets.token_urlsafe(32)}\n' for key in
                   ('STOCK_SERVICE_TOKEN', 'ORDER_SERVICE_TOKEN', 'GATEWAY_CUSTOMER_TOKEN'))
    with path.open('x', encoding='utf-8') as target:
        target.write(text)
    print('Created untracked local demo credentials in .env.')
