"""The holdout oracle is exactly outcome and missing component, not display copy."""
from checks.final_replay_support import mismatch_reasons


def test_holdout_match_ignores_message_line_and_code_when_two_source_fields_match():
    row = {'expected_outcome': 'refused_unavailable', 'expected_missing_component': 'oat milk',
           'expected_message': 'Different source display text', 'scenario_tag': 'base_out',
           'line_item_number': '1', 'store_id': 'STB-10342'}
    body = {'error': {'code': 'STOCK_CHANGED', 'missing_component': 'oat milk',
                      'message': 'Actual v1 unavailable message', 'line_item_number': 2}}
    assert mismatch_reasons(row, 409, body) == []


def test_missing_store_error_is_not_an_unavailable_drink_match():
    row = {'expected_outcome': 'refused_unavailable', 'expected_missing_component': 'oat milk'}
    body = {'error': {'code': 'STORE_NOT_FOUND', 'missing_component': None}}
    assert mismatch_reasons(row, 404, body) == [
        'Outcome does not match source', 'Missing component does not match source']


def test_correct_outcome_with_wrong_component_still_fails():
    row = {'expected_outcome': 'refused_unavailable', 'expected_missing_component': 'oat milk'}
    body = {'error': {'code': 'BASE_OUT_OF_STOCK', 'missing_component': 'espresso'}}
    assert mismatch_reasons(row, 409, body) == ['Missing component does not match source']


def test_closed_store_blank_component_does_not_compare_per_line_messages():
    body = {'error': {'code': 'STORE_CLOSED', 'missing_component': 'store_closed',
                      'message': 'The existing v1 store-level message'}}
    for message in ['Caffè Latte (line 1) unavailable', 'Cold Brew (line 2) unavailable']:
        row = {'expected_outcome': 'refused_unavailable', 'expected_missing_component': '',
               'expected_message': message}
        assert mismatch_reasons(row, 409, body) == []
