"""Source parsing only: never infer stock, aliases or recipes from expected answers."""
import csv
from collections import OrderedDict
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

CONTRACT = json.loads((Path(__file__).resolve().parents[1] /
                       'services/gateway/contract.json').read_text(encoding='utf-8'))


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as source:
        return list(csv.DictReader(source))


def load_inputs(directory):
    rows = read_csv(directory / 'orders.csv')
    stock = read_csv(directory / 'stock.csv')
    groups = OrderedDict()
    for line_number, row in enumerate(rows, 2):
        row['csv_line'] = line_number
        group = groups.setdefault(row['order_id'], [])
        if group and any(group[0][field] != row[field] for field in ('store_id', 'submitted_at')):
            raise ValueError('Inconsistent order-level fields')
        if any(item['line_item_number'] == row['line_item_number'] for item in group):
            raise ValueError('Duplicate order line')
        group.append(row)
    known = {row['store_id'] for row in stock}
    used = {row['store_id'] for row in rows}
    coverage = {'source_rows': len(rows), 'baskets': len(groups),
                'order_stores': sorted(used), 'snapshot_stores': sorted(known),
                'missing_stores': sorted(used - known),
                'overlapping_rows': sum(row['store_id'] in known for row in rows)}
    return rows, groups, coverage


def order_payload(group):
    first = group[0]
    return {'store_id': first['store_id'], 'submitted_at': first['submitted_at'],
            'payment_method_token': 'synthetic-development-payment', 'items': [
                {'line_item_number': int(row['line_item_number']), 'drink_name': row['drink_name'],
                 'size': row['size'], 'milk': row['milk'],
                 'add_ins': row['add_ins'].split(';') if row['add_ins'] else [],
                 'quantity': int(row['quantity'])}
                for row in sorted(group, key=lambda item: int(item['line_item_number']))]}


UNAVAILABLE_CODES = {'STORE_CLOSED', 'BASE_OUT_OF_STOCK', 'ADD_IN_OUT_OF_STOCK',
                     'INSUFFICIENT_QUANTITY', 'STOCK_CHANGED'}


def observed_outcome(status, body):
    if not isinstance(body, dict):
        return 'error'
    if status == 201 and body.get('status') == 'accepted':
        return 'accepted'
    error = body.get('error', {})
    if status == 409 and isinstance(error, dict) and error.get('code') in UNAVAILABLE_CODES:
        return 'refused_unavailable'
    return 'error'


def mismatch_reasons(row, status, body):
    """Compare exactly the two source oracle columns; other fields are diagnostics.

    Schema, correlation and no-charge invariants are checked by the independent
    safety guard, not by the source-row matcher.
    """
    actual = observed_outcome(status, body)
    error = body.get('error', {}) if isinstance(body, dict) else {}
    error = error if isinstance(error, dict) else {}
    component = error.get('missing_component')
    # The v1 store-closed sentinel denotes no ingredient; the final CSV is blank.
    if error.get('code') == 'STORE_CLOSED' and component == 'store_closed':
        component = None
    reasons = []
    if actual != row['expected_outcome']:
        reasons.append('Outcome does not match source')
    if component != (row['expected_missing_component'] or None):
        reasons.append('Missing component does not match source')
    return reasons


def boundary_failures(status, body, effects, request_id, store_id):
    """Independent frozen-contract and no-charge checks, not CSV match fields."""
    if not isinstance(body, dict):
        return ['Response is not a JSON object']
    accepted = observed_outcome(status, body) == 'accepted'
    error = body.get('error', {})
    error = error if isinstance(error, dict) else {}
    reasons = []
    response = CONTRACT['paths']['/v1/orders']['post']['responses'].get(str(status))
    if response is None:
        reasons.append('HTTP status is not in frozen contract')
    else:
        schema = response['content']['application/json']['schema']
        validator = Draft202012Validator({**schema, 'components': CONTRACT['components']},
                                         format_checker=FormatChecker())
        if not validator.is_valid(body):
            reasons.append('Response does not validate against frozen contract')
    if body.get('request_id') != request_id:
        reasons.append('Response request ID does not match input')
    if accepted:
        if body.get('store_id') != store_id:
            reasons.append('Accepted store does not match input')
        if not body.get('order_id') or type(body.get('queue_spot')) is not int or body['queue_spot'] < 1:
            reasons.append('Accepted response lacks valid order/queue identity')
    if status == 409 and error.get('code') in UNAVAILABLE_CODES:
        if error.get('retryable') is not False:
            reasons.append('Business refusal retryable must be false')
        expected_detail = {field: error.get(field) for field in
                           ['code', 'line_item_number', 'missing_component']}
        details = error.get('details')
        if not isinstance(details, list) or expected_detail not in details:
            reasons.append('Refusal details do not identify the returned failure')
    if not accepted and (effects['payment_rows'] or effects['outbox_rows']):
        reasons.append('Refusal/uncertainty created payment or queue entry')
    if accepted and (effects['payment_rows'] != 1 or effects['outbox_rows'] != 1):
        reasons.append('Acceptance lacks exactly one payment and queue entry')
    return reasons
