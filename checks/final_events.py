"""Explicit source events, independent of expected outcome/component labels."""
from datetime import datetime
import hashlib
import json
from checks.final_replay_support import order_payload


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Event timestamps require timezones')
    return result


def validate_event(event, group):
    if set(event) != {'store_id', 'menu_at', 'effective_at', 'components'}:
        raise ValueError('Unexpected event fields')
    if event['store_id'] != group[0]['store_id']:
        raise ValueError('Event store differs from order store')
    if not timestamp(event['menu_at']) < timestamp(event['effective_at']) <= timestamp(group[0]['submitted_at']):
        raise ValueError('Require menu_at < effective_at <= checkout submitted_at')
    if not isinstance(event['components'], dict) or not event['components']:
        raise ValueError('Event requires component updates')
    for component, update in event['components'].items():
        if not component or set(update) != {'quantity_on_hand', 'last_updated_at'}:
            raise ValueError('Only physical count and timestamp updates are allowed')
        if type(update['quantity_on_hand']) is not int or update['quantity_on_hand'] < 0:
            raise ValueError('Invalid physical count')
        if timestamp(update['last_updated_at']) != timestamp(event['effective_at']):
            raise ValueError('Component timestamp differs from event time')


def load_events(path, source, groups):
    if path is None:
        return {}, None
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if set(manifest) != {'provenance', 'source_sha256', 'events'} or not manifest['provenance']:
        raise ValueError('Event manifest requires provenance and source hashes')
    expected = {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                for name in ['orders.csv', 'stock.csv']}
    if manifest['source_sha256'] != expected:
        raise ValueError('Event manifest does not match input files')
    for order_id, event in manifest['events'].items():
        if order_id not in groups or not any(r['stock_runs_out_mid_order'] == 'true' for r in groups[order_id]):
            raise ValueError('Event references an unknown or non-mid-order basket')
        validate_event(event, groups[order_id])
    return manifest['events'], {'sha256': hashlib.sha256(raw).hexdigest(), 'provenance': manifest['provenance']}


def prepare_checkout(group, events, operator):
    payload = order_payload(group)
    required = any(r['stock_runs_out_mid_order'] == 'true' for r in group)
    evidence = {'required': required, 'feed_applied': False}
    failures = []
    if not required:
        return payload, evidence, failures
    event = events.get(group[0]['order_id'])
    if event is not None:
        validate_event(event, group)
    else:
        failures.append('Missing authoritative mid-order event')
    basket = {k: v for k, v in payload.items() if k != 'payment_method_token'}
    try:
        menu = operator('menu', basket)
        evidence['menu'] = {'status': menu['status'], 'body':
                            {k: v for k, v in menu['body'].items() if k != 'availability_token'}}
        token = menu['body'].get('availability_token')
        if menu['status'] != 200 or menu['body'].get('available') is not True or not isinstance(token, str) or not token:
            failures.append('Menu-time availability not established')
        elif event is not None:
            applied = operator('feed', {'store_id': event['store_id'], 'components': event['components']})
            if applied != {'applied': True}:
                failures.append('Stock owner did not acknowledge feed event')
            else:
                evidence.update(feed_applied=True, menu_at=event['menu_at'], effective_at=event['effective_at'])
                payload['availability_token'] = token
    except (RuntimeError, KeyError, TypeError, ValueError) as error:
        failures.append('Event preparation failed: ' + type(error).__name__)
    return payload, evidence, failures
