"""Gateway behavior around the frozen routing contract."""
import hashlib

import httpx
import pytest
from fastapi.testclient import TestClient

from services.gateway.app import create_app


HEADERS = {"Authorization": "Bearer customer", "X-Request-ID": "req-unit"}


def client_for(handler):
    upstream = httpx.Client(base_url="http://order", transport=httpx.MockTransport(handler))
    return TestClient(create_app(order_client=upstream, authenticate=lambda token: token == "customer"))


@pytest.mark.parametrize("result", [
    {"status": "accepted", "order_id": "order-a", "store_id": "SB-10482", "queue_spot": 2,
     "request_id": "original-attempt-id"},
    {"status": "pending", "order_id": "order-a", "code": "PAYMENT_PENDING",
     "message": "Waiting for payment.", "request_id": "original-attempt-id"},
])
def test_get_forwards_durable_order_result(result):
    def upstream(request):
        assert request.method == "GET" and request.url.path == "/v1/orders/order-a"
        assert request.headers["X-Request-ID"] == "req-unit"
        assert request.headers["Authorization"] == "Bearer customer"
        return httpx.Response(200, json=result)
    response = client_for(upstream).get("/v1/orders/order-a", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == result


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"status": "accepted", "order_id": "missing-fields"}),
    httpx.Response(500, json={"detail": "upstream failure"}),
    httpx.Response(200, json={"status": "pending", "order_id": "x", "request_id": "r",
                              "code": "PAYMENT_PENDING", "message": "waiting", "queue_spot": 1}),
])
def test_unusable_upstream_never_becomes_acceptance_or_stock_refusal(response):
    result = client_for(lambda request: response).get("/v1/orders/a", headers=HEADERS)
    assert result.status_code == 502
    assert result.json() == {"error": {"code": "UPSTREAM_UNAVAILABLE",
        "message": "Unable to complete this request.", "line_item_number": None,
        "missing_component": None, "details": [], "retryable": True}, "request_id": "req-unit"}


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic customer"])
def test_authentication_rejects_before_forwarding(authorization):
    def unexpected(request):
        pytest.fail("Unauthorized request reached upstream")
    headers = {"X-Request-ID": "req-unit"}
    if authorization:
        headers["Authorization"] = authorization
    response = client_for(unexpected).get("/v1/orders/a", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_default_runtime_fails_closed_without_customer_credentials(monkeypatch):
    monkeypatch.delenv("GATEWAY_CUSTOMER_TOKEN", raising=False)
    response = TestClient(create_app()).get("/v1/orders/a", headers=HEADERS)
    assert response.status_code == 401


def test_only_versioned_public_routes_and_readiness():
    client = client_for(lambda request: pytest.fail("Unexpected upstream request"))
    assert client.get("/v1/health").json() == {"status": "ok"}
    for path in ("/orders", "/docs", "/openapi.json", "/v1/stock"):
        assert client.get(path).status_code == 404


@pytest.mark.parametrize("method", ["get", "post"])
def test_verified_customer_scope_overwrites_forged_public_header(method):
    observed = []
    def upstream(request):
        observed.append(request.headers.get("X-Customer-ID"))
        return httpx.Response(200 if method == "get" else 202, json={"status": "pending", "order_id": "order-a",
            "code": "PAYMENT_PENDING", "message": "Waiting.", "request_id": "req-unit"})
    client = client_for(upstream)
    headers = {**HEADERS, "X-Customer-ID": "victim-owner", "Idempotency-Key": "scope-attempt"}
    if method == "get":
        response = client.get("/v1/orders/a", headers=headers)
    else:
        response = client.post("/v1/orders", headers=headers, json={"store_id": "SB-10482",
            "items": [{"line_item_number": 1, "drink_name": "Latte", "size": "Grande",
                       "milk": "Oatmilk", "add_ins": [], "quantity": 1}],
            "payment_method_token": "test-payment"})
    assert response.status_code == (200 if method == "get" else 202)
    assert observed == [hashlib.sha256(b"customer").hexdigest()]


def test_forged_customer_scope_does_not_authorize_invalid_bearer():
    client = client_for(lambda request: pytest.fail("Forged scope reached upstream"))
    response = client.get("/v1/orders/a", headers={"Authorization": "Bearer wrong",
                          "X-Customer-ID": hashlib.sha256(b"customer").hexdigest()})
    assert response.status_code == 401
