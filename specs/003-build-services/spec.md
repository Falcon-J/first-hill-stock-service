# Build the three contracted services

Implement the existing versioned contracts and all existing acceptance criteria;
do not replace or weaken the 85 contract checks. Each service has its own folder,
Dockerfile, private storage and runtime credentials. Stock alone loads the 30-row
7 March 2025 snapshot. Gateway -> order -> stock uses HTTP exclusively.

The order spec's reserve -> confirm current stock/commit allocation -> authorize
-> capture -> accept/queue sequence applies to both successful source stores.
Stock's 120-second expiry applies only to unconfirmed reservations. Confirmed
allocation stays pinned while payment is uncertain; decline restores once.

Retain all five refusal rules and exact envelopes, including numeric rollback
baselines and named StockChangedEnvelope for menu-available/checkout-gone races.
The real snapshot's First Hill oat milk remains 0 on hand and 0 reserved, so a
fresh oat latte returns BASE_OUT_OF_STOCK with line 1 and missing_component
Oatmilk; no synthetic race unit is inserted into runtime snapshot data.

Build acceptance evidence:
- All existing contract tests pass with no skips/deletions/loosened assertions.
- Stop hook invokes full pytest and lint, demonstrably blocks a failing test and
  permits finishing only after the failure is fixed.
- Compose starts the three containers. Query the public gateway for First Hill
  oat latte and retain exact request/status/body plus HTTP call metadata.
- PR description lists service calls, key prompt, changed/rejected alternatives,
  latest green Actions and the observed refusal. Update existing PR #1.

Development payments may use an explicit no-charge adapter for local validation;
production payment integration must be configured independently and fail closed.
