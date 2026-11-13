# Submission verification

Rule: Availability = max(0, quantity_on_hand - reserved_quantity), because
reserved units are already committed to other orders and cannot be sold again.

Key prompt: Build and start a stock service reading the supplied 30-row snapshot;
check each First Hill milk with oat milk sold out; add pytest and push the code,
test, rule, prompt, passing test output, and specific comparison evidence to an
original GitHub repository.

Check: Compared First Hill (10482)'s API replies against the snapshot rows for
oat_milk (0 on hand, 0 reserved -> 0 available, sold out), almond_milk
(38 - 1 -> 37 available), and two_pct_milk (96 - 3 -> 93 available);
all three matched. Espresso is a separate control with 142 - 4 = 138.

The parameterized `test_first_hill` in `tests/test_stock.py` explicitly includes
`('oat_milk', 0, 0, 0, True)` and asserts the response's `sold_out` flag is True.
The suite also compares every snapshot row through the API.

Command: `python -m pytest -q` (isolated Python 3.12 environment).

Passing output from the submission rerun:

```text
...............                                                          [100%]
15 passed, 1 warning in 6.35s
```

The warning is Starlette's deprecation notice for its httpx TestClient integration;
there were no test failures. The running HTTP service was also compared against
all 30 source rows; details are in `verification.json`.
