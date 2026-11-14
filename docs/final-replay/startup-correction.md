# Concurrent stock-worker startup correction

Push Actions run **43598800535** on `5fc3199` exposed a real startup failure in the unchanged two-process stock regression. One child raised `sqlite3.OperationalError: database is locked` at `PRAGMA journal_mode=WAL`, before reaching the reservation barrier. The suite reported 1 failed / 161 passed. The corresponding PR-event run passed, which showed the race was intermittent; it was not dismissed or rerun away.

SQLite's journal-mode change can return BUSY immediately while another worker initializes the same inventory-owned file. The existing reservation `BEGIN IMMEDIATE` transaction did not cover that earlier configuration operation.

## Fix and red/green evidence

- `enable_wal` retries only SQLite BUSY/LOCKED base/extended codes while initializing the journal, with a monotonic retry deadline and short backoff. It consumes the PRAGMA result before proceeding.
- The retry scheduling deadline is one second; an individual SQLite execute can additionally consume the configured one-second busy timeout. This is worker startup before readiness, not a change to the three-second order request budget.
- FULL synchronous mode, schema setup, `BEGIN IMMEDIATE`, seed read/write and commit remain in the same startup path. The reservation transaction and the original two-process [201,409] assertions are unchanged.
- Any unrecovered initialization failure rolls back/closes the connection and propagates. Disk I/O errors are not retried or suppressed.

Before the fix, the two fault tests failed: transient WAL BUSY was not retried, and an I/O failure left the connection unclosed. After the fix, **eight startup/stock-transaction tests passed in 40.09s**, including the original two-process reservation test. A third new test asserts retry deadline exhaustion. Independent review found no Important issues and independently ran the three startup cases (3 passed).

This correction is separate from the final source replay: the corrected two-column oracle already reports two matched rows and 38 data-dependent mismatches, with zero boundary failures. A startup fix must not turn missing stock data into a false 40/40 claim. The PR links the final complete-suite and gateway replay runs after this change.

## Seed-transaction rollback and an existing live order

`test_seed_busy_cleanup_preserves_other_worker_live_hold` creates a real committed winner hold, keeps that worker's real database transaction live, and injects BUSY specifically at a second worker's seed `BEGIN IMMEDIATE` (after already-established journal/schema setup). It asserts the exact cleanup sequence: **seed BEGIN busy → rollback second connection → close second connection**. The first connection remains in its transaction, with the same reservation ID/public record. That winner then confirms successfully; restarting from the file returns the same confirmed reservation and oat counts 0 on hand / 0 reserved. The second worker's cleanup cannot release or alter another connection's hold.

This is a targeted seed-failure injection over a real shared database, not a claim that a startup worker served an order. A failed worker never becomes ready. An already live worker retains its allocation/transaction; requests whose stock outcome cannot be confirmed fail closed before payment, as the existing order timeout/lost-reply tests prove. All four startup tests pass (4.08s), with Ruff green; no production code changed for this additional proof.
