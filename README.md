# First Hill stock service

A Python/FastAPI service reading the supplied **Store Stock Snapshot,
7 March 2025 06:45**: 30 component rows across three Seattle stores.
This repository contains original code, not a fork.

## Rule

`available_quantity = max(0, quantity_on_hand - reserved_quantity)`

Reserved units are already committed to other orders, so quantity on hand alone
would overstate what a new customer can buy. A component is sold out when its
available quantity is zero. It is orderable only when it has available stock
and the store is open. Store and component must both match; espresso stock must
never be returned for oat milk.

| First Hill (10482) | On hand | Reserved | Available | Sold out |
|---|---:|---:|---:|---|
| oat_milk | 0 | 0 | 0 | Yes |
| almond_milk | 38 | 1 | 37 | No |
| two_pct_milk | 96 | 3 | 93 | No |
| espresso_signature (control) | 142 | 4 | 138 | No |

## Run

Requires Python 3.12 or newer. From the repository directory:

```sh
python -m venv .venv
# Windows PowerShell:
.venv/Scripts/Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs for interactive API documentation.

```sh
curl http://127.0.0.1:8000/stores/10482/milks
curl http://127.0.0.1:8000/stores/10482/stock/oat_milk
```

Also supports `/health` and `/stores/{store_id}/stock`. Unknown keys return 404.
CSV data is validated and loaded on startup; restart after changing the snapshot.
Invalid or duplicate records fail startup rather than silently selecting a row.
Store IDs remain strings, preserving `09815`.

## Build prompt

"Build a stock service that reads the supplied 30-row snapshot. Use quantity on
hand minus reserved stock because reservations are already committed. Look up
by store ID and component ID. Start the service and verify each First Hill milk,
with oat milk sold out. Add pytest tests, create my own GitHub repository,
and push one commit stating the rule, prompt, and check line."

## Checks

Tests in `tests/test_stock.py` check all 30 snapshot rows through the API,
the three First Hill milk counts, espresso as a regression control, unknown
keys, closed stores, leading-zero store IDs, and malformed CSV rejection.
GitHub Actions runs pytest on every push and pull request.

Actual local HTTP responses and verification results are saved in
`docs/verification.json` after running the service.

## Scope

This is a historical, read-only stock snapshot service, not live store stock.
It does not reserve quantities, process payments, or accept orders. Preventing
checkout races requires atomic stock reservations in a future order service.
