"""Red-phase provider contracts. No skipped tests or substitute provider apps.

Real stock legacy app is exercised until services.stock.app.create_app exists.
Missing order/gateway providers fail inside test bodies, never at collection.
Dependency transports are test doubles only; the service under test is always real.
"""
import copy
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / 'contracts/refusal-cases.json').read_text(encoding='utf-8'))
TOKEN = 'contract-test-only-not-a-secret'
AUTH = {'Authorization':f'Bearer {TOKEN}'}
BASKET = {'store_id':'SB-10482','items':[{'line_item_number':1,
    'drink_name':'Iced Brown Sugar Oatmilk Shaken Espresso','size':'Grande',
    'milk':'Oatmilk','add_ins':['Brown Sugar Syrup'],'quantity':1}]}


class Clock:
    def __init__(self): self.now = datetime(2025,3,7,14,31,tzinfo=timezone.utc)
    def __call__(self): return self.now
    def advance(self, seconds): self.now += timedelta(seconds=seconds)


def headers(key='attempt-1', request_id='req-contract-1', clock=None):
    deadline=(clock or Clock())()+timedelta(seconds=3)
    return {**AUTH,'Idempotency-Key':key,'X-Request-ID':request_id,
            'X-Request-Deadline':deadline.isoformat()}


def provider(name, **kwargs):
    try:
        module = importlib.import_module(f'services.{name}.app')
    except ModuleNotFoundError as error:
        if name == 'stock' and error.name in {'services','services.stock','services.stock.app'}:
            return TestClient(importlib.import_module('app').app)
        pytest.fail(f'{name} provider is not implemented: services.{name}.app.create_app ({error})')
    factory = getattr(module, 'create_app', None)
    assert callable(factory), f'{name} provider must expose create_app for real in-process contract tests'
    return TestClient(factory(authenticate=lambda token: token == TOKEN, **kwargs))


def stock_provider(clock=None):
    # Synthetic race stock. Baseline syrup/espresso reservations come from snapshot.
    state = {'stores':{'SB-10482':{'store_open':True,'components':{
        'oat_milk':{'quantity_on_hand':1,'reserved_quantity':0},
        'brown_sugar_syrup':{'quantity_on_hand':64,'reserved_quantity':2},
        'espresso_signature':{'quantity_on_hand':142,'reserved_quantity':4}}}},
        'recipes':{'Iced Brown Sugar Oatmilk Shaken Espresso|Grande|Oatmilk|Brown Sugar Syrup':{
            'oat_milk':1,'brown_sugar_syrup':1,'espresso_signature':1}}}
    return provider('stock', initial_state=copy.deepcopy(state), clock=clock or Clock())


def reserve(client, key, order_id):
    return client.post('/v1/reservations',headers=headers(key),json={'order_id':order_id,'basket':BASKET})


def assert_held(response):
    assert response.status_code == 201, f'Reservation contract requires 201; current provider returned {response.status_code}: {response.text}'
    body = response.json()
    assert body['status'] == 'reserved'
    assert body['reservation_id']
    assert datetime.fromisoformat(body['expires_at'].replace('Z','+00:00')) - datetime.fromisoformat(body['created_at'].replace('Z','+00:00')) == timedelta(seconds=120)
    return body


def assert_stock_changed_variant(body,service='stock-service'):
    import yaml
    from jsonschema import Draft202012Validator
    document=yaml.safe_load((ROOT/'contracts'/f'{service}.openapi.yaml').read_text(encoding='utf-8'))
    Draft202012Validator({'$ref':'#/components/schemas/StockChangedEnvelope',
        'components':document['components']}).validate(body)


def test_stock_atomic_race_and_ownership_safe_rollback():
    client = stock_provider()
    start = Barrier(2)
    def attempt(number):
        start.wait()
        return reserve(client,f'race-{number}',f'order-{number}')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,[1,2]))
    assert sorted(response.status_code for response in results) == [201,409]
    winner=assert_held(next(response for response in results if response.status_code==201))
    loser=next(response for response in results if response.status_code==409).json()
    assert loser['error']['missing_component']=='Oatmilk'
    assert loser['error']['line_item_number']==1
    # Provider-owned inspection seam, not another service reading its database.
    snapshot=client.app.state.inventory.snapshot('SB-10482')
    assert snapshot['brown_sugar_syrup']['reserved_quantity']==3  # 2 baseline + winner's 1
    assert snapshot['espresso_signature']['reserved_quantity']==5  # 4 baseline + winner's 1
    assert snapshot['oat_milk']['reserved_quantity']==1
    held=client.get(f"/v1/reservations/{winner['reservation_id']}",headers=headers()).json()
    assert held==winner
    # Releasing only the winner restores the baselines; loser added nothing.
    released=client.post(f"/v1/reservations/{winner['reservation_id']}/release",headers=headers('release-winner'))
    assert released.status_code==200
    snapshot=client.app.state.inventory.snapshot('SB-10482')
    assert snapshot['brown_sugar_syrup']['reserved_quantity']==2
    assert snapshot['espresso_signature']['reserved_quantity']==4
    assert snapshot['oat_milk']['reserved_quantity']==0


def test_stock_replay_never_double_reserves_and_payload_change_conflicts():
    client=stock_provider()
    first=assert_held(reserve(client,'same-key','order-1'))
    assert reserve(client,'same-key','order-1').json()==first
    changed=copy.deepcopy(BASKET)
    changed['items'][0]['quantity']=2
    response=client.post('/v1/reservations',headers=headers('same-key'),json={'order_id':'order-1','basket':changed})
    assert response.status_code==409
    assert response.json()['error']['code']=='IDEMPOTENCY_CONFLICT'
    assert client.app.state.inventory.snapshot('SB-10482')['oat_milk']['reserved_quantity']==1


def test_stock_expires_at_exact_boundary_and_release_is_idempotent():
    clock=Clock(); client=stock_provider(clock)
    held=assert_held(reserve(client,'expiry','order-expiry'))
    clock.advance(120)
    result=client.get(f"/v1/reservations/{held['reservation_id']}",headers=headers(clock=clock))
    assert result.status_code==200 and result.json()['status']=='expired'
    for _ in range(2):
        released=client.post(f"/v1/reservations/{held['reservation_id']}/release",headers=headers('expiry-release',clock=clock))
        assert released.status_code==200
    assert client.app.state.inventory.snapshot('SB-10482')['oat_milk']['reserved_quantity']==0
    confirmed=client.post(f"/v1/reservations/{held['reservation_id']}/confirm",headers=headers('expiry-confirm',clock=clock))
    assert confirmed.status_code==409
    assert confirmed.json()['error']['code']=='RESERVATION_EXPIRED'


@pytest.mark.parametrize('change', ['pos_stock_loss','store_closed'])
def test_stock_confirm_rechecks_external_changes(change):
    client=stock_provider()
    held=assert_held(reserve(client,'pos','order-pos'))
    # Simulates the inventory owner's feed/POS adapter; no order-service mutation.
    client.app.state.inventory.apply_feed('SB-10482',
        {'oat_milk':{'quantity_on_hand':0}} if change=='pos_stock_loss' else {'store_open':False})
    result=client.post(f"/v1/reservations/{held['reservation_id']}/confirm",headers=headers('confirm-pos'))
    assert result.status_code==409
    assert result.json()['error']['code']==('STOCK_CHANGED' if change=='pos_stock_loss' else 'STORE_CLOSED')
    assert client.app.state.inventory.snapshot('SB-10482')['oat_milk']['reserved_quantity']==0


def test_stock_confirm_consumes_once_and_release_restores_once():
    client=stock_provider()
    held=assert_held(reserve(client,'confirm','order-confirm'))
    url=f"/v1/reservations/{held['reservation_id']}/confirm"
    first=client.post(url,headers=headers('confirm-once'))
    assert first.status_code==200 and first.json()['status']=='confirmed'
    assert client.post(url,headers=headers('confirm-once')).json()==first.json()
    assert client.app.state.inventory.snapshot('SB-10482')['oat_milk']=={'quantity_on_hand':0,'reserved_quantity':0}
    release=f"/v1/reservations/{held['reservation_id']}/release"
    for _ in range(2): assert client.post(release,headers=headers('restore-once')).status_code==200
    assert client.app.state.inventory.snapshot('SB-10482')['oat_milk']=={'quantity_on_hand':1,'reserved_quantity':0}


def test_stock_unauthenticated_mutation_is_rejected():
    client=stock_provider()
    response=client.post('/v1/reservations',json={'order_id':'unauthorized','basket':BASKET})
    assert response.status_code==401


def test_stock_menu_read_is_not_a_hold_and_token_does_not_hide_checkout_loss():
    client=stock_provider()
    menu=client.post('/v1/availability',headers=headers(),json=BASKET)
    assert menu.status_code==200
    assert menu.json()['available'] is True
    token=menu.json()['availability_token']
    assert client.app.state.inventory.snapshot('SB-10482')['oat_milk']['reserved_quantity']==0
    client.app.state.inventory.apply_feed('SB-10482',{'oat_milk':{'quantity_on_hand':0}})
    response=client.post('/v1/reservations',headers=headers('menu-race'),json={
        'order_id':'menu-race-order','basket':BASKET,'availability_token':token})
    assert response.status_code==409
    assert response.json()['error']['code']=='STOCK_CHANGED'
    assert response.json()['error']['line_item_number']==1
    assert response.json()['error']['missing_component']=='Oatmilk'
    assert_stock_changed_variant(response.json())
    snapshot=client.app.state.inventory.snapshot('SB-10482')
    assert snapshot['brown_sugar_syrup']['reserved_quantity']==2
    assert snapshot['espresso_signature']['reserved_quantity']==4


def test_stock_unknown_store_is_not_guessed_or_treated_as_zero():
    client=stock_provider()
    basket=copy.deepcopy(BASKET); basket['store_id']='SB-104820'
    response=client.post('/v1/reservations',headers=headers('unknown-store'),json={'order_id':'unknown-store','basket':basket})
    assert response.status_code==404
    assert 'error' in response.json(), 'Unknown-store refusal requires the compatible error envelope, not legacy route-not-found detail'
    assert response.json()['error']['code']=='STORE_NOT_FOUND'


def dependency_clients(events, failure=None, failure_status=409, confirm_failure=False, timeout=False, confirm_timeout=False, payment_pending=False, payment_declined=False, stock_malformed=False, stock_error=None):
    identity={}
    def stock_transport(request):
        events.append(('stock',request.method,request.url.path))
        body=json.loads(request.content) if request.content else None
        if body: assert 'payment_method_token' not in json.dumps(body)
        if request.url.path=='/v1/reservations' and body:
            identity.update(order_id=body['order_id'],store_id=body['basket']['store_id'])
        if timeout or (confirm_timeout and request.url.path.endswith('/confirm')):
            raise httpx.ReadTimeout('Synthetic stock timeout')
        if stock_malformed: return httpx.Response(201,json={'not':'a reservation'})
        if stock_error: return httpx.Response(stock_error,json={'detail':'synthetic dependency failure'})
        if failure and (not confirm_failure or request.url.path.endswith('/confirm')):
            return httpx.Response(failure_status,json=failure)
        status='confirmed' if request.url.path.endswith('/confirm') else ('released' if request.url.path.endswith('/release') else 'reserved')
        return httpx.Response(201 if request.url.path=='/v1/reservations' and request.method=='POST' else 200,json={
            'reservation_id':'hold-test',**identity,'status':status,
            'created_at':'2025-03-07T14:31:00Z','expires_at':'2025-03-07T14:33:00Z',
            'allocations':[{'component_id':'oat_milk','units':1,'line_item_numbers':[1]}]})
    def payment_transport(request):
        events.append(('payment',request.method,request.url.path))
        assert request.headers.get('Idempotency-Key')
        if payment_pending: raise httpx.ReadTimeout('Synthetic uncertain payment')
        if payment_declined: return httpx.Response(402,json={'status':'declined','payment_id':'payment-test'})
        return httpx.Response(200,json={'status':'captured' if request.url.path.endswith('/capture') else 'authorized','payment_id':'payment-test'})
    return (httpx.Client(transport=httpx.MockTransport(stock_transport),base_url='http://stock'),
            httpx.Client(transport=httpx.MockTransport(payment_transport),base_url='http://payment'))


class Queue:
    def __init__(self,events): self.events=events
    def enqueue(self,order_id): self.events.append(('queue','enqueue',order_id)); return 1


def order_provider(events, **options):
    stock,payment=dependency_clients(events,**options)
    return provider('order',stock_client=stock,payment_client=payment,queue=Queue(events),clock=Clock())


@pytest.mark.parametrize('case', CASES, ids=lambda case:case['order_id'])
def test_order_refuses_each_sample_without_payment_or_queue(case):
    events=[]
    client=order_provider(events,failure=case['expected_body'],confirm_failure=case['rule']=='R5')
    request={key:value for key,value in case['input'].items() if key!='idempotency_key'}
    request['payment_method_token']='fixture-token-not-real'
    response=client.post('/v1/orders',headers=headers(case['order_id'],case['expected_body']['request_id']),json=request)
    assert response.status_code==409
    assert response.json()==case['expected_body']
    if case['rule']=='R5': assert_stock_changed_variant(response.json(),'order-service')
    assert not any(event[0] in {'payment','queue'} for event in events)
    assert response.json()['error']['retryable'] is False


@pytest.mark.parametrize('order_id,store_id,milk', [
    ('MO-250303-0002','SB-11937','2% Milk'),
    ('MO-250307-0023','SB-10482','Oatmilk')])
def test_order_confirms_before_payment_and_replays_once(order_id,store_id,milk):
    events=[]; client=order_provider(events)
    # AC-P2 source MO-250307-0023: the winning oat-milk latte at the race store.
    request={'store_id':store_id,'items':[{'line_item_number':1,'drink_name':'Caffè Latte',
        'size':'Grande','milk':milk,'add_ins':[],'quantity':1}],
        'payment_method_token':'fixture-token-not-real'}
    first=client.post('/v1/orders',headers=headers(order_id),json=request)
    assert first.status_code==201
    assert first.json()['status']=='accepted' and first.json()['queue_spot']>=1
    assert [event[2] for event in events[:4]]==['/v1/reservations','/v1/reservations/hold-test/confirm','/authorize','/capture']
    assert client.post('/v1/orders',headers=headers(order_id),json=request).json()==first.json()
    assert sum(event[2]=='/capture' for event in events)==1
    assert sum(event[0]=='queue' for event in events)==1
    before=list(events)
    changed=copy.deepcopy(request); changed['items'][0]['quantity']=2
    conflict=client.post('/v1/orders',headers=headers(order_id),json=changed)
    assert conflict.status_code==409
    assert conflict.json()['error']['code']=='IDEMPOTENCY_CONFLICT'
    assert events==before


@pytest.mark.parametrize('options',[{'timeout':True},{'confirm_timeout':True},
    {'stock_malformed':True},{'stock_error':500},{'stock_error':401}],
    ids=['reserve','confirm','malformed','stock-500','stock-auth-failure'])
def test_order_stock_timeout_never_requests_payment(options):
    events=[]; client=order_provider(events,**options)
    response=client.post('/v1/orders',headers=headers('timeout'),json={**BASKET,'payment_method_token':'fixture-token-not-real'})
    assert response.status_code==503
    assert not any(event[0] in {'payment','queue'} for event in events)
    assert response.json()=={'error':{'code':'STOCK_CHECK_UNAVAILABLE',
        'message':"We can't confirm this store's stock right now. Please try again.",
        'line_item_number':None,'missing_component':None,'details':[],
        'retryable':True},'request_id':'req-contract-1'}


def test_order_uncertain_payment_is_pending_not_stock_refusal():
    events=[]; client=order_provider(events,payment_pending=True)
    response=client.post('/v1/orders',headers=headers('payment-timeout'),json={**BASKET,'payment_method_token':'fixture-token-not-real'})
    assert response.status_code==202 and response.json()['status']=='pending'
    assert not any(event[0]=='queue' or event[2].endswith('/release') for event in events)


@pytest.mark.parametrize('code,status,message,store_id,at_confirm', [
    ('RESERVATION_EXPIRED',409,'Your stock reservation expired. Please try again.','SB-10482',True),
    ('STORE_NOT_FOUND',404,'Store SB-99999 was not found.','SB-99999',False)])
def test_order_expired_or_unknown_store_preserves_exact_refusal(code,status,message,store_id,at_confirm):
    expected={'error':{'code':code,'message':message,'line_item_number':None,
        'missing_component':None,'details':[],'retryable':False},'request_id':'req-contract-1'}
    events=[]; client=order_provider(events,failure=expected,failure_status=status,confirm_failure=at_confirm)
    response=client.post('/v1/orders',headers=headers(code),json={**BASKET,'store_id':store_id,'payment_method_token':'fixture-token-not-real'})
    assert response.status_code==status and response.json()==expected
    assert not any(event[0] in {'payment','queue'} for event in events)


@pytest.mark.parametrize('invalid', ['empty','zero','negative','fraction','missing-store','missing-key'])
def test_order_invalid_input_refuses_before_dependencies(invalid):
    events=[]; client=order_provider(events)
    request=copy.deepcopy({**BASKET,'payment_method_token':'fixture-token-not-real'})
    supplied=headers('invalid')
    if invalid=='empty': request['items']=[]
    elif invalid=='missing-store': del request['store_id']
    elif invalid=='missing-key': del supplied['Idempotency-Key']
    else: request['items'][0]['quantity']={'zero':0,'negative':-1,'fraction':1.5}[invalid]
    response=client.post('/v1/orders',headers=supplied,json=request)
    assert response.status_code==422
    assert response.json()=={'error':{'code':'INVALID_ORDER',
        'message':'Provide a valid store, basket, and idempotency key.',
        'line_item_number':None,'missing_component':None,'details':[],
        'retryable':False},'request_id':'req-contract-1'}
    assert events==[]


@pytest.mark.parametrize('field,value',[('size','Unsupported'),('drink_name','Unknown drink'),('milk','Unknown milk'),('add_ins',['Unknown add-in'])])
def test_order_unknown_catalogue_refusal_is_not_replaced(field,value):
    expected={'error':{'code':'INVALID_ORDER','message':'Provide a valid store, basket, and idempotency key.',
        'line_item_number':None,'missing_component':None,'details':[],'retryable':False},'request_id':'req-contract-1'}
    events=[]; client=order_provider(events,failure=expected,failure_status=422)
    request=copy.deepcopy({**BASKET,'payment_method_token':'fixture-token-not-real'})
    request['items'][0][field]=value
    response=client.post('/v1/orders',headers=headers('unknown-catalogue'),json=request)
    assert response.status_code==422 and response.json()==expected
    assert not any(event[0] in {'payment','queue'} for event in events)


def test_order_terminal_payment_decline_restores_allocation_once():
    events=[]; client=order_provider(events,payment_declined=True)
    request={**BASKET,'payment_method_token':'fixture-token-not-real'}
    first=client.post('/v1/orders',headers=headers('declined'),json=request)
    assert first.status_code==402 and first.json()['error']['code']=='PAYMENT_DECLINED'
    assert not any(event[0]=='queue' for event in events)
    assert sum(event[2].endswith('/release') for event in events)==1
    assert client.post('/v1/orders',headers=headers('declined'),json=request).json()==first.json()
    assert sum(event[2].endswith('/release') for event in events)==1


@pytest.mark.parametrize('case', [case for case in CASES if case['order_id'] in {
    'MO-250303-0001','MO-250304-0007','MO-250305-0014','MO-250307-0028','MO-250307-0024'}], ids=lambda case:case['rule'])
def test_gateway_preserves_refusal_and_deadline(case):
    seen=[]
    def upstream(request):
        seen.append(request)
        assert request.url.path=='/v1/orders'
        assert request.headers['Idempotency-Key']==case['order_id']
        assert request.headers['X-Request-ID']==case['expected_body']['request_id']
        deadline=datetime.fromisoformat(request.headers['X-Request-Deadline'].replace('Z','+00:00'))
        assert deadline==Clock()()+timedelta(seconds=3)
        return httpx.Response(409,json=case['expected_body'])
    order=httpx.Client(transport=httpx.MockTransport(upstream),base_url='http://order')
    client=provider('gateway',order_client=order,clock=Clock())
    request={key:value for key,value in case['input'].items() if key!='idempotency_key'}
    request['payment_method_token']='fixture-token-not-real'
    supplied=headers(case['order_id'],case['expected_body']['request_id'])
    supplied['X-Request-Deadline']='2099-01-01T00:00:00Z'  # Must not extend budget.
    response=client.post('/v1/orders',headers=supplied,json=request)
    assert response.status_code==409 and response.json()==case['expected_body']
    if case['rule']=='R5': assert_stock_changed_variant(response.json(),'gateway')
    assert len(seen)==1


def test_gateway_has_no_stock_mutation_route():
    order=httpx.Client(transport=httpx.MockTransport(lambda request:pytest.fail('No upstream call permitted')),base_url='http://order')
    client=provider('gateway',order_client=order,clock=Clock())
    assert client.post('/v1/reservations',headers=headers(),json={'order_id':'forbidden','basket':BASKET}).status_code==404


def test_gateway_invalid_basket_preserves_legacy_error_envelope():
    order=httpx.Client(transport=httpx.MockTransport(lambda request:pytest.fail('Invalid input must not reach order provider')),base_url='http://order')
    client=provider('gateway',order_client=order,clock=Clock())
    response=client.post('/v1/orders',headers=headers(),json={'store_id':'SB-10482','items':[]})
    assert response.status_code==422
    body=response.json()
    assert body['request_id']=='req-contract-1'
    assert body['error']['code']=='INVALID_ORDER' and body['error']['message']


def test_gateway_unknown_upstream_timeout_is_retryable_not_a_stock_refusal():
    def timeout(request): raise httpx.ReadTimeout('Synthetic exhausted upstream deadline')
    order=httpx.Client(transport=httpx.MockTransport(timeout),base_url='http://order')
    client=provider('gateway',order_client=order,clock=Clock())
    response=client.post('/v1/orders',headers=headers('gateway-timeout'),json={**BASKET,'payment_method_token':'fixture-token-not-real'})
    assert response.status_code==504
    assert response.json()['error']['code']=='DEADLINE_EXCEEDED'
    assert response.json()['error']['retryable'] is True
    assert response.json()['error']['missing_component'] is None
