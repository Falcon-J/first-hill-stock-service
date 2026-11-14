# Boundary decisions

- Decision: stock owns hours, counts, recipes and atomic full-basket holds.
  Rationale: only that owner can serialize competing demand and POS/feed changes.
  Rejected: shared tables, replicas and order-side count arithmetic.
- Decision: reserve then confirm current stock before payment. A menu read is
  advisory. Confirmation creates a pinned allocation, accounted for by stock.
  Rationale: a still-valid hold cannot prove physical stock after a POS change.
  Rejected: trusting last_updated_at or starting payment after menu availability.
- Decision: 120-second holds with idempotent terminal transitions, owner-scoped
  keys and 24-hour tombstones; query the original key after uncertain reserve.
  Rationale: retries and network loss must not leak or duplicate reservations.
- Decision: preserve the owning teams' error envelope; additive details array,
  deterministic primary failure, three-second shared deadline.
  Rationale: existing clients display error.message and retry 502/503/504.
  Rejected: the earlier flat refusal envelope and 5xx business stock refusals.
- Decision: real provider assertions stay red while implementations are absent.
  Rationale: draft checks define the build target without fake green evidence.
  Tests run in process, with controlled upstream transports and no external calls.

All choices come from the owning-team review and existing constitution. No
unresolved research question remains. OpenAPI reference:
https://spec.openapis.org/oas/v3.1.1.html
