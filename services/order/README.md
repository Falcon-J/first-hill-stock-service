# Order runtime

Build from repository root with `docker build -f services/order/Dockerfile .`.
The app is `services.order.app:app`; readiness is `GET /v1/health`.
Run with separate private `/data` volume and `ORDERS_DB=/data/orders.sqlite3`.

Required credentials are `ORDER_SERVICE_TOKEN` (gateway inbound),
`STOCK_SERVICE_TOKEN` (stock outbound), and `PAYMENT_SERVICE_TOKEN` (payment
outbound). Addresses are `STOCK_URL` and `PAYMENT_URL`. Missing configuration
fails readiness and fails order processing closed. No credential defaults exist.
The authenticated gateway supplies `X-Customer-ID` from its validated principal,
overwriting any public header; absent that header the configured customer scope
is used. Never expose this internal service directly to customers.

Set `PAYMENT_ADAPTER=development` explicitly for the local demo. This uses
order-owned SQLite simulated payment records and makes no financial requests.
Without that setting, the HTTP payment adapter calls `POST /authorize`,
`POST /capture`, and `GET /payments/by-key/{order_id}:authorize` to reconcile
uncertain outcomes. The provider must deduplicate the supplied stable keys and
return current authorized/captured/declined status plus payment_id on lookup.
The payment provider is intentionally outside the frozen three-service API.

Every attempt, phase, stock identity, result, outbox row, and local queue spot is
durable. Payment method tokens are used only in request memory; persisted
fingerprints are SHA-256 digests. Same-key POST and owner-authorized GET resume
reconciliation; neither creates another stock key. A runtime background worker
reconciles uncertain payments, retries terminal releases, and delivers captured
outbox entries every two seconds. Pre-payment stock uncertainty is reconciled
when callers retry the same key or query the order.
Stock owns expiry of unconfirmed holds; confirmed allocations remain held during
uncertain payment. Attempts/tombstones are retained without automatic deletion.

The default queue is the durable order-owned outbox with unique order_id and
monotonic queue spot. An injected external queue supports `enqueue(order_id)`
and **must deduplicate order_id**: after a process crash between external delivery
and local acknowledgement the durable outbox can redeliver the same order ID.
SQLite leases serialize workers for each attempt; stale leases expire after ten
seconds, longer than the three-second synchronous deadline.
