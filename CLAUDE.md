# Standing instructions: mobile ordering services

Read `.specify/memory/constitution.md` and `specs/001-order-refusals/spec.md`
before changing a service. This file governs future implementation; this commit
adds specifications only and does not claim the order service exists.

For the service-boundary draft, read `specs/002-service-contracts/plan.md` and
the three `contracts/*.openapi.yaml` files. The owning-team review supersedes
the earlier flat refusal wire shape: preserve `{error: {code, message},
request_id}` and add line/component/details inside error. Older flat JSON stays
source acceptance evidence; it MUST NOT be emitted as the new public response.
Only stock decides fulfilability/recipes/current open state; order sends the
original basket and MUST NOT calculate a decision from raw stock counts. Gateway
routes/translates only. All public paths MUST start /v1 and the end-to-end order
budget MUST remain 3 seconds including every stock/payment call and retry.

## Three mandatory engineering rules

1. **Fixed OpenAPI contracts.** Every gateway, order and stock endpoint MUST
   implement its checked-in, versioned OpenAPI contract exactly. Freeze schemas,
   status codes, error codes and examples before implementation. A breaking
   change MUST use a new API version and update consumer/provider contract tests
   together. Runtime-generated documentation alone is not a frozen contract.
2. **No shared database.** Each service MUST own its data and credentials. A
   service MUST NOT read or write another service's database, tables, files or
   shared ORM models. Cross-service access MUST use the versioned API. The stock
   service alone MUST own stock and atomic reservation mutations.
3. **No merge until contract tests pass.** Every merge MUST have passing
   gateway/order and order/stock consumer/provider contract tests and service
   pytest suites for that commit, including all refusal criteria below. Missing,
   skipped, stale or failing contract checks MUST block merge. This requirement
   is a policy; branch protection and the future contract-test jobs MUST be
   configured before an implementation merge. The current stock-only workflow
   is not evidence that the future contracts passed.

## Five mandatory refusal rules

Apply these rules to the entire basket before payment. Every refusal MUST return
the exact status, code and message defined by the mapped spec criterion, create
no accepted order or barista queue entry, initiate no payment, and retain no
partial stock hold. Evaluate the open-store rule before stock. For multiple
missing components, select the lowest line number then component ID in ascending
lexical order. The submitted scenario tag is evidence only; services MUST derive
the decision from trusted store/stock responses, never from a client label.

- **R1 — `store_closed`:** The order service MUST refuse the entire order when
  the authoritative store-hours result says closed at reservation time or at
  final confirmation. It MUST NOT treat stock on hand as permission to order
  from a closed store. Return HTTP 409, `STORE_CLOSED`; see **AC-R1**.
- **R2 — `base_out_of_stock`:** The order service MUST refuse the entire order
  when any required drink base or chosen milk has zero available stock
  (`max(0, quantity_on_hand - reserved_quantity)`). It MUST identify the missing
  component and MUST NOT substitute another milk or espresso stock. Return HTTP
  409, `BASE_OUT_OF_STOCK`; see **AC-R2**.
- **R3 — `add_in_out_of_stock`:** The order service MUST refuse the entire order
  when any requested or recipe-required add-in has zero available stock. It MUST
  NOT silently remove the add-in. Return HTTP 409, `ADD_IN_OUT_OF_STOCK`; see
  **AC-R3**.
- **R4 — `insufficient_quantity`:** The order service MUST aggregate recipe
  component demand across all lines and quantities and refuse the entire order
  when a component has positive available stock below the total required. It
  MUST NOT accept one item from a larger unfulfillable basket. Return HTTP 409,
  `INSUFFICIENT_QUANTITY`; see **AC-R4**.
- **R5 — `stock_runs_out_mid_order`:** An earlier successful stock read MUST NOT
  authorize acceptance or payment. Menu-time availability MUST NOT be treated
  as a reservation. If the atomic all-component hold loses a
  race and cannot reserve the full basket, the order service MUST refuse the
  entire order and MUST name the lost component. Return HTTP 409,
  `STOCK_CHANGED`; see **AC-R5**. A confirmed, unexpired hold can still succeed
  even when unreserved stock later becomes zero; see **AC-P2**.

  AC-R5 MUST distinguish the refused CSV row `MO-250307-0024` from its designed
  menu-to-checkout race. AC-P2 MUST distinguish the accepted CSV row
  `MO-250307-0023` from its designed winning-hold alternative. These fixture
  sequences MUST NOT be presented as event history recorded by the CSV.
  AC-P2's ordering assertion MUST exercise the full AC-P1 sequence for the same
  race order `MO-250307-0023` at `SB-10482`, including zero payment requests
  before its confirmed hold and committed allocation. A passing test for the
  different store/order in AC-P1 MUST NOT substitute for this race-order test.
  AC-R5's rollback fixture MUST name the loser's tentative syrup and espresso
  allocations and prove neither becomes a committed partial hold. After the
  failure, their committed reservation totals MUST be unchanged, and the
  winner's oat-milk hold MUST retain its original ID, owner and quantity.
  The concrete AC-R5 fixture MUST assert committed reserved totals of syrup
  **2 -> 2** and espresso **4 -> 4**, using the cited snapshot baselines while
  explicitly labelling its oat-milk race stock as a synthetic override.
  Check the explicit numeric reservation assertions at the start of AC-R5:
  `brown_sugar_syrup.reserved_quantity == 2` and
  `espresso_signature.reserved_quantity == 4` both before and after refusal.

## Refusal-rule traceability

| Rule | Refused source rows | Spec criterion | Exact response definition |
|---|---:|---|---|
| R1 | 4 | AC-R1 | 409 / STORE_CLOSED / store-name template |
| R2 | 6 | AC-R2 | 409 / BASE_OUT_OF_STOCK / component template |
| R3 | 5 | AC-R3 | 409 / ADD_IN_OUT_OF_STOCK / component template |
| R4 | 2 | AC-R4 | 409 / INSUFFICIENT_QUANTITY / component template |
| R5 | 4 | AC-R5 | 409 / STOCK_CHANGED / component template |

`specs/001-order-refusals/refusal-cases.json` enumerates all 21 refused source
orders with their exact input, controlled service precondition and full expected
response. Every listed case MUST become a contract test before order-service
implementation can merge. `scenario-audit.md` records all 40 source outcomes.

## Implementation guardrails

Use Python and FastAPI, one independently built and deployed container per
service. Write a failing test before implementation. Keep secrets in injected
environment variables or a secret manager; MUST NOT commit credentials or log
payment tokens. Stock MUST be reserved atomically before payment and released
on refusal/cancellation/expiry. Missing or uncertain stock/hours replies MUST
block payment and acceptance; AC-E2 defines the exact 503 response.

Store IDs MUST remain strings. No implicit stripping of `SB-` or leading zeros
is permitted. The sample-order IDs and stock-snapshot IDs MUST be connected only
through the explicit mapping in the spec; unknown mappings MUST be refused.
