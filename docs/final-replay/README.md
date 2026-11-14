# Final March 10 replay: actual results and open feed request

**Not a successful final replay: 0/40 exact source-line matches.** The services fail closed: all 28 whole-basket attempts produced zero simulated payment rows and zero queue/outbox rows. That prevents a charge, but a 404 or 422 is not the business result the holdout asks for.

## Sources (unchanged)

- Zero resource / attached file: `Held-out Mobile Orders for Final Replay (10 March 2025).csv` → `orders.csv`. SHA-256 `6c1d31093e11fea50a59b6bd800ca176fdd6dd7d10b509e2e875e9bdc8a1f46d`.
- Zero resource: `Store Stock Snapshot for Final Replay (10 March 2025, 06:45)` → `stock.csv`. The colon in its proposed Windows filename was invalid, so only the filename was changed. The reattached `Store Stock Snapshot for Final Replay.csv` is byte-identical. SHA-256 `651326beceb9273dddd0b993bfd6912574efdc1ea52ea3ab5c67d99afeaffeeb`.

The source has 40 **line rows**, grouped into **28 orders**, across eight store IDs. The 30-row snapshot contains five stores. Only STB-10342 overlaps, covering six order lines. `summary.json` gives the exact sets and hashes. No original value was rewritten.

## Actual baseline replay (a7a6fd5, before the narrow catalogue adapter)

`checks/final_replay.py` submits each complete basket to the real Docker gateway on localhost:18083. Gateway calls order, and order calls stock over HTTP. Stock alone mounts and loads the supplied CSV. No source expected outcome/tag/message enters a service request. There are no per-scenario stock overrides, guessed aliases or expected-answer providers.

- **34 lines:** HTTP 404 `STORE_NOT_FOUND`, because seven order stores have no snapshot rows.
- **Six lines at STB-10342:** HTTP 422 `INVALID_ORDER`, because the existing explicitly limited demo catalogue cannot resolve their final source vocabulary/recipes. They are MO-20250310-0209/1, MO-20250310-0302/1 and /2, MO-20250310-0553/1, MO-20250310-0624/1 and MO-20250310-1268/1.
- **28 order attempts:** zero development-payment and outbox rows, checked by the read-only inspector inside the order owner's container. The runner does not read stock/order SQLite files on the host or from another service.
- Strict exit status **1**. Every row's expected/actual outcome, status, component, message, side effects and diagnosis is in `results.csv`; exact gateway envelopes and owner counters are in `responses.json`.

Do not substitute the previous stage's designed 40-case sample replay for this holdout. The previous sample fixtures deliberately supplied synthetic historical preconditions; this final run does not.

## Feed owner request / unblock conditions

To Store Inventory Systems (Tobias Wren / Keiko Hamasaki), via the manager: supply the March 10 06:45 stock rows or an explicit authoritative mapping for **STB-10358, STB-10417, STB-10466, STB-10503, STB-10529, STB-10588 and STB-10611**. A near-match to one of the other four snapshot stores is not an authorized mapping.

Also provide the compatible trusted catalogue/recipe/component units and the intervening stock/hold events for `mid_order_sellout`. The order CSV's labels are expected results, not an authoritative recipe/feed or recorded explanation of how stock changed. Keep store IDs as strings and unknown stores refused while these inputs are missing. Implement any compatible provider mapping with a failing test first; never obtain 40/40 by assigning counts from expected outcomes.

There is also a comparison contradiction: MO-20250310-0167 has two source lines (CSV 6–7) requiring different exact error messages for one whole-basket response. The frozen API has one error.message, so both cannot match simultaneously. The owner must clarify the authoritative order-level expectation or intended line-display comparison. This is an additional blocker even after the missing feed is supplied; neither source nor contract was relaxed.

## Reproduction and CI

From repository root, with runtime `.env` created by `python scripts/init_demo_env.py`:

```powershell
docker compose -p first-hill-final-replay -f compose.final-replay.yaml down --volumes --remove-orphans
docker compose -p first-hill-final-replay -f compose.final-replay.yaml build --no-cache
docker compose -p first-hill-final-replay -f compose.final-replay.yaml up --detach --wait --wait-timeout 180
python checks/final_replay.py --output-dir final-replay-results
```

The first command deletes only this isolated development project's state. No global Docker cleanup is used. `.github/workflows/final-replay.yml` runs frozen contracts, builds all three images without cache, starts fresh services and runs this same strict runner on every push/PR. It publishes reports and HTTP logs even when the replay fails. It does not skip or waive the failure. Both `contract-tests` and `final-holdout-replay` are required on the protected base; `required-checks.json` records that configuration.

CI output is exclusively a fresh untracked `final-replay-results/` directory, with a run marker distinguishing not-started/in-progress/completed states, GitHub run ID/SHA and completed baskets. It never republishes the checked-in local evidence as a new CI result. Each local rerun likewise needs a fresh output directory.

## Clean rebuild and audit evidence

The normal demo project was removed, including its two development volumes; all three images were rebuilt with `docker compose build --no-cache`, then started with `up --detach --wait`. `rebuilt-containers.jsonl` records three newly created running/healthy services. `local-final-containers.jsonl` records the separate final-source stack. These are local observations, not GitHub run artifacts.

`audit.md` lists every service and changed boundary with an explicit keep/fix decision. The subsequent narrow adapter changes only stock-owned catalogue resolution/category interpretation among runtime services. Order/gateway code, OpenAPI contracts, specs and CLAUDE.md remain unchanged. A ready-for-review PR invites review of the evidence and input blockers; it is not merge approval or a claim of 40/40.

Local verification: 85 frozen contracts passed; two new parsing/whole-basket tests passed; Ruff passed. The first full local run returned 1 failed/147 passed while Docker built; a second returned the same counts with a different old sample case hitting the three-second deadline. Their raw reports are saved as local diagnostics. Neither run is described as green, and no deadline/assertion was relaxed. See the PR's linked latest Actions run for current validation on that commit.

After stopping local proof containers, the full suite passed **148 tests in 118.40s**. Comparator coverage was subsequently expanded: all six final-replay helper tests pass, including wrong-code/line/envelope/correlation rejection and complete matching positive cases. Current CI, rather than the earlier 148-test run, is the evidence for the expanded full suite.

## Subsequent bounded fix

As requested in manager review, inventory now accepts registered spellings for the existing oat-drink recipes and maps their ingredient identities to unique compatible component names within that same store. It uses the supplied oat 0/0 unchanged, rather than allowing validation to hide the shortage. Provider tests now return 409 BASE_OUT_OF_STOCK for 0209 and 0624 with no hold or count mutation. Unsupported recipes and stores stay refused. The API message wording remains frozen and still differs from the final source text; these two rows are not declared exact matches. Five initial adapter cases plus six replay-input/matcher cases and 85 frozen contracts passed together (96 tests). A sixth adapter regression then preserved the existing UNKNOWN_ITEM result for missing recipe components; all 12 final cases passed in 3.33s. See `catalogue-gap.md` for before/after proof and the PR's latest run for the fresh gateway replay.

Final local implementation verification: **158 passed in 92.83s**, Ruff green; raw output is `local-tests-adapter.txt`. The full suite includes the frozen contracts and new compatibility regressions. This green service suite does not turn the separate holdout's unresolved source mismatches into passes.
