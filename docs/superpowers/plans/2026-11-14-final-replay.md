# Final rebuild and holdout verification plan

**Goal:** Rebuild the three services without cached images or state, run frozen contracts, replay the final supplied data, and audit service ownership before handing over the existing PR.

**Architecture:** Preserve the versioned API boundaries. Only stock loads the final snapshot. The replay runner groups source lines into whole baskets and calls the gateway; expected labels remain in the assertion layer. Test-only inspectors run inside the service owning each database.

**Spec:** `CLAUDE.md`, `.specify/memory/constitution.md`, `specs/002-service-contracts/plan.md`.

## Constraints and data ruling

- Fix implementation, never weaken frozen contracts or change source expected answers.
- No guessed store aliases, fabricated stock, cross-service database reads or payments on uncertain stock.
- The supplied final orders contain 40 lines across eight stores; only six lines at STB-10342 have a store in the supplied five-store snapshot. Seven order stores have no stock rows. This prevents an honest 40/40 claim; request the missing owner feed and record actual failures meanwhile.
- Menu, recipe and feed prerequisites are distinct from expected results. Do not reuse the earlier sample's synthetic per-scenario stock fixtures for this holdout.

## Tasks

- [ ] Save both source CSVs unchanged with hashes and source names.
- [ ] Remove only this project's development containers/volumes, build all three images with `--no-cache`, start from Compose and record three healthy services.
- [ ] Run all frozen contracts, full pytest and lint; preserve output.
- [ ] Add a strict final replay runner and an isolated three-service Compose configuration. Mount source only into stock. Send grouped baskets through gateway, record one result per original CSV line and owner-scoped side-effect counts. Return nonzero on any mismatch.
- [ ] Run replay on GitHub on every push; publish failure reports even when the strict gate is red. Do not hide mismatches with skips, xfail or continue-on-error.
- [ ] Audit stock, order and gateway plus every stage diff boundary; list evidence and keep/fix decisions, including unresolved input dependencies.
- [ ] Update existing PR with actual result, links, decisions, key prompt and two checked claims. Ready for human review does not mean approved for merge; missing feed and any red check remain explicit blockers.

## Review focus

Unknown stores must remain 404; missing recipe components must fail closed; multi-line orders must stay whole baskets; expected source labels must never reach a runtime service; refused or uncertain orders must have zero payment and outbox records.
