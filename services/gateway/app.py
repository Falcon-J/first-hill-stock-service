"""Public HTTP routing boundary; order remains the sole decision maker."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator, FormatChecker, ValidationError


CONTRACT = json.loads(Path(__file__).with_name("contract.json").read_text(encoding="utf-8"))


def validator(schema):
    return Draft202012Validator(
        {**schema, "components": CONTRACT["components"]}, format_checker=FormatChecker()
    )


INPUT = validator({"$ref": "#/components/schemas/OrderRequest"})


def error(status, code, request_id, message="Unable to complete this request.", retryable=False):
    return JSONResponse(status_code=status, content={
        "error": {"code": code, "message": message, "line_item_number": None,
                  "missing_component": None, "details": [], "retryable": retryable},
        "request_id": request_id,
    })


def create_app(order_client=None, clock=None, authenticate=None):
    """Inject an HTTP client/verifier for tests; runtime config fails closed."""
    now = clock or (lambda: datetime.now(timezone.utc))
    customer_token = os.environ.get("GATEWAY_CUSTOMER_TOKEN", "")
    upstream_token = os.environ.get("ORDER_SERVICE_TOKEN", "")
    verify = authenticate or (lambda token: bool(customer_token) and hmac.compare_digest(token, customer_token))
    owned_client = order_client is None
    order_url = os.environ.get("ORDER_URL", "")
    if order_client is None and order_url and upstream_token:
        order_client = httpx.Client(base_url=order_url, follow_redirects=False, trust_env=False)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owned_client and order_client is not None:
            order_client.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.get("/v1/health")
    def health():
        return {"status": "ok"}

    @app.middleware("http")
    async def admission(request: Request, call_next):
        request.state.started = time.monotonic()
        request.state.deadline = now() + timedelta(seconds=3)
        supplied = request.headers.get("X-Request-ID")
        request.state.request_id = supplied or f"req-{uuid4()}"
        if supplied is not None and not re.fullmatch(r"[!-~]+", supplied):
            request.state.request_id = f"req-{uuid4()}"
            return error(422, "INVALID_ORDER", request.state.request_id,
                         "Provide a valid store, basket, and idempotency key.")
        try:
            # httpx timeouts bound individual I/O phases; this bounds total admission
            # and forwarding time even if an upstream trickles response bytes.
            remaining = 3 - (time.monotonic() - request.state.started)
            return await asyncio.wait_for(call_next(request), timeout=max(0, remaining))
        except TimeoutError:
            return error(504, "DEADLINE_EXCEEDED", request.state.request_id,
                         "Order confirmation is pending; retry using the same idempotency key.", True)

    def authorized(request):
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return False
        try:
            if not verify(token):
                return False
            # Scope derives only from verified credentials, never a public header.
            request.state.customer_id = hashlib.sha256(token.encode("utf-8")).hexdigest()
            return True
        except Exception:
            return False

    def forward(request, method, path, body=None):
        rid = request.state.request_id
        if not authorized(request):
            return error(401, "UNAUTHORIZED", rid)
        if order_client is None:
            return error(502, "UPSTREAM_UNAVAILABLE", rid, retryable=True)
        remaining = min(
            (request.state.deadline - now()).total_seconds(),
            3 - (time.monotonic() - request.state.started),
        )
        if remaining <= 0:
            return error(504, "DEADLINE_EXCEEDED", rid,
                         "Order confirmation is pending; retry using the same idempotency key.", True)
        headers = {"X-Request-ID": rid,
                   "X-Customer-ID": request.state.customer_id,
                   "X-Request-Deadline": request.state.deadline.isoformat(),
                   "Authorization": f"Bearer {upstream_token}" if owned_client else request.headers["Authorization"]}
        if "Idempotency-Key" in request.headers:
            headers["Idempotency-Key"] = request.headers["Idempotency-Key"]
        try:
            kwargs = {"headers": headers, "timeout": remaining}
            if method == "post":
                kwargs["json"] = body
            response = getattr(order_client, method)(path, **kwargs)
            if now() >= request.state.deadline or time.monotonic() - request.state.started >= 3:
                raise httpx.ReadTimeout("Gateway deadline exhausted")
            result = response.json()
            operation = CONTRACT["paths"]["/v1/orders" if method == "post" else "/v1/orders/{order_id}"][method]
            schema = operation["responses"][str(response.status_code)]["content"]["application/json"]["schema"]
            validator(schema).validate(result)
        except httpx.TimeoutException:
            return error(504, "DEADLINE_EXCEEDED", rid,
                         "Order confirmation is pending; retry using the same idempotency key.", True)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return error(502, "UPSTREAM_UNAVAILABLE", rid, retryable=True)
        except ValidationError:
            return error(502, "UPSTREAM_UNAVAILABLE", rid, retryable=True)
        return JSONResponse(status_code=response.status_code, content=result)

    @app.post("/v1/orders")
    async def place(request: Request):
        rid = request.state.request_id
        if not authorized(request):
            return error(401, "UNAUTHORIZED", rid)
        try:
            body = await request.json()
            INPUT.validate(body)
            lines = [line["line_item_number"] for line in body["items"]]
            if len(lines) != len(set(lines)) or not request.headers.get("Idempotency-Key", "").strip():
                raise ValueError("Invalid structural input")
        except (ValueError, TypeError, ValidationError):
            return error(422, "INVALID_ORDER", rid,
                         "Provide a valid store, basket, and idempotency key.")
        # Synchronous HTTP executes off the event loop with a bounded timeout.
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(forward, request, "post", "/v1/orders", body)

    @app.get("/v1/orders/{order_id}")
    def retrieve(order_id: str, request: Request):
        from urllib.parse import quote
        return forward(request, "get", f"/v1/orders/{quote(order_id, safe='')}")

    return app


app = create_app()
