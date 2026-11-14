# Overselling fix and executable evidence

**Crash rule:** Before commit, a stock-container crash leaves no hold; after
commit, the stock-private SQLite record retains the hold and its
`public.expires_at`, and restart/on-access expiry releases unconfirmed holds at
their original 120-second boundary. Order cannot pay without confirmed stock.

Expiry is written by `Inventory.reserve` in services/stock/inventory.py into
inventory_state.payload.reservations[reservation_id].public.expires_at.
`Inventory.expire` checks now >= expires_at and only releases status=reserved;
confirmed allocations remain protected during payment uncertainty.

## Reproduced root cause

The previous RLock protected one Python process. Each worker cached a separate
copy of stock and could overwrite the same database record after both saw one
unit available. Before the fix, both the two-process stock regression and the
full gateway/order/stock HTTP race returned **201, 201**. A deliberately crashed
write also exposed an early commit inside the old save helper.

The stock owner now obtains BEGIN IMMEDIATE, reloads current state inside that
write transaction, checks hours/available demand, and commits the complete basket
and idempotency outcome together. Seeding is serialized too. An unsuccessful
transaction rolls back; a busy/unavailable database gives the defined 503 instead
of permission to charge. Stock workers share only their service's private file.
Order and gateway continue to use HTTP and cannot read stock persistence.

## Run the proofs

```powershell
python -m pytest tests/test_stock_transactions.py tests/test_gateway_race.py tests/test_gateway_replay.py -q
python scripts/init_demo_env.py
docker compose -p first-hill-overselling -f compose.overselling.yaml up --build --detach --wait --wait-timeout 180
python -m pytest checks/live_overselling.py -q
```

The isolated stack starts three containers, with two stock and two order workers
to expose the old cross-worker defect. Its volumes and localhost ports differ
from normal Compose. Test operators are mounted read-only and require the explicit
ALLOW_TEST_FIXTURES flag; they execute inside the owning stock/order containers.
No production fixture endpoint or cross-service database access is added.

The socket race submits simultaneous distinct-key purchases through the gateway,
requires one accepted and one exact oat-milk refusal, and inspects owner-local
payment/queue counters and conserved stock. The replay sends every source order
through the real gateway and validates each source result and exact refusal.
See replay-provenance.md for explicit synthetic historical preconditions; the
single real snapshot is never rewritten into a fabricated week's inventory.

Source recipe/count fixtures are test data, never acceptance rules. Runtime
services receive ordinary baskets with no scenario tag or expected outcome.
Normal pytest exercises the real in-process HTTP chain; the explicit socket
suite additionally requires healthy Docker services and fails if they are absent.
CI runs both suites, with no skipped checks. Contracts, spec.md and CLAUDE.md are
unchanged from the previous stage.

The additional live AC-E2 control stops only the isolated test stock container
before submitting MO-250303-0002's valid basket. It expects 503
STOCK_CHECK_UNAVAILABLE and zero payment/outbox rows. It is labelled separately
from the CSV replay: that source order's normal expected outcome stays accepted.

`tests/test_lost_stock_reply.py` separately forwards reserve/confirm requests to
the real stock app, then drops the successful committed reply in the delivery
transport. Both cases require first503 with zero payment/queue calls, committed
state surviving a stock restart, and same-key reconciliation completing once.
This is a real-provider commit with injected delivery loss, not a claim of a
socket-level network proxy or an extra source-CSV scenario.

SQLite transaction reference: https://www.sqlite.org/lang_transaction.html .
