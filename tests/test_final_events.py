from pathlib import Path
import copy
import hashlib
import json
import pytest
from checks.final_replay_support import load_inputs
from checks.final_events import prepare_checkout, load_events

ROOT = Path(__file__).resolve().parents[1]
_, GROUPS, _ = load_inputs(ROOT / 'docs/final-replay')
GROUP = GROUPS['MO-20250310-0371']
EVENT = {'store_id': GROUP[0]['store_id'], 'menu_at': '2025-03-10T07:16:30-07:00',
         'effective_at': '2025-03-10T07:16:35-07:00',
         'components': {'oat': {'quantity_on_hand': 0, 'last_updated_at': '2025-03-10T07:16:35-07:00'}}}

def test_menu_then_event_then_checkout_token_without_expected_labels():
    calls=[]
    def operator(action, data):
        calls.append((action, data))
        return {'status':200, 'body':{'available':True, 'availability_token':'opaque'}} if action=='menu' else {'applied':True}
    payload, evidence, failures = prepare_checkout(GROUP, {GROUP[0]['order_id']: EVENT}, operator)
    assert [x[0] for x in calls] == ['menu','feed']
    assert 'expected_outcome' not in str(calls)
    assert payload['availability_token']=='opaque'
    assert failures == [] and evidence['feed_applied'] is True
    assert 'opaque' not in str(evidence)

def test_missing_event_cannot_silently_count_as_exercised():
    calls=[]
    def operator(action, data):
        calls.append(action)
        return {'status':200,'body':{'available':True,'availability_token':'opaque'}}
    _, evidence, failures=prepare_checkout(GROUP, {}, operator)
    assert calls==['menu'] and failures
    assert evidence['feed_applied'] is False

def test_unavailable_menu_never_applies_feed():
    def operator(action, data):
        assert action=='menu'
        return {'status':404,'body':{'error':{'code':'STORE_NOT_FOUND'}}}
    _, _, failures=prepare_checkout(GROUP,{GROUP[0]['order_id']:EVENT},operator)
    assert failures

def test_ordinary_order_does_not_call_event_operator():
    payload, evidence, failures=prepare_checkout(GROUPS['MO-20250310-0209'],{},lambda *args:pytest.fail('Unexpected operator'))
    assert 'availability_token' not in payload and not failures and evidence['required'] is False

@pytest.mark.parametrize('field,value',[('store_id','wrong'),('effective_at','2025-03-10T07:16:29-07:00')])
def test_wrong_store_or_event_sequence_rejected(field,value):
    event=copy.deepcopy(EVENT);event[field]=value
    with pytest.raises(ValueError):
        prepare_checkout(GROUP,{GROUP[0]['order_id']:event},lambda *args:pytest.fail('Invalid event reached operator'))


@pytest.mark.parametrize('invalid', [None, 'hash', 'order', 'reserved'])
def test_event_manifest_binds_source_and_rejects_inventory_invention(tmp_path, invalid):
    source = ROOT / 'docs/final-replay'
    manifest = {'provenance': 'Synthetic unit-test fixture, not a supplied event',
                'source_sha256': {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                                  for name in ['orders.csv', 'stock.csv']},
                'events': {GROUP[0]['order_id']: copy.deepcopy(EVENT)}}
    if invalid == 'hash':
        manifest['source_sha256']['stock.csv'] = 'wrong'
    if invalid == 'order':
        manifest['events']['unknown'] = manifest['events'].pop(GROUP[0]['order_id'])
    if invalid == 'reserved':
        manifest['events'][GROUP[0]['order_id']]['components']['oat']['reserved_quantity'] = 0
    path = tmp_path / 'events.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    if invalid:
        with pytest.raises(ValueError):
            load_events(path, source, GROUPS)
    else:
        events, provenance = load_events(path, source, GROUPS)
        assert events == manifest['events']
        assert provenance['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('feed_result', [{'applied': False}, {}])
def test_unacknowledged_feed_never_passes_token_to_checkout(feed_result):
    def operator(action, data):
        return {'status': 200, 'body': {'available': True, 'availability_token': 'opaque'}} if action == 'menu' else feed_result
    payload, evidence, failures = prepare_checkout(GROUP, {GROUP[0]['order_id']: EVENT}, operator)
    assert failures and not evidence['feed_applied'] and 'availability_token' not in payload
