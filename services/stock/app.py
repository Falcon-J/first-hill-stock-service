"""Contract-first stock HTTP API. Run exactly one worker per private state file."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import os
from typing import Annotated

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .catalogue import load_snapshot
from .inventory import Inventory, Refusal


Text = Annotated[str, Field(min_length=1)]
Positive = Annotated[int, Field(strict=True, ge=1)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Line(Model):
    line_item_number: Positive
    drink_name: Text
    size: Text
    milk: Text
    add_ins: list[Text]
    quantity: Positive

    @model_validator(mode='after')
    def unique_add_ins(self):
        if len(set(self.add_ins)) != len(self.add_ins):
            raise ValueError('Duplicate add-ins')
        return self


class Basket(Model):
    store_id: Text
    items: Annotated[list[Line], Field(min_length=1)]
    submitted_at: Text | None = None

    @field_validator('submitted_at', mode='before')
    @classmethod
    def nonnull_timestamp(cls, value):
        if value is None:
            raise ValueError('submitted_at may be omitted but cannot be null')
        return value

    @model_validator(mode='after')
    def valid_lines(self):
        if len({line.line_item_number for line in self.items}) != len(self.items):
            raise ValueError('Duplicate line number')
        if self.submitted_at:
            if datetime.fromisoformat(self.submitted_at.replace('Z', '+00:00')).tzinfo is None:
                raise ValueError('Timestamp requires timezone')
        return self


class ReserveRequest(Model):
    order_id: Text
    basket: Basket
    availability_token: Text | None = None

    @field_validator('availability_token', mode='before')
    @classmethod
    def nonnull_token(cls, value):
        if value is None:
            raise ValueError('availability_token may be omitted but cannot be null')
        return value


def create_app(initial_state=None, clock=None, authenticate=None, storage_path=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    if authenticate is None:
        def authenticate(token):
            expected = os.environ.get('STOCK_SERVICE_TOKEN', '')
            return bool(expected) and hmac.compare_digest(token, expected)
    inventory = Inventory(initial_state if initial_state is not None else load_snapshot(
        os.environ.get('STOCK_SNAPSHOT_PATH')), clock, storage_path or os.environ.get('STOCK_STORAGE_PATH'))

    @asynccontextmanager
    async def lifespan(app):
        async def sweep():
            while True:
                await asyncio.sleep(1)
                with inventory.transaction():
                    pass
        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title='Stock service', version='1.0.0', lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None)
    app.state.inventory = inventory

    def invalid():
        return Refusal('INVALID_ORDER', 422, 'Provide a valid store, basket, and idempotency key.')

    @app.exception_handler(Refusal)
    async def refusal_handler(request, error):
        return JSONResponse(error.envelope(request.headers.get('X-Request-ID') or 'uncorrelated'), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        return await refusal_handler(request, invalid())

    @app.middleware('http')
    async def authenticate_request(request, call_next):
        if request.url.path == '/v1/health':
            return await call_next(request)
        if not request.url.path.startswith('/v1/'):
            return await call_next(request)
        try:
            auth = request.headers.get('Authorization', '')
            if not auth.startswith('Bearer ') or not auth[7:]:
                raise Refusal('UNAUTHORIZED', 401)
            identity = authenticate(auth[7:])
            if not identity:
                raise Refusal('UNAUTHORIZED', 401)
            request.state.owner = identity if isinstance(identity, str) else hashlib.sha256(auth[7:].encode()).hexdigest()
            if not request.headers.get('X-Request-ID'):
                raise invalid()
            try:
                deadline = datetime.fromisoformat(request.headers['X-Request-Deadline'].replace('Z', '+00:00'))
                if deadline.tzinfo is None:
                    raise ValueError('Deadline must include timezone')
            except (ValueError, KeyError):
                raise invalid() from None
            if clock() >= deadline:
                raise Refusal('STOCK_CHECK_UNAVAILABLE', 503, "We can't confirm this store's stock right now. Please try again.")
            if request.method == 'POST' and request.url.path != '/v1/availability' and not request.headers.get('Idempotency-Key'):
                raise invalid()
            return await call_next(request)
        except Refusal as error:
            return await refusal_handler(request, error)

    async def parse(request, model):
        try:
            return model.model_validate(await request.json()).model_dump(exclude_none=True)
        except (ValueError, ValidationError):
            raise invalid() from None

    def response(result):
        return JSONResponse(result[1], status_code=result[0])

    @app.get('/v1/health')
    def health():
        return {'status': 'ok', 'service': 'stock', 'persistence': 'sqlite' if inventory.connection else 'memory'}

    @app.post('/v1/availability')
    async def availability(request: Request):
        return inventory.availability(request.state.owner, await parse(request, Basket))

    @app.post('/v1/reservations')
    async def reserve(request: Request):
        return response(inventory.reserve(request.state.owner, request.headers['Idempotency-Key'],
            await parse(request, ReserveRequest), request.headers['X-Request-ID']))

    @app.get('/v1/reservations/by-key/{idempotency_key}')
    def by_key(idempotency_key: str, request: Request):
        return response(inventory.get(request.state.owner, key=idempotency_key))

    @app.get('/v1/reservations/{reservation_id}')
    def status(reservation_id: str, request: Request):
        return response(inventory.get(request.state.owner, reservation_id=reservation_id))

    @app.post('/v1/reservations/{reservation_id}/confirm')
    def confirm(reservation_id: str, request: Request):
        return response(inventory.transition(request.state.owner, request.headers['Idempotency-Key'],
            reservation_id, 'confirm', request.headers['X-Request-ID']))

    @app.post('/v1/reservations/{reservation_id}/release')
    def release(reservation_id: str, request: Request):
        return response(inventory.transition(request.state.owner, request.headers['Idempotency-Key'],
            reservation_id, 'release', request.headers['X-Request-ID']))

    return app


app = create_app()
