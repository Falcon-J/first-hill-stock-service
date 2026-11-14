# Historical-scenario replay provenance

The 40 baskets come unchanged from
`specs/001-order-refusals/evidence/mobile-orders-2025-03-03-to-09.csv`.
The evidence contains order inputs, scenario labels and expected results; it is
**not inventory history**. Every replay starts a fresh stock app and order database.
Submitted timestamp offsets are preserved, but the authoritative injected clock
is fixed at 2025-03-07T14:31:00Z and open/closed state is explicit fixture data.

Only `SB-10482` aliases snapshot store `10482` (First Hill). `SB-11937` and
`SB-20516` are standalone synthetic stores retaining those exact identifiers.
Bellevue Square's display name comes from the source refusal messages.
Neither is mapped to another snapshot store.

`tests/replay_support.py` provides reusable `load_orders()`,
`make_fixture(row) -> (initial_state, basket, metadata)` and `expected_refusal(row)`.
The injected `initial_state.recipes` is an authoritative synthetic test catalogue;
this does not add recipes or stores to the runtime catalogue. No source scenario,
expected outcome, price, component label or expected message is sent to a service.
The helper uses scenario/component labels only to construct stock preconditions.
The actual stock provider independently resolves demand and chooses the response.

All recipes use **one synthetic unit of each distinct ingredient per item**, then
the real provider multiplies by the source quantity. Sizes do not change these
test units. Base ingredients are explicit:

| Source drink | Synthetic base |
|---|---|
| Pike Place Roast | Pike roast test base |
| Caffè Latte | Signature Espresso Roast |
| Iced Caramel Macchiato | Signature Espresso Roast |
| Iced Brown Sugar Oatmilk Shaken Espresso | Signature Espresso Roast |
| Chai Tea Latte | Chai test concentrate |
| Cold Brew | Cold brew test base |
| Flat White | Signature Espresso Roast |
| Matcha Tea Latte | Matcha Tea Powder |
| Caramel Frappuccino | Frappuccino test base |
| Vanilla Sweet Cream Cold Brew | Cold brew test base plus Vanilla sweet cream test base |

Chosen milk (unless `None`) adds one base unit. Each selected add-in adds one
add-in unit; Extra Shot is a synthetic add-in in this fixture. Brown Sugar
Oatmilk Shaken Espresso always includes Oatmilk and Brown Sugar Syrup, with
distinct ingredients counted once. Metadata explicitly supplies display names
and base/add-in types, including ingredients absent from the demo catalogue.

Initial stock is 100 on hand, zero reserved per required component except:

| Criterion | Controlled fixture |
|---|---|
| AC-R1 | Store closed; otherwise sufficient stock |
| AC-R2 / AC-R3 | Named missing component has zero on hand |
| AC-R4, order 0028 | Syrup has 3 on hand against demand 4 |
| AC-R4, order 0030 | Syrup has 2 on hand against demand 3 |
| AC-R5 | Named component has one on hand; menu returns available and opaque token; independent competitor holds that unit before target checkout |
| AC-P2, order 0023 | One oat unit; target reserves it first, competitor then fails before target confirms and pays |

In race fixtures with espresso/syrup, espresso begins at on-hand 142/reserved 4
and syrup at on-hand 64/reserved 2, the documented snapshot baselines. The single
last milk/foam unit is synthetic. Competitor recipes explicitly consume only
that one contested component. Refused targets must leave every component count
and the competing reservation's identity, owner and quantities unchanged.

The replay uses real FastAPI gateway, order and stock apps. Controlled HTTP
transports forward request bytes/headers to the real downstream TestClient;
they never return canned stock responses. A recording development payment
adapter returns authorization/capture success without financial requests.
Accepted requests assert hold -> confirm -> authorize -> capture -> accepted,
one capture and queue entry, plus identical idempotent replay without another
effect. Refusals assert the entire frozen contract envelope, separately checked
against CSV message/component/line, zero payment and queue, and no target hold.

`replay-results.csv` records one row per source order including physical CSV
line, expected/actual outcome, HTTP status, component and criterion. The first
scoped run of the new replay test passed all **40/40: 19 accepted, 21 refused**
(`1 passed in 46.38s`); no replay-driven production fix was required.

Run from the repository root:

```powershell
& ../../work/stock-venv/Scripts/python.exe -m pytest tests/test_gateway_replay.py -q
```
