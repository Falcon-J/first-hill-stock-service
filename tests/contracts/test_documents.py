"""Executable checks for the contract artifacts, not proof of provider behavior."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NAMES = ['stock-service', 'order-service', 'gateway']


def contract(name):
    import yaml
    path = ROOT / 'contracts' / f'{name}.openapi.yaml'
    assert path.exists(), f'Missing checked-in contract: {path.name}'
    return yaml.safe_load(path.read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', NAMES)
def test_valid_openapi_contract(name):
    from openapi_spec_validator import validate
    validate(contract(name))


@pytest.mark.parametrize('name', NAMES)
def test_examples_validate_and_external_schema_refs_are_absent(name):
    from jsonschema import Draft202012Validator, FormatChecker
    document = contract(name)
    encoded = json.dumps(document)
    assert '"$ref": "http' not in encoded
    schemas = document['components']['schemas']
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
        expanded = dict(schema, components=document['components'])
        for example in schema.get('examples', []):
            Draft202012Validator(expanded, format_checker=FormatChecker()).validate(example)
    for path in document['paths'].values():
        for operation in path.values():
            if not isinstance(operation, dict) or 'responses' not in operation:
                continue
            for response in operation['responses'].values():
                media = response.get('content', {}).get('application/json')
                if media:
                    expanded = dict(media['schema'], components=document['components'])
                    for example in media.get('examples', {}).values():
                        Draft202012Validator(expanded, format_checker=FormatChecker()).validate(example['value'])


def test_boundary_schemas_match_without_shared_runtime_models():
    stock, order, gateway = [contract(name) for name in NAMES]
    for schema in ['Basket', 'ErrorEnvelope']:
        assert stock['components']['schemas'][schema] == order['components']['schemas'][schema]
        assert order['components']['schemas'][schema] == gateway['components']['schemas'][schema]
    assert order['components']['schemas']['OrderResult'] == gateway['components']['schemas']['OrderResult']
    assert all(path.startswith('/v1/') for path in gateway['paths'])
    assert not any('reservation' in path or 'stock' in path for path in gateway['paths'])


@pytest.mark.parametrize('name', NAMES)
def test_legacy_error_envelope_and_machine_readable_details(name):
    schemas = contract(name)['components']['schemas']
    assert {'error', 'request_id'} <= set(schemas['ErrorEnvelope']['required'])
    assert {'code', 'message', 'line_item_number', 'missing_component', 'details', 'retryable'} <= set(schemas['Error']['required'])
    assert schemas['Error']['properties']['message']['minLength'] == 1
    assert 'enum' not in schemas['Error']['properties']['message']


@pytest.mark.parametrize('name', NAMES)
@pytest.mark.parametrize('field,value',[('code','INSUFFICIENT_QUANTITY'),('retryable',True),('missing_component',None)])
def test_mid_order_schema_rejects_wrong_variant_fields(name,field,value):
    import copy
    from jsonschema import Draft202012Validator, ValidationError
    document=contract(name)
    cases=json.loads((ROOT/'contracts/refusal-cases.json').read_text(encoding='utf-8'))
    body=copy.deepcopy(next(case['expected_body'] for case in cases if case['order_id']=='MO-250307-0024'))
    schema={'$ref':'#/components/schemas/StockChangedEnvelope','components':document['components']}
    validator=Draft202012Validator(schema)
    validator.validate(body)
    body['error'][field]=value
    with pytest.raises(ValidationError): validator.validate(body)
    for item in document['paths'].values():
        for operation in item.values():
            if isinstance(operation,dict) and '409' in operation.get('responses',{}):
                assert operation['responses']['409']['content']['application/json']['schema']=={'$ref':'#/components/schemas/BusinessRefusalEnvelope'}


def test_all_source_refusals_have_exact_compatible_contract_examples():
    source = json.loads((ROOT / 'specs/001-order-refusals/refusal-cases.json').read_text(encoding='utf-8'))
    cases = json.loads((ROOT / 'contracts/refusal-cases.json').read_text(encoding='utf-8'))
    assert len(cases) == len(source) == 21
    for original, case in zip(source, cases):
        assert case['order_id'] == original['order_id']
        assert case['expected_status'] == 409
        assert case['expected_body']['error']['code'] == original['expected_body']['code']
        assert case['expected_body']['error']['message'] == original['expected_body']['message']
        assert case['expected_body']['error']['line_item_number'] == original['expected_body']['line_item_number']
        assert case['expected_body']['error']['missing_component'] == original['expected_body']['missing_component']
        assert case['expected_body']['error']['retryable'] is False
    assert {case['rule'] for case in cases} == {'R1', 'R2', 'R3', 'R4', 'R5'}


@pytest.mark.parametrize('name', NAMES)
def test_nonretryable_business_responses_have_no_5xx_status(name):
    document = contract(name)
    for path in document['paths'].values():
        for operation in path.values():
            if not isinstance(operation, dict):
                continue
            for status, response in operation.get('responses', {}).items():
                for example in response.get('content', {}).get('application/json', {}).get('examples', {}).values():
                    error = example['value'].get('error')
                    if error and not error['retryable']:
                        assert int(status) < 500


def test_workflow_has_the_required_check_and_no_masked_failures():
    import yaml
    workflow = yaml.safe_load((ROOT / '.github/workflows/contract-tests.yml').read_text())
    events = workflow.get('on', workflow.get(True))  # YAML 1.1 treats on as boolean.
    assert set(events) == {'push', 'pull_request'}
    job = workflow['jobs']['contract-tests']
    assert job['name'] == 'contract-tests'
    assert any(step.get('with', {}).get('python-version') == '3.12' for step in job['steps'])
    assert not job.get('continue-on-error', False)
    commands = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'pytest tests/contracts' in commands
    assert '|| true' not in commands


def test_rollback_values_are_explicit_in_the_contract_fixture():
    cases = json.loads((ROOT / 'contracts/refusal-cases.json').read_text(encoding='utf-8'))
    case = next(case for case in cases if case['order_id'] == 'MO-250307-0024')
    assert case['rollback_reserved_before'] == {'brown_sugar_syrup': 2, 'espresso_signature': 4}
    assert case['rollback_reserved_after'] == case['rollback_reserved_before']


def test_network_guard_blocks_external_addresses_but_allows_local_ipc():
    import socket
    with socket.socket() as sock:
        with pytest.raises(AssertionError, match='External network'):
            sock.connect(('203.0.113.1', 80))
    left, right = socket.socketpair()
    left.close(); right.close()
