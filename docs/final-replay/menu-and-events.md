# Menu coverage and mid-checkout replay

The remaining recipe gaps were ours: missing stores masked unsupported menu
items. Every one of the 40 supplied order lines now resolves in the stock-owned
catalogue. Caramel macchiatos include vanilla and caramel even when the add-in
column is empty. Mocha, white chocolate mocha, cappuccino, flat white, iced chai,
iced matcha, whole/soy milk, classic syrup and chocolate foam are registered.
This retains the project's explicit one-unit-per-component demo convention;
these are not verified commercial size-specific recipes. Registration creates
no inventory and does not turn missing components into zero-count rows.

## Sequence and tests

`tests/test_final_menu_coverage.py` checks all 40 source lines plus required
recipe ingredients. `tests/test_final_events.py` checks event ordering, source
hashes, store identity, missing events and failed feed acknowledgement.
`tests/test_final_event_providers.py::test_final_mid_checkout_real_providers`
uses all four flagged baskets against real stock/order/gateway applications:
menu availability, a feed update, checkout with the menu token, then 409
STOCK_CHANGED with the named component, zero payment calls, zero queue/outbox
entries, no new reservation and unchanged pre-existing reserved totals.
Its inventory and events are explicitly synthetic, not held-out replay evidence.

The final replay now performs that sequence when supplied an event manifest.
The menu HTTP call and feed transaction run inside stock's isolated test
container. Order and gateway never access stock's database. Feed updates use the
existing transactional `Inventory.apply_feed`; no new public API is exposed.
Only physical count and timestamp changes are permitted. Unknown stores or
components remain errors. Missing events and unavailable menu reads are separate
scenario failures even if the source outcome happens to match.

Pass `--events path/to/events.json` or supply `docs/final-replay/events.json`.
The JSON object requires `provenance`, `source_sha256` (exact `orders.csv` and
`stock.csv` SHA-256 values), and `events` keyed by order ID. Each event contains
`store_id`, `menu_at`, `effective_at`, and `components` keyed by actual snapshot
component ID. Each component update contains integer `quantity_on_hand` and
`last_updated_at` equal to `effective_at`. Require menu_at < effective_at <= the
order's submitted_at. Replay executes these phases in order without historical
wall-clock sleeps; availability-token deadlines use the current service clock.
Provenance is a recorded source statement, not a cryptographic authentication.
Review the supplier/approval separately. No authoritative event file has been
received or invented for this change.

## Exact remaining source requirements

The supplied stock file still has no rows for:

| Store | Affected order lines |
|---|---:|
| STB-10358 | 3 |
| STB-10417 | 3 |
| STB-10466 | 5 |
| STB-10503 | 5 |
| STB-10529 | 5 |
| STB-10588 | 6 |
| STB-10611 | 7 |

Provide a corrected March 10 snapshot or explicitly approved supplement covering
every recipe component at those seven stores, with store/component identity,
on-hand count, reserved count, units, timestamps and store hours/open status.
Do not infer aliases or counts from expected outcomes.

At the present store STB-10342, supply cold brew (0302), coconut milk and
strawberry açaí base (0553), and chai concentrate (1268). These missing rows
affect four order lines; recipe registration alone cannot supply their stock.

Provide menu-time inventory and independently sourced stock-change events for
0371 (oat milk), 0516 (chai concentrate), 0731 (vanilla sweet cream cold foam),
and 1047 (vanilla syrup), all prefixed MO-20250310-. The CSV flag identifies the
scenario but does not supply event quantities or times. Bind events to the
corrected input hashes and identify their source or explicit approval.

Current immutable input hashes:

- orders.csv: `6c1d31093e11fea50a59b6bd800ca176fdd6dd7d10b509e2e875e9bdc8a1f46d`
- stock.csv: `651326beceb9273dddd0b993bfd6912574efdc1ea52ea3ab5c67d99afeaffeeb`

The PR remains draft until the real replay matches 40/40 and both required checks
are green. Synthetic provider proofs cannot substitute for that result.
