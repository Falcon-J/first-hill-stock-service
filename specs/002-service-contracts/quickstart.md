# Validate the draft

Use Python 3.12 in an isolated virtual environment at repository root:

```powershell
python -m pip install -r requirements-contracts.txt
python -m pytest tests/test_stock.py tests/contracts -q --junitxml=contract-results.xml
```

Document/schema tests and the 15 original stock tests must pass. Provider
assertions deliberately fail until services.stock/order/gateway expose the real
factories described in plan.md. Do not skip, xfail or return fixtures from a
substitute target app. Upstream HTTP transports and clocks are controlled test
dependencies, not the provider being tested.

GitHub Actions runs contract-tests on every push and pull_request, uploads JUnit
even for a red run, and blocks merge on the protected base. The independent
existing stock workflow remains green. See coverage.md for criterion-specific
commands/test names and verification.md for the recorded run.

After provider implementation, validate the menu-to-checkout race, exact
loser refusal/no payment, unchanged winner, expiry/retry safety and confirmation
after a POS change before requesting merge. This draft does not claim these
paths have been built.
