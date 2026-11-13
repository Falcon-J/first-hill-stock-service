# Stock service implementation plan

Goal: Read the supplied 30-row snapshot and report stock by exact store and component.

Architecture: Python/FastAPI loads and validates CSV at startup. A lookup uses
the pair (store_id, component_id), preserving store IDs as strings. Available
quantity is max(0, quantity_on_hand - reserved_quantity). Sold out means zero
available; orderable additionally requires an open store. This is a historical,
read-only snapshot, not live inventory or a reservation/order service.

Files: app.py for API and CSV validation; tests/test_stock.py for regression and
snapshot comparisons; data/stock_snapshot.csv for original data; requirements.txt,
README.md and .github/workflows/tests.yml for installation and CI.

- [ ] Write and run failing API tests for all snapshot rows, First Hill's three
  milks (0, 37, 93), espresso (138), unknown keys, closed store and bad CSV.
- [ ] Implement validated loader and GET /health, /stores/{store_id}/stock,
  /stores/{store_id}/stock/{component_id}, and /stores/{store_id}/milks.
- [ ] Run full pytest suite, start server, and save real HTTP milk responses.
- [ ] Document usage and limits; create private GitHub repository and push code.

Review focus: duplicate composite keys; invalid counts; closed stores; missing
keys; preserving leading-zero store IDs. Cover all in the tests.
