# Draft verification evidence

Local run, 14 November 2026, Python environment installed from
requirements-contracts.txt:

```text
python -m pytest -q --tb=short --junitxml=contract-results.xml
59 failed, 32 passed in 15.64s
91 tests, 0 collection/runtime errors, 0 skipped
```

The 32 passes are 17 OpenAPI/document/fixture/workflow assertions and 15 existing
read-only stock tests. All 59 failures are provider assertions: 9 exercise the
existing stock app's missing /v1 routes; 50 explicitly report the missing real
order/gateway provider factory. No test is skipped or marked xfail. No expected-
answer target service or continue-on-error is used. This is the required draft
red phase, not evidence that reservation or payment behavior works.

The Actions contract-tests job runs only tests/contracts: its corresponding
expected draft result is 59 failed, 17 passed. The separate original stock job
runs its 15 tests. Actions must report actual results and retain JUnit. The PR
links its hosted check run; CI counts are checked against this local baseline.

Reviewed the complete staged diff. app.py, tests/test_stock.py and the snapshot
CSV are unchanged. The only change to the original workflow narrows it to its
existing stock suite; the new required contract-tests check remains independently
red and blocks merge. git diff --cached --check reported no whitespace errors.
The boundary review download is preserved verbatim in evidence/.

Review corrections included clock-relative deadlines after expiry, documented
402 lookup responses, stock fixture identities bound to the actual order/store,
and explicit tests for every AC-E edge criterion. Synthetic oat stock remains
an override; real snapshot reservations remain syrup 2 and espresso 4.
