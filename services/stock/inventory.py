"""Full-basket transactions serialized by the stock owner's durable database."""
import copy
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from threading import RLock

from .catalogue import COMPONENTS, demo_recipe, recipe_key, component_type


class Refusal(Exception):
    def __init__(self, code, status=409, message=None, details=None):
        self.code, self.status = code, status
        self.message = message or 'Unable to complete this request.'
        self.details = details or []

    def envelope(self, request_id):
        first = self.details[0] if self.details else {}
        return {'error': {'code': self.code, 'message': self.message,
            'line_item_number': first.get('line_item_number'),
            'missing_component': first.get('missing_component'), 'details': self.details,
            'retryable': self.status == 503}, 'request_id': request_id}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


class Inventory:
    def __init__(self, initial_state, clock, storage_path=None):
        self.lock, self.clock = RLock(), clock
        self.connection = None
        self.data = {'state': copy.deepcopy(initial_state), 'reservations': {}, 'keys': {}, 'tokens': {}}
        if storage_path:
            path = Path(storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=1)
            self.connection.execute('PRAGMA journal_mode=WAL')
            self.connection.execute('PRAGMA synchronous=FULL')
            self.connection.execute('CREATE TABLE IF NOT EXISTS inventory_state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
            # Seeding must not overwrite a reservation committed by another worker
            # between its initial SELECT and our first write.
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                row = self.connection.execute('SELECT payload FROM inventory_state WHERE id=1').fetchone()
                if row:
                    self.data = json.loads(row[0])
                else:
                    self.save()
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def save(self):
        if self.connection:
            if not self.connection.in_transaction:
                raise RuntimeError('Inventory writes require the owner transaction')
            self.connection.execute('INSERT OR REPLACE INTO inventory_state VALUES (1, ?)', (canonical(self.data),))

    @contextmanager
    def transaction(self):
        with self.lock:
            backup = copy.deepcopy(self.data)
            try:
                if self.connection:
                    self.connection.execute('BEGIN IMMEDIATE')
                    # Reload and decoding must also be inside rollback protection:
                    # an I/O failure here must not retain the writer lock.
                    row = self.connection.execute('SELECT payload FROM inventory_state WHERE id=1').fetchone()
                    self.data = json.loads(row[0])
                    backup = copy.deepcopy(self.data)
                try:
                    self.expire()
                    yield
                except Refusal:
                    # Expiry and a failed confirmation's release commit together.
                    self.save()
                    if self.connection:
                        self.connection.commit()
                    raise
                else:
                    self.save()
                    if self.connection:
                        self.connection.commit()
            except Refusal:
                raise
            except BaseException:
                self.data = backup
                raise
            finally:
                if self.connection and self.connection.in_transaction:
                    self.connection.rollback()

    def resolve_store(self, store_id):
        store_id = self.data['state'].get('aliases', {}).get(store_id, store_id)
        if store_id not in self.data['state']['stores']:
            raise Refusal('STORE_NOT_FOUND', 404, f'Store {store_id} was not found.')
        return store_id

    def store(self, store_id):
        return self.data['state']['stores'][store_id]

    def components(self, store_id):
        return self.store(store_id)['components']

    def basket(self, basket):
        result = copy.deepcopy(basket)
        result['store_id'] = self.resolve_store(result['store_id'])
        result['items'].sort(key=lambda line: line['line_item_number'])
        for line in result['items']:
            line['add_ins'] = sorted(line['add_ins'])
        return result

    def demand(self, basket):
        demand = {}
        recipes = self.data['state'].get('recipes', {})
        for line in basket['items']:
            try:
                recipe = recipes.get(recipe_key(line))
                if recipe is None:
                    if recipes:  # Injected catalogues are authoritative, not partial guessed data.
                        raise ValueError('Unknown recipe')
                    recipe = demo_recipe(line, self.components(basket['store_id']))
            except ValueError:
                raise Refusal('INVALID_ORDER', 422, 'Provide a valid store, basket, and idempotency key.') from None
            for component, units in recipe.items():
                if type(units) is not int or units < 1 or component not in self.components(basket['store_id']):
                    raise Refusal('UNKNOWN_ITEM', 422, 'Recipe component is not in this store catalogue.')
                entry = demand.setdefault(component, {'component_id': component, 'units': 0, 'line_item_numbers': []})
                entry['units'] += units * line['quantity']
                entry['line_item_numbers'].append(line['line_item_number'])
        return sorted(demand.values(), key=lambda item: item['component_id'])

    def failures(self, basket, allocations, changed=False, confirming=False):
        store = self.store(basket['store_id'])
        if not store['store_open']:
            return [{'code': 'STORE_CLOSED', 'line_item_number': None, 'missing_component': 'store_closed'}]
        failed = []
        for allocation in allocations:
            component = allocation['component_id']
            row = store['components'][component]
            available = max(0, row['quantity_on_hand'] - row['reserved_quantity'])
            shortage = row['quantity_on_hand'] < row['reserved_quantity'] if confirming else available < allocation['units']
            if shortage:
                name, kind = COMPONENTS.get(component, (component, 'drink_base'))
                name, kind = row.get('component_name', name), component_type(row.get('component_type', kind))
                code = 'STOCK_CHANGED' if changed else ('INSUFFICIENT_QUANTITY' if available > 0 else
                    'ADD_IN_OUT_OF_STOCK' if kind == 'add_in' else 'BASE_OUT_OF_STOCK')
                failed.append((min(allocation['line_item_numbers']), component,
                    {'code': code, 'line_item_number': min(allocation['line_item_numbers']), 'missing_component': name}))
        return [entry[2] for entry in sorted(failed)]

    def refuse_failures(self, basket, failures):
        if not failures:
            return
        first = failures[0]
        if first['code'] == 'STORE_CLOSED':
            message = f"{self.store(basket['store_id']).get('store_name', basket['store_id'])} is closed right now and can't take mobile orders."
        else:
            line = next(line for line in basket['items'] if line['line_item_number'] == first['line_item_number'])
            message = f"Line {line['line_item_number']}, {line['size']} {line['drink_name']}: {first['missing_component']} is unavailable at this store right now."
        raise Refusal(first['code'], message=message, details=failures)

    def adjust(self, reservation, reserved=0, on_hand=0):
        for allocation in reservation['public']['allocations']:
            row = self.components(reservation['basket']['store_id'])[allocation['component_id']]
            row['reserved_quantity'] += reserved * allocation['units']
            row['quantity_on_hand'] += on_hand * allocation['units']

    def expire(self):
        for reservation in self.data['reservations'].values():
            public = reservation['public']
            if public['status'] == 'reserved' and self.clock() >= datetime.fromisoformat(public['expires_at']):
                self.adjust(reservation, reserved=-1)
                public['status'] = 'expired'
        self.data['tokens'] = {key: token for key, token in self.data['tokens'].items()
            if self.clock() < datetime.fromisoformat(token['expires_at'])}

    def snapshot(self, store_id):
        with self.transaction():
            return copy.deepcopy(self.components(self.resolve_store(store_id)))

    def apply_feed(self, store_id, changes):
        """Owner feed sends absolute physical counts before pinned allocations.

        Confirmed unpaid allocations are subtracted from feed values so a replayed
        snapshot cannot sell their units again. Feed producers must obey this
        accounting convention; arbitrary post-allocation counts are not accepted.
        """
        with self.transaction():
            store_id = self.resolve_store(store_id)
            store = self.store(store_id)
            if 'store_open' in changes:
                if type(changes['store_open']) is not bool:
                    raise ValueError('store_open must be boolean')
                store['store_open'] = changes['store_open']
            for component, update in changes.get('components', changes).items():
                if component == 'store_open':
                    continue
                if component not in store['components']:
                    raise ValueError('Unknown feed component')
                if set(update) - {'quantity_on_hand', 'last_updated_at'}:
                    raise ValueError('Feeds cannot overwrite owner reservation totals')
                if 'quantity_on_hand' in update:
                    value = update['quantity_on_hand']
                    if type(value) is not int or value < 0:
                        raise ValueError('Invalid physical count')
                    pinned = sum(allocation['units'] for hold in self.data['reservations'].values()
                        if hold['basket']['store_id'] == store_id and hold['public']['status'] == 'confirmed'
                        for allocation in hold['public']['allocations'] if allocation['component_id'] == component)
                    store['components'][component]['quantity_on_hand'] = max(0, value - pinned)
                if 'last_updated_at' in update:
                    store['components'][component]['last_updated_at'] = update['last_updated_at']

    def key(self, owner, key):
        return hashlib.sha256(canonical([owner, key]).encode()).hexdigest()

    def replay(self, owner, key, payload):
        record = self.data['keys'].get(self.key(owner, key))
        if record:
            if record['payload'] != canonical(payload):
                raise Refusal('IDEMPOTENCY_CONFLICT', message='This idempotency key was already used for a different order.')
            return copy.deepcopy(record['result'])

    def remember(self, owner, key, payload, result):
        self.data['keys'][self.key(owner, key)] = {'payload': canonical(payload), 'result': copy.deepcopy(result)}
        # Response serialization happens outside the lock; never leak live state.
        return copy.deepcopy(result)

    def availability(self, owner, basket):
        with self.transaction():
            submitted_store_id = basket['store_id']
            basket = self.basket(basket)
            allocations = self.demand(basket)
            failures = self.failures(basket, allocations)
            result = {'store_id': submitted_store_id, 'available': not failures,
                'checked_at': self.clock().isoformat(), 'failures': failures}
            if not failures:
                token = secrets.token_urlsafe(32)
                self.data['tokens'][token] = {'owner': owner, 'basket': canonical(basket),
                    'expires_at': (self.clock() + timedelta(seconds=120)).isoformat()}
                result['availability_token'] = token
            return result

    def reserve(self, owner, key, payload, request_id):
        with self.transaction():
            submitted_store_id = payload['basket']['store_id']
            # Canonicalize before mutation; aliases and add-in ordering identify the same basket.
            payload = copy.deepcopy(payload)
            try:
                payload['basket'] = self.basket(payload['basket'])
            except Refusal as error:
                replay = self.replay(owner, key, payload)
                return replay or self.remember(owner, key, payload, [error.status, error.envelope(request_id)])
            replay = self.replay(owner, key, payload)
            if replay:
                return replay
            basket = payload['basket']
            try:
                allocations = self.demand(basket)
                evidence = self.data['tokens'].get(payload.get('availability_token'))
                changed = bool(evidence and evidence['owner'] == owner and evidence['basket'] == canonical(basket))
                if payload.get('availability_token') and not changed:
                    raise Refusal('INVALID_ORDER', 422, 'Invalid or expired availability token for this basket.')
                self.refuse_failures(basket, self.failures(basket, allocations, changed=changed))
                now = self.clock()
                public = {'reservation_id': secrets.token_urlsafe(24), 'order_id': payload['order_id'],
                    'store_id': submitted_store_id, 'status': 'reserved', 'created_at': now.isoformat(),
                    'expires_at': (now + timedelta(seconds=120)).isoformat(), 'allocations': allocations}
                reservation = {'owner': owner, 'basket': basket, 'public': public}
                self.adjust(reservation, reserved=1)
                self.data['reservations'][public['reservation_id']] = reservation
                result = [201, public]
            except Refusal as error:
                result = [error.status, error.envelope(request_id)]
            return self.remember(owner, key, payload, result)

    def owned(self, owner, reservation_id):
        reservation = self.data['reservations'].get(reservation_id)
        if not reservation or reservation['owner'] != owner:
            raise Refusal('RESERVATION_NOT_FOUND', 404)
        return reservation

    def get(self, owner, reservation_id=None, key=None):
        with self.transaction():
            if key is not None:
                result = self.data['keys'].get(self.key(owner, key), {}).get('result')
                if not result:
                    raise Refusal('RESERVATION_NOT_FOUND', 404)
                if 'reservation_id' not in result[1]:
                    return copy.deepcopy(result)
                reservation_id = result[1]['reservation_id']
            return [200, copy.deepcopy(self.owned(owner, reservation_id)['public'])]

    def transition(self, owner, key, reservation_id, action, request_id):
        with self.transaction():
            payload = {'reservation_id': reservation_id, 'action': action}
            reservation = self.owned(owner, reservation_id)
            replay = self.replay(owner, key, payload)
            if replay:
                return replay
            public = reservation['public']
            status = public['status']
            try:
                if action == 'confirm':
                    if status == 'expired':
                        raise Refusal('RESERVATION_EXPIRED', message='Your stock reservation expired. Please try again.')
                    if status == 'released':
                        raise Refusal('INVALID_RESERVATION_STATE')
                    if status == 'reserved':
                        failures = self.failures(reservation['basket'], public['allocations'], changed=True, confirming=True)
                        if failures:
                            self.adjust(reservation, reserved=-1)
                            public['status'] = 'released'
                            self.refuse_failures(reservation['basket'], failures)
                        self.adjust(reservation, reserved=-1, on_hand=-1)
                        public['status'] = 'confirmed'
                elif action == 'release':
                    if status == 'reserved':
                        self.adjust(reservation, reserved=-1)
                        public['status'] = 'released'
                    elif status == 'confirmed':
                        self.adjust(reservation, on_hand=1)
                        public['status'] = 'released'
                result = [200, public]
            except Refusal as error:
                result = [error.status, error.envelope(request_id)]
            return self.remember(owner, key, payload, result)
