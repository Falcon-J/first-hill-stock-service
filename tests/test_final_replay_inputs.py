"""Final replay inputs cannot manufacture missing stock or split baskets."""
from pathlib import Path
import hashlib
import json

from checks.final_replay_support import load_inputs, order_payload, mismatch_reasons

ROOT = Path(__file__).resolve().parents[1]


def test_final_sources_have_40_lines_and_report_missing_stores():
    rows, groups, coverage = load_inputs(ROOT / 'docs/final-replay')
    assert len(rows) == 40
    assert sum(len(group) for group in groups.values()) == 40
    assert coverage['overlapping_rows'] == 6
    assert coverage['missing_stores'] == [
        'STB-10358', 'STB-10417', 'STB-10466', 'STB-10503',
        'STB-10529', 'STB-10588', 'STB-10611']
    recorded = json.loads((ROOT / 'docs/final-replay/summary.json').read_text())['source_sha256']
    for filename, digest in recorded.items():
        assert hashlib.sha256((ROOT / 'docs/final-replay' / filename).read_bytes()).hexdigest() == digest


def test_final_multi_line_basket_preserves_inputs_without_expected_labels():
    _, groups, _ = load_inputs(ROOT / 'docs/final-replay')
    source = groups['MO-20250310-0419']
    payload = order_payload(source)
    assert payload['store_id'] == 'STB-10611'
    assert [line['line_item_number'] for line in payload['items']] == [1, 2, 3]
    assert payload['items'][1]['drink_name'] == 'Caramel Macchiato'
    assert payload['items'][1]['add_ins'] == ['vanilla syrup', 'caramel drizzle']
    assert set(payload) == {'store_id', 'submitted_at', 'items', 'payment_method_token'}
    assert all(set(line) == {'line_item_number', 'drink_name', 'size', 'milk', 'add_ins', 'quantity'}
               for line in payload['items'])


def test_final_refusal_cannot_pass_with_wrong_code_or_side_effects():
    rows, _, _ = load_inputs(ROOT / 'docs/final-replay')
    row = next(row for row in rows if row['order_id'] == 'MO-20250310-0209')
    body = {'request_id': 'req-proof', 'error': {
        'code': 'STOCK_CHANGED', 'message': row['expected_message'],
        'missing_component': 'oat milk', 'retryable': False}}
    reasons = mismatch_reasons(row, 409, body, {'payment_rows': 1, 'outbox_rows': 0}, 'req-proof')
    assert 'Refusal code does not match scenario rule' in reasons
    assert 'Refusal/uncertainty created payment or queue entry' in reasons


def test_final_acceptance_cannot_pass_with_wrong_store_or_request_id():
    rows, _, _ = load_inputs(ROOT / 'docs/final-replay')
    row = rows[0]
    body = {'status': 'accepted', 'store_id': 'wrong-store', 'order_id': 'opaque',
            'queue_spot': 1, 'request_id': 'wrong-request'}
    reasons = mismatch_reasons(row, 201, body, {'payment_rows': 1, 'outbox_rows': 1}, 'req-proof')
    assert 'Accepted store does not match input' in reasons
    assert 'Response request ID does not match input' in reasons


def test_final_comparison_accepts_complete_matching_refusal_and_acceptance():
    rows, _, _ = load_inputs(ROOT / 'docs/final-replay')
    row = next(row for row in rows if row['order_id'] == 'MO-20250310-0209')
    detail = {'code': 'BASE_OUT_OF_STOCK', 'line_item_number': 1, 'missing_component': 'oat milk'}
    body = {'request_id': 'req-proof', 'error': {
        **detail, 'message': row['expected_message'], 'details': [detail], 'retryable': False}}
    assert mismatch_reasons(row, 409, body, {'payment_rows': 0, 'outbox_rows': 0}, 'req-proof') == []
    accepted = {'status': 'accepted', 'store_id': rows[0]['store_id'], 'order_id': 'opaque',
                'queue_spot': 3, 'request_id': 'req-proof'}
    assert mismatch_reasons(rows[0], 201, accepted, {'payment_rows': 1, 'outbox_rows': 1}, 'req-proof') == []


def test_final_comparison_rejects_wrong_selected_line_and_incomplete_envelope():
    rows, _, _ = load_inputs(ROOT / 'docs/final-replay')
    row = next(row for row in rows if row['order_id'] == 'MO-20250310-0209')
    body = {'request_id': 'req-proof', 'error': {
        'code': 'BASE_OUT_OF_STOCK', 'line_item_number': 2,
        'missing_component': 'oat milk', 'message': row['expected_message'],
        'details': [], 'retryable': False}}
    reasons = mismatch_reasons(row, 409, body, {'payment_rows': 0, 'outbox_rows': 0}, 'req-proof')
    assert 'Selected refusal line does not match source' in reasons
    assert 'Refusal details do not identify source failure' in reasons
    del body['error']['retryable']
    assert 'Response does not validate against frozen contract' in mismatch_reasons(
        row, 409, body, {'payment_rows': 0, 'outbox_rows': 0}, 'req-proof')
