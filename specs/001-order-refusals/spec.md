# Feature Specification: Refuse unfulfillable mobile orders before payment

**Feature**: `001-order-refusals` | **Created**: 2026-11-14 | **Status**: Draft

**Brief**: The gateway takes a store ID, drinks, sizes, chosen milks, add-ins and
quantities. The order service checks authoritative hours and stock, reserves the
entire basket before payment, then either returns an accepted order with a queue
spot or an exact refusal without charging the customer.

This commit specifies behavior for future services. It does not implement the
gateway, order service, reservation API or payment flow. The existing stock API
remains read-only and unchanged.

## Clarifications

### Session 2026-11-14

The user explicitly directed the stock-hold choice and delegated answering the
remaining clarification questions. The following are concrete drafting decisions,
recorded by the current agent; they are not claimed as separate user replies.

- Q: Reserve before or after payment? A: **Stock MUST be reserved atomically for
  the full basket BEFORE any payment request, including authorization.** A read
  check alone is insufficient. This is the user's required decision.
- Q: How long does a pending hold last? A: 120 seconds from the stock service's
  authoritative clock. Expiry is inclusive: `now >= expires_at` is expired.
  No automatic renewal; payment cannot start on an expired hold.
- Q: Can a basket be partially accepted or substituted? A: No. All required
  components for all lines are held together; no milk substitution or omitted
  add-in. Demand includes recipe units multiplied by item quantity, aggregated
  across lines before comparison.
- Q: How does payment interact with hold expiry? A: Before any payment request, stock atomically converts the confirmed,
  unexpired hold into committed allocation and revalidates store-open state.
  If conversion fails, refuse without contacting payment. Only then request
  authorization and capture. Committed allocation cannot expire while payment
  is pending; terminal payment failures release it after reconciliation.
  Only successful capture leads to acceptance/queueing.
- Q: What about timeouts or retries? A: Missing/invalid stock or hours evidence
  gives the exact 503 below, no payment. Idempotency keys deduplicate holds,
  authorization, capture and queue entries. An uncertain payment result remains
  pending reconciliation; never blindly retry a charge or label it refused while
  a charge may have succeeded.
- Q: Which error wins? A: Invalid input/unknown store first; authoritative closed
  state second; otherwise lowest line number, then lexical component ID. Zero
  available uses base/add-in code; positive but insufficient uses quantity code.
  A previously adequate read followed by failed hold uses STOCK_CHANGED.
- Q: Can the weekly order labels be inferred from the March 7 stock snapshot?
  A: No. Use explicit per-order hours/stock/recipe fixtures; preserve source
  labels and expected messages. The sample contains other stores, ingredients
  and times absent from the snapshot. Do not invent historical stock as fact.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Refuse every unfulfillable order before payment (Priority: P1)

As a customer I receive a component-specific refusal before money is requested,
so I do not discover an unavailable ingredient at the counter after paying.

**Shared refusal envelope** (the complete expected body, no queue spot):

```json
{
  "status": "refused",
  "code": "BASE_OUT_OF_STOCK",
  "store_id": "SB-10482",
  "line_item_number": 1,
  "missing_component": "Oatmilk",
  "message": "Line 1, Venti Caffè Latte: Oatmilk is unavailable at this store right now."
}
```

All five business refusals return HTTP **409**. Store-closed responses use
`line_item_number: null` and `missing_component: "store_closed"`. The component
message is exactly `Line {line_item_number}, {size} {drink_name}: {component_name}
is unavailable at this store right now.` The closed-store message is exactly
`{store_name} is closed right now and can't take mobile orders.` Names are
trusted catalogue/store display names. Preserve punctuation and accents.

**Every criterion AC-R1 through AC-R5 additionally asserts:** payment-provider
request count = 0, captured amount = 0, accepted-order count = 0, queue-entry
count = 0 and retained partial-hold count = 0. Full exact JSON bodies for all
21 cases are in `refusal-cases.json`; each is a mandatory future contract test.

#### AC-R1 — R1 / store_closed

Input: `MO-250303-0001`, store `SB-20516`, line 1, Grande Pike Place Roast,
milk None, no add-ins, quantity 1. Trusted hours fixture: Bellevue Square closed.
Expected: HTTP 409, code `STORE_CLOSED`, null line, missing `store_closed`, message
`Bellevue Square is closed right now and can't take mobile orders.` Do not
call payment or create a hold. Repeat with the other three R1 source orders.

#### AC-R2 — R2 / base_out_of_stock

Input: `MO-250308-0033`, store `SB-10482`, line 1, Venti Caffè Latte, Oatmilk,
Vanilla Syrup, quantity 1. Store open; all other components sufficient; oat milk
on hand 0, reserved 0. Expected: HTTP 409, `BASE_OUT_OF_STOCK`, missing `Oatmilk`,
line 1, message `Line 1, Venti Caffè Latte: Oatmilk is unavailable at this store
right now.` Espresso at 138 available MUST NOT alter the result. Repeat all six
R2 source cases, including both Almondmilk rows.

#### AC-R3 — R3 / add_in_out_of_stock

Input: `MO-250305-0014`, store `SB-10482`, line 1, Venti Cold Brew, milk None,
Vanilla Sweet Cream Cold Foam, quantity 1. Store open, base sufficient; foam
available 0. Expected: HTTP 409, `ADD_IN_OUT_OF_STOCK`, missing `Vanilla Sweet
Cream Cold Foam`, line 1, message `Line 1, Venti Cold Brew: Vanilla Sweet Cream
Cold Foam is unavailable at this store right now.` Repeat all five R3 cases.

#### AC-R4 — R4 / insufficient_quantity

Input: `MO-250307-0028`, store `SB-11937`, line 1, Grande Iced Brown Sugar
Oatmilk Shaken Espresso, Oatmilk, Brown Sugar Syrup, quantity 4. Fixture recipe
uses 1 syrup test-unit per item; syrup on hand 3, reserved 0, demand 4; all
other components sufficient and store open. Expected: HTTP 409,
`INSUFFICIENT_QUANTITY`, missing `Brown Sugar Syrup`, line 1, message
`Line 1, Grande Iced Brown Sugar Oatmilk Shaken Espresso: Brown Sugar Syrup is
unavailable at this store right now.` Repeat `MO-250307-0030` with 3 drinks,
2 syrup units available, demand 3 and its exact message from refusal-cases.json.
Also test two lines needing 2 units each against 3 available: aggregate demand
4 MUST refuse the complete basket with the component message for the first line.
These numbers are controlled test fixtures, not asserted historical recipes.

#### AC-R5 — R5 / stock_runs_out_mid_order (refused cases only)

**Part 1 — CSV fact:** Physical CSV line 25 (header is line 1), order
`MO-250307-0024`, contains exactly:

```text
scenario_tag: stock_runs_out_mid_order
stock_runs_out_mid_order: true
expected_outcome: refused
expected_missing_component: Oatmilk
```

The CSV does not record menu-time stock, a competing order or reservation timing.

**Part 2 — Designed race and expected refusal:** This is a synthetic test
designed to match that tag, not a historical sequence recorded by the CSV.

Given store `SB-10482` is open and the menu-time stock read reports 1 available
oat-milk unit, this customer has not yet reserved it. Before this customer's
checkout hold, another order reserves that last unit. At checkout, available
oat milk is 0 (on hand 1 minus reserved 1); all other required components remain
sufficient.

**Concrete rollback fixture:** For this test only, resolve the basket to one
test-unit each of `brown_sugar_syrup` (Brown Sugar Syrup), `espresso_signature`
(Signature Espresso Roast) and `oat_milk` (Oatmilk). These are synthetic recipe
units, not quantities or reservation events recorded in the CSV. Capture the
committed reservation totals before the losing request. Exercise an internal
reservation attempt that tentatively stages syrup and espresso before finding
that the oat-milk unit is already reserved by the winner.

Seed committed reserved totals at `SB-10482` to **2 syrup units** and **4 espresso
units** before the losing request. These baselines are copied from stock
snapshot store `10482`: physical CSV line 6, `brown_sugar_syrup`, on hand 64,
reserved 2; and line 2, `espresso_signature`, on hand 142, reserved 4 (header
counted as line 1). Those existing reservations belong to other orders. The
fixture's one oat-milk unit is a synthetic override: the actual snapshot oat
row at line 3 has on hand 0 and reserved 0 and cannot itself replay this race.

| Committed reserved total | Before losing request | After refusal |
|---|---:|---:|
| Brown Sugar Syrup | 2 | 2 |
| Signature Espresso Roast | 4 | 4 |

Under the atomic full-basket rule, those syrup/espresso changes MUST remain
uncommitted and MUST NOT be exposed as successful partial holds. When oat milk
fails, discard both tentative changes. Assert that the loser owns no hold for
any of the three components, and that committed syrup and espresso reservation
totals equal their pre-attempt values. Assert that the winner still owns its
one oat-milk unit and that its reservation ID, owner and quantity are unchanged.
There is no interval in which a committed partial basket is promised to the
loser; any implementation that validates everything before staging writes MUST
produce the same unchanged committed state on this failure.

When the customer submits `MO-250307-0024`: line 1, Grande Iced Brown Sugar
Oatmilk Shaken Espresso, milk Oatmilk, add-in Brown Sugar Syrup, quantity 1,
the atomic full-basket hold MUST fail and the order service MUST return HTTP
**409** with this exact body:

```json
{
  "status": "refused",
  "code": "STOCK_CHANGED",
  "store_id": "SB-10482",
  "line_item_number": 1,
  "missing_component": "Oatmilk",
  "message": "Line 1, Grande Iced Brown Sugar Oatmilk Shaken Espresso: Oatmilk is unavailable at this store right now."
}
```

Assert zero payment-provider requests, zero captured amount, zero accepted
orders, zero queue entries and zero retained partial holds for this order.
The competing order's reservation MUST remain intact. Increment `stock_conflict`
exactly once per distinct attempt, recording order ID, store ID and missing
component without payment secrets. Repeat the other three R5 refused cases
from `refusal-cases.json`, including foam loss in `MO-250307-0026`.

### User Story 2 - A secured, fulfilable basket can complete (Priority: P1)

**AC-P1:** For `MO-250303-0002` (SB-11937, Grande Caffè Latte, 2% Milk,
quantity 1), fixture hours open and all recipe demand available. Assert confirmed
all-component hold precedes committed allocation; allocation precedes authorization;
successful capture precedes HTTP 201 `status: accepted`, an opaque order ID and
queue spot. Exactly one payment capture and queue entry are created.

**AC-P2 — Accepted winning-hold alternative:**

**CSV fact:** Order `MO-250307-0023` has `scenario_tag=stock_runs_out_mid_order`,
`stock_runs_out_mid_order=true`, `expected_outcome=accepted`, and an empty
`expected_missing_component`. Its input is store `SB-10482`, line 1, Grande
Caffè Latte, Oatmilk, no add-ins, quantity 1. The CSV does not record the order
in which reservations occurred.

**Designed test:** Given the store is open, all other required components are
sufficient and one oat-milk unit is available, this order atomically holds that
last unit before a competing order. Another customer then sees zero unreserved
oat milk. This order MUST still follow AC-P1 while its hold is valid: commit
allocation before payment, capture successfully, and return HTTP 201 with
`status: accepted`, an order ID and a queue spot. Assert exactly one capture and
one queue entry for this order. The scenario tag alone MUST NOT cause refusal.

For two simultaneous orders competing for that one unit, exactly one hold MUST
succeed; the losing order MUST return AC-R5 with no payment request or queue
entry. Assert no oversell. This winning-hold sequence is a synthetic test that
matches the accepted source outcome, not event history recorded by the CSV.

**AC-P2 ordering assertion (same race order and store):** AC-P1's complete
sequence also applies to `MO-250307-0023` at `SB-10482`, not only to
`MO-250303-0002` at `SB-11937`. In AC-P2's designed winning-hold fixture, record
events for `MO-250307-0023` and assert this strict order: confirmed full-basket
hold -> committed allocation -> payment authorization -> successful capture ->
HTTP 201 accepted response with an opaque order ID and queue spot. Before the
confirmed hold and committed allocation, payment-provider request count MUST
remain zero. Assert exactly one capture and one queue entry for this same order.
These are required future contract-test assertions, not claimed executed tests.

### User Story 3 - Failure and retry do not charge an unfulfillable order (Priority: P2)

**AC-E1 (expired hold):** Hold created at T, expires at T+120 seconds; no payment
started. At exactly T+120, return HTTP 409 with body `status: refused`, code
`RESERVATION_EXPIRED`, the submitted store ID, null line, null missing component,
message `Your stock reservation expired. Please try again.` Assert released
hold, zero payment requests, zero queue entries. If allocation conversion loses
to expiry/closure, refuse before authorization; never capture or queue.

**AC-E2 (unconfirmed check):** Valid basket, stock/hours dependency times out,
returns malformed evidence or cannot confirm the hold. Return HTTP 503 with
body `status: refused`, code `STOCK_CHECK_UNAVAILABLE`, submitted store ID,
null line, null missing component, message `We can't confirm this store's stock
right now. Please try again.` Assert zero payment requests and no queue entry.
Reconcile an uncertain hold using the same idempotency key and release it;
never create a second hold to guess whether the first one exists.

**AC-E3 (unknown store):** Input store ID `SB-99999` with otherwise valid line.
Return HTTP 404 and body `status: refused`, code `STORE_NOT_FOUND`, store ID
`SB-99999`, null line, null missing component, message `Store SB-99999 was not
found.` Assert no stock mutation/payment/queue entry. Do not report zero stock.

**AC-E4 (invalid input):** Input an empty basket or quantity 0, negative or
noninteger, unsupported size/drink/milk/add-in, missing store ID or missing
idempotency key. Return HTTP 422, body `status: refused`, code `INVALID_ORDER`,
`store_id` equal to the submitted string or null if absent, null line and
missing component, message `Provide a valid store, basket, and idempotency key.`
No stock mutation, payment request or queue entry.

**AC-E5 (idempotency):** Repeating an accepted order with the same key and
canonical basket returns its original 201 body, with exactly one hold,
authorization, capture and queue entry. Reusing the key for a different basket
returns HTTP 409 with body `status: refused`, code `IDEMPOTENCY_CONFLICT`,
submitted store ID, null line and missing component, message `This idempotency
key was already used for a different order.` It creates no additional side
effect. Unknown payment outcomes return HTTP 202 `status: pending`, order ID,
code `PAYMENT_PENDING`, message `Payment confirmation is pending.` and no queue
spot until reconciliation confirms capture. Retries MUST NOT duplicate capture.

### Edge Cases

The scenarios above cover zero stock, positive insufficient stock, competing
holds, expiry boundaries, closed/unknown stores, unconfirmed checks, invalid
input and repeated requests. Refuse the whole basket; never substitute stock.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001:** Gateway MUST validate a string `store_id`, nonempty `items`, and
  an `Idempotency-Key` header; each item MUST contain unique positive line number,
  catalogue drink/size/milk/add-ins and a positive integer quantity. Client price
  and scenario tags MUST NOT determine price or availability.
- **FR-002:** Order service MUST resolve trusted recipes into component units,
  multiply by quantity and aggregate across lines. Milk None means no chosen
  milk, not bypassing recipe-required bases/add-ins. Unsupported recipes MUST
  give AC-E4 and MUST NOT be approximated with the current snapshot catalogue.
- **FR-003:** Stock service MUST atomically check hours and available quantities
  and create a full-basket hold or no hold. Available remains max(0, on-hand minus
  reserved); equality with required quantity succeeds. Each concurrent hold MUST
  see prior reservations. API calls MUST be idempotent by order attempt.
- **FR-004:** Follow the clarification's hold -> commit allocation -> authorize
  -> capture -> accept sequence. Never release committed allocation while capture
  outcome is unknown. A terminal decline MUST release allocation, return HTTP
  402 with `status: refused`, code `PAYMENT_DECLINED`, submitted store ID, null
  line and missing component, message `Payment was declined. No order was
  accepted.`, and create no queue entry. This extra payment rule is not a sample
  refusal tag and requires a future payment contract test.
- **FR-005:** Revalidate hours when converting the hold. Closed-store conversion
  returns the AC-R1 refusal before authorization and never requests payment.
  Queue retries after a confirmed payment MUST be durable and idempotent; never
  capture a second payment because queue delivery is delayed.
- **FR-006:** Refusal bodies MUST match the specified envelopes exactly; no
  success/queue payload may be attached. Preserve source messages for sample
  cases. One failure reason is selected deterministically as clarified above.
- **FR-007:** Freeze gateway/order and order/stock OpenAPI contracts, including
  hours, hold, release and commit allocation, before writing service code. Run
  provider and consumer tests. This draft's response definitions do not claim
  those contract files or endpoints already exist.

### Key Entities and Fixture Provenance

- Gateway validates/routs; order service owns order/payment orchestration and
  queue delivery state; stock service owns counts, hours decisions and holds.
  No shared database; each uses one Python/FastAPI container.
- Key entities: basket line, resolved recipe demand, store-hours decision,
  component stock, expiring hold, committed allocation, payment result and order.
- Source: unchanged `evidence/mobile-orders-2025-03-03-to-09.csv`, 40 orders,
  21 refused, 19 accepted. All refused tags and rows are in `scenario-audit.md`.
  No credentials or personal customer/payment data appear in the supplied file.
- **Explicit ID mapping:** sample `SB-10482` -> snapshot `10482` (First Hill).
  Sample `SB-11937` and `SB-20516` have no supplied snapshot counterparts. They
  MUST use explicit store/stock contract fixtures in these tests. Do not map
  either to snapshot `11307` or `09815`. Preserve identifiers as strings;
  no heuristic prefix removal. Bellevue Square comes from sample messages.
- The single March 7 snapshot MUST NOT serve as a fabricated week-long stock
  history. Refusal fixtures specify the tag's necessary conditions; absent
  counts, recipes and hours are synthetic test setup, labelled as such in JSON.
  Source submitted_at offsets are preserved verbatim; tests MUST NOT silently
  reinterpret those timestamps as authoritative current store hours.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001:** All 21 refused sample cases return their exact HTTP/JSON refusal
  and have zero payment requests and zero queue entries under their fixtures.
- **SC-002:** R1 -> AC-R1; R2 -> AC-R2; R3 -> AC-R3; R4 -> AC-R4; R5 -> AC-R5.
  Each `refusal-cases.json` entry records its rule and criterion; no rule lacks
  a testable input/precondition/exact response. These are planned contract tests,
  not assertions that an unimplemented order service has passed them.
- **SC-003:** The accepted race case succeeds with its valid hold; concurrency,
  expiry, dependency failure, unknown store and retry criteria prevent oversell,
  premature payment and duplicate charges.
- **SC-004:** Before implementation merges, all service and contract tests pass
  for that commit, with required CI checks enforced. This documentation-only
  commit MUST leave stock service code, stock tests and workflow unchanged.

## Assumptions

Catalogue/recipes and historical fixture values beyond the supplied columns are
future test setup, not inferred facts. Hold TTL 120 seconds, refusal HTTP/code
choices, whole-basket behavior and deterministic error selection are drafting
decisions for the next contract review. No remaining clarification placeholders.
UI, real payment integration, deployment, live inventory and implementation of
these future services are excluded from this commit.
