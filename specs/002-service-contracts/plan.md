# Service boundary and contract plan

Status: DRAFT FOR OWNER REVIEW. Source: Service Boundary Review: Asks from the
Owning Teams, 7 March 2025, read in the Zero task resources on 2026-11-14.
This PR freezes proposed boundaries and adds executable contract tests. It does
not implement reservations, ordering or the gateway. Red provider tests are
intentional until those services exist; collection errors/skips are not accepted.

## Technical context and constitution check

Python 3.12 and FastAPI, one container and private persistence boundary per
service. HTTP/JSON uses OpenAPI 3.1.1 and pytest provider contract tests. No shared
database, no credentials in code, tests before implementation, no merge until
contract-tests passes. Existing read-only app.py and tests/test_stock.py remain
unchanged. Design gates pass; the implementation/merge gate intentionally remains
closed while provider assertions are red. No unresolved design clarifications.
Spec Kit setup-plan.ps1 -Json was executed for this feature; no extension hooks
are registered. Research, data model, quickstart and criterion mapping accompany
the plan. Canonical contracts live in repository-root contracts/.

## Ownership and dependency direction

| Service | Owns | Calls | MUST NOT own or do |
|---|---|---|---|
| Store stock | quantity_on_hand, reserved_quantity, store_open, catalogue/recipe resolution, availability decisions, reservations and allocations | Its own data stores/feed adapters | Give DB credentials or replicas to callers |
| Order | Basket validation, durable order attempts, idempotency, payment orchestration, queue outbox | Stock API and payment adapter | Read stock tables, cache counts/open status as truth, calculate fulfilability from raw counts |
| Gateway | Public /v1 routing, authentication, correlation, deadlines, response translation | Order API | Decide acceptance, resolve recipes, reserve stock, copy stock/order business logic |

Only stock answers whether a store can make a line. Both availability and hold
requests take the original basket; callers do not submit computed ingredient
requirements. Stock resolves trusted recipes and explicit store aliases itself.
Store IDs remain strings. A confirmed alias SB-10482 -> 10482 is inventory-owned;
unknown stores/items return 404/422, never a guessed match or fabricated zero.
last_updated_at is diagnostic provenance, never a freshness guarantee.

For the precise menu-to-checkout race code, stock may issue an opaque availability
token bound to the canonical store and basket for 120 seconds. The gateway/order
pass it through without interpreting it. Inventory verifies it and still checks
current stock: an earlier available decision followed by a losing hold returns
STOCK_CHANGED. Without that evidence, a component already at zero uses its normal
base/add-in refusal code. The token is not a hold or an authoritative cached
stock copy. It cannot extend a hold/deadline or authorize payment.

## Decisions from the review

### Full-basket reservation and final check

Choose a single atomic basket hold, not separate per-ingredient calls. Stock
checks current store_open and aggregate recipe demand while creating the hold.
It returns all holds or none; a losing race leaves syrup reserved 2 and espresso
reserved 4 in the synthetic AC-R5 fixture and never alters the winner's oat hold.
No call to payment is permitted until stock confirms the reservation.

Holds expire automatically after 120 seconds on inventory's clock; now >=
expires_at is expired. A background sweep and on-access expiry release reserved
units once. No caller-triggered renewal is supported. Every hold becomes
confirmed, released or expired. Confirm and release are idempotent terminal
transitions; retries cannot double-reserve, consume or restore quantities.

**POS/feed race:** POS and stock feeds can change quantity_on_hand without calling
the order API. Therefore confirmation MUST recheck current open state and
physical stock under the stock owner's transaction/locking boundary, including
all outstanding reservations. It MUST NOT trust the earlier read, hold creation
time or timestamp. If the basket is no longer fulfilable, confirmation releases
this hold atomically and returns 409 STOCK_CHANGED or STORE_CLOSED before
payment. A valid hold does not immunize an order against a later POS shortage.

Successful confirmation atomically changes reserved -> confirmed allocation,
subtracts this basket from on-hand and reserved totals once, and protects that
allocation from later feed overwrites. Payment then begins. A confirmed allocation
does not expire while payment is uncertain. On a terminal payment decline or
pre-capture cancellation, order asks stock to release/restore the allocation
once. After capture it cannot be released as an unpaid cancellation. Inventory
owns allocation accounting; no other service can alter it. Feed/POS adapters
must participate in that accounting at the inventory boundary.

### Retry and timeout rules

The order service sends an authenticated HTTP request to stock, for example:

```http
POST /v1/reservations HTTP/1.1
Host: stock
Authorization: Bearer <runtime-service-credential>
Idempotency-Key: order-attempt-0024
X-Request-ID: req-race-1
X-Request-Deadline: 2025-03-07T14:31:03Z
Content-Type: application/json

{"order_id":"order-attempt-0024","basket":{"store_id":"SB-10482","items":[{"line_item_number":1,"drink_name":"Iced Brown Sugar Oatmilk Shaken Espresso","size":"Grande","milk":"Oatmilk","add_ins":["Brown Sugar Syrup"],"quantity":1}]}}
```

201 returns a full-basket hold; then HTTP POST
`/v1/reservations/{reservation_id}/confirm` rechecks and converts it before
payment. 409 preserves the exact business refusal and sends no payment request.
404/422 preserve unknown-store/invalid-input errors. 401/403, malformed evidence
or stock 5xx fail closed as 503 STOCK_CHECK_UNAVAILABLE at the order boundary,
with no payment. A timeout uses GET `/v1/reservations/by-key/{idempotency_key}`
under the same remaining deadline; never assume the timed-out POST did nothing.

An authenticated owner plus Idempotency-Key and canonical basket identify an
attempt. Stock records success/refusal with the key atomically with any mutation.
Same payload/key replays the original outcome with no mutation; different
payload/key gives 409 IDEMPOTENCY_CONFLICT. Order uses its durable order ID as
the stock key. Confirm/release reuse stable transition keys. Keep order and
stock key tombstones at least 24 hours; replay after expiry cannot create a new
attempt under the old key. A fresh purchase requires a fresh key.

After a reserve timeout, query stock by the original key; do not reserve again
under a new key. A late hold expires on its own if reconciliation cannot release
it. Before payment, an unconfirmed check may give 503 STOCK_CHECK_UNAVAILABLE
with retryable=true; retrying the same order key is safe. An unknown confirmation
outcome is reconciled by GET status with no payment until confirmed.
The immediate response to either pre-payment reserve/confirm timeout is exactly
503 STOCK_CHECK_UNAVAILABLE, not a business stock refusal. Same-key retries
remain mandatory even when confirmation may have succeeded.

Payment uses a stable provider idempotency key. Unknown payment/capture results
give 202 pending and durable reconciliation; retain the confirmed allocation,
never return an ingredient-unavailable refusal after capture and never blindly
recapture. A successful capture is accepted durably and queued once via an outbox.
Queue delay cannot turn a captured order into a stock refusal. The gateway only
passes through the order service's decision.

### Error compatibility and multiple failures

The owning-team envelope supersedes the earlier draft's flat refusal JSON:

```json
{"error":{"code":"STOCK_CHANGED","message":"Line 1, Grande Iced Brown Sugar Oatmilk Shaken Espresso: Oatmilk is unavailable at this store right now.","line_item_number":1,"missing_component":"Oatmilk","details":[{"code":"STOCK_CHANGED","line_item_number":1,"missing_component":"Oatmilk"}],"retryable":false},"request_id":"req-race-1"}
```

Preserve error.code, error.message and request_id; add fields without renaming
those keys. Legacy apps still display error.message. Product owns message copy;
schemas require a nonempty string, not an enum of marketing text. Source CSV
messages remain exact test fixtures, not text hard-coded into every service.

Choose an additive details array for multiple failures. The primary reason is
store-wide closure first; otherwise lowest line number then lexical component
ID. Details use that same deterministic order. Top-level error line/component
identify the primary failure; whole-store closure uses null line and
missing_component=store_closed. Never silently substitute/drop items or accept
a partial basket. Business refusals use 409, unknown store 404, invalid/unknown
item 422 and payment decline 402; never 502/503/504 for sold-out/store-closed
business decisions. Infrastructure failures remain distinguishable.

### Deadline budget (one end-to-end 3,000 ms budget)

| Work | Maximum allocation |
|---|---:|
| Gateway admission/routing | 200 ms |
| Order validation/idempotency | 200 ms |
| Stock reserve, including any retry | 600 ms |
| Stock confirm, including any retry | 400 ms |
| Payment response | 1,000 ms |
| Response forwarding | 200 ms |
| Shared scheduling/serialization margin | 400 ms |
| Total | 3,000 ms |

Gateway sets an absolute X-Request-Deadline and request ID; it overwrites any
client deadline and propagates the remaining budget. All internal timeouts are
bounded by both their allocation and the remaining deadline. No retries reset
the budget. The app's 8-second timeout is not extra service time. At deadline,
return a safe pre-payment infrastructure failure or 202 pending for a durable
attempt with uncertain payment, never a false stock refusal after charging.
If the gateway itself loses the upstream response, it cannot infer the order's
state or invent an order ID. It returns 504 DEADLINE_EXCEEDED with retryable=true
and no missing ingredient. The client replays the original key; the order service
then returns its durable result. Malformed upstream responses use 502
UPSTREAM_UNAVAILABLE with the same retry discipline. These are infrastructure
outcomes, never sold-out refusals. The order service itself can return 202 pending
when it knows its durable order ID and payment remains uncertain.

## Deliverables and verification

1. contracts/stock-service.openapi.yaml: availability plus reserve/status/confirm/
   release, lifecycle, idempotency, current-stock confirmation and errors.
2. contracts/order-service.openapi.yaml: POST/GET /v1/orders, durable attempt
   outcomes, hold-before-payment and failure/reconciliation requirements.
3. contracts/gateway.openapi.yaml: public /v1 orders; preserve the order decision,
   error envelope, identity and 3-second budget. No direct stock mutation route.
4. pytest static checks validate OpenAPI, schemas, examples, matching boundaries
   and all five sample refusal tags. Provider tests exercise in-process ASGI
   apps with controlled dependencies. No external service, no skip/xfail, and no
   fake provider that returns the expected answers to make the draft green.
5. GitHub Actions job/check name exactly contract-tests, on push and pull_request,
   Python 3.12. It runs the full contract suite, uploads JUnit even on failures,
   and retains a failing conclusion until the missing provider behavior exists.

The actual repository's default/base branch is codex/stock-service, not the
review notes' recorded main. This draft PR targets that existing branch. The
actual base branch is now protected with required context contract-tests, strict
up-to-date checks and admin enforcement. GitHub's API confirmed these settings.
Failing/missing contract-tests blocks merging; draft status does not waive it.

## Implementation order after contract approval

- Stock provider: atomic owner-only state, idempotent bounded lifecycle and POS
  confirmation; prove race/rollback/expiry before implementing order orchestration.
- Order provider: dependency-injected stock/payment adapters and event-order tests;
  prove no payment on failed/uncertain stock and no duplicate payment/queue entry.
- Gateway: dependency-injected order adapter, preserve exact refusals and deadline;
  prove no independent acceptance logic. Build one container per service.
- Run all contract tests and existing stock tests; only then request merge.

## Provider test seams (not public endpoints)

Provider assertions use FastAPI TestClient in memory, not live feeds or an
expected-answer fake server. Implement these factories in the build stage:

- `services.stock.app.create_app(initial_state, clock, authenticate)`;
  its provider-owned `app.state.inventory` exposes `snapshot(store_id)` and
  `apply_feed(store_id, changes)` for controlled tests only. initial_state uses
  stores/components, synthetic recipes and optional seeded reservations. These
  test seams do not grant order/gateway runtime DB access.
- `services.order.app.create_app(stock_client, payment_client, queue, clock,
  authenticate)`; clients are synchronous HTTP interfaces with post/get methods
  and request hooks. Payment fixture endpoints are /authorize, /capture and
  /void. Queue exposes enqueue(order_id), returning an integer queue spot.
- `services.gateway.app.create_app(order_client, clock, authenticate)`.

clock() returns an aware datetime; authenticate(token) is a test-injected verifier.
Runtime deployments must use configured service credentials/customer auth, not
test tokens. Test transports stand in only for upstream dependencies; the target
provider must be the real app. Missing factories cause explicit failed assertions
inside tests. Legacy stock app is exercised until its factory exists; its 404
for reservation routes is an expected red contract result, not an implementation.

Reference: OpenAPI 3.1.1 specification at
https://spec.openapis.org/oas/v3.1.1.html and GitHub required-check semantics at
https://docs.github.com/en/pull-requests/reference/status-checks .
