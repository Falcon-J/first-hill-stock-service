# Draft service contracts

See `specs/002-service-contracts/plan.md` for review-note decisions, ownership,
lifecycle, retries and the 3-second budget. Each OpenAPI file is standalone:

- stock-service.openapi.yaml: inventory-owned basket decisions and bounded,
  atomic reservations with confirm/release/status and idempotency.
- order-service.openapi.yaml: durable order attempts; confirm current stock
  before payment, release on terminal failure and reconcile uncertain outcomes.
- gateway.openapi.yaml: /v1 public routing and compatible error pass-through.

The existing snapshot API is not rewritten by this draft. No new service provider
or expected-answer stub is supplied. The provider tests are deliberately red
until the next build stage implements the actual contracts. Do not bypass the
required check with skips, xfail, continue-on-error or a fake success server.

```sh
python -m pip install -r requirements-contracts.txt
python -m pytest tests/contracts/test_documents.py -q
python -m pytest tests/contracts -q --junitxml=contract-results.xml
python -m pytest tests/test_stock.py -q
```

`test_documents.py` checks OpenAPI structure, schemas/examples, cross-boundary
compatibility, all 21 sample refusals, numeric rollback baselines and CI settings.
`test_providers.py` tests real providers: stock lifecycle/race/POS loss/replay,
all source order refusals without payment, ordering/idempotency and gateway
pass-through/deadlines. Missing order/gateway providers fail assertions inside
test bodies; legacy stock returns 404 on missing reservation endpoints. Neither
condition is a passing reservation implementation.

Controlled upstream dependency doubles use httpx.MockTransport. TestClient calls
the actual target ASGI app in memory. External socket connections are blocked;
loopback/Unix IPC is allowed for the job and Windows asyncio's own socketpair.
There are no live feeds, deployed services or third-party API calls.

The workflow's job/check is named exactly **contract-tests**, runs on push and
pull_request using Python 3.12, and uploads JUnit on failure. The actual base
branch codex/stock-service now requires this context, strict up-to-date checks
and administrator enforcement. Failing or missing contract-tests blocks merge.

Error compatibility: old clients continue reading `error.message`. Reason code,
line and missing component are machine-readable; all failures can be represented
in sorted `error.details`, while the primary failure remains deterministic.
Product owns message wording; copied sample messages are fixtures, not enums.
Known business refusals are never returned as app-auto-retried 502/503/504.
