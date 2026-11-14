Stock owns the supplied snapshot, catalogue, store hours, feeds, holds and allocations.
The default data is a historical demo snapshot, not a live inventory connection.
Only the explicit alias `SB-10482 -> 10482` is configured. Other stock store IDs
are accepted as exact strings; unknown sample IDs are never guessed.
The small catalogue uses documented demo recipe units, not historical recipes.
Unsupported recipes fail closed. Injected `initial_state.recipes` is authoritative.

Run `uvicorn services.stock.app:app --port 8000 --workers 1` from repository root.
Inject `STOCK_SERVICE_TOKEN` at runtime. No default credential is accepted.
`STOCK_STORAGE_PATH` points to the stock-private SQLite file (a private volume in
Docker); unset means ephemeral in-memory state for tests. `STOCK_SNAPSHOT_PATH`
optionally selects inventory's seed CSV. Readiness is `GET /v1/health`.

SQLite commits the complete inventory and owner-scoped idempotency state together,
using WAL and FULL synchronous mode. Refused and successful attempts are retained
indefinitely (at least 24 hours). Menu tokens are opaque random, owner/basket-bound,
expire after 120 seconds and never reserve stock. Holds expire on access plus a
one-second background sweep while the application lifespan is active.

The default container starts one worker. Correctness now also holds across stock
workers using the **same inventory-owned SQLite file**: BEGIN IMMEDIATE acquires
the write lock before loading state, checking quantities and publishing all holds.
The local RLock protects a connection; the SQLite transaction coordinates workers.
Separate inventory copies or independent volumes are not a single authority.
Keep this database on a local durable volume; multi-host storage is not claimed.
Back up the private volume and keep the service identity stable across restarts.
Without a configured file, a restart loses state and is unsuitable for real orders.

If stock dies before commit, the transaction rolls back. A committed hold survives
in inventory_state.payload.reservations with its public.expires_at timestamp;
restart/on-access expiry releases unconfirmed holds at their original 120-second
boundary. Confirmed allocations do not expire during payment uncertainty.

`app.state.inventory.snapshot(store_id)` is an inventory-owner inspection seam.
`apply_feed(store_id, changes)` is a trusted in-process adapter seam, never an HTTP
mutation API. Feed values are physical counts **before inventory's pinned confirmed
allocations**; the adapter subtracts those allocations and refuses writes to reserved
totals. A production feed must implement this explicit accounting convention and
version/reconcile its snapshots, rather than sending ambiguous absolute values.

Release of a confirmed allocation is an owner-authenticated **unpaid cancellation**
instruction. Order must never send it after capture or while payment is uncertain;
the present stock contract has no payment/capture reporting endpoint, so inventory
cannot independently prove capture status. Captured allocations stay pinned. A
production integration needs explicit final settlement/feed reconciliation before
pruning pinned allocations or idempotency records.
