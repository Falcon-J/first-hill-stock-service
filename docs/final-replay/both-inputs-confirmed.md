# Both named inputs reconfirmed directly in Zero

After the second review I reopened **Held-out Mobile Orders for Final Replay (10 March 2025)** in Zero and downloaded a fresh copy. It is byte-identical to the replay's `orders.csv`: SHA-256 **6c1d31093e11fea50a59b6bd800ca176fdd6dd7d10b509e2e875e9bdc8a1f46d**, 40 source lines. The fresh resource itself references eight stores. This complements the separate direct re-download of the stock resource; neither local copy is the wrong version of the named resource.

| Fresh orders resource IDs | Fresh stock resource IDs |
|---|---|
| STB-10342 | STB-10342 |
| STB-10358 | STB-10518 |
| STB-10417 | STB-10877 |
| STB-10466 | STB-11203 |
| STB-10503 | STB-11456 |
| STB-10529 | — |
| STB-10588 | — |
| STB-10611 | — |

These columns are independent sorted lists, **not mappings**. All IDs already have STB- format. Comparing numeric suffixes still overlaps only at 10342. The missing-store resource discrepancy is real in the published pair. `orders-reconfirmation.json` records the fresh/loaded hashes, both ID sets and every STB-10342 component row.

## Every supplied STB-10342 component

| CSV line | Component ID | Exact component name | On hand | Reserved | Available |
|---:|---|---|---:|---:|---:|
| 2 | CMP-101 | 2% milk | 64 | 9 | 55 |
| 3 | CMP-104 | oat milk | 0 | 0 | 0 |
| 4 | CMP-201 | espresso | 118 | 22 | 96 |
| 5 | CMP-301 | brown sugar syrup | 41 | 6 | 35 |
| 6 | CMP-302 | vanilla syrup | 37 | 4 | 33 |
| 7 | CMP-402 | vanilla sweet cream cold foam | 18 | 3 | 15 |

- **0302, lines 1–2:** Cold Brew and Americano recipes are not registered. Espresso is present for a possible trusted Americano recipe, but cold-brew base is not present at this store. CMP-202 is explicitly cold brew at other stores, not a different name for this store's espresso. The whole basket cannot be accepted by dropping its Cold Brew line.
- **0553, line 1:** Pink Drink needs coconut milk and strawberry açaí base. Neither appears at this store. Coconut milk does not appear anywhere in the supplied snapshot; strawberry açaí base exists only at STB-11203. There is no same-store alias that can resolve these absent counts.
- **1268, line 1:** 2% milk is present, but chai concentrate is not. CMP-203 is explicitly chai concentrate at STB-10877/STB-11456, not a different name for one of these six rows. Milk alone cannot fulfil a Chai Tea Latte.

Decision: request trusted recipe/component data and actual inventory for these cases. Do not reinterpret espresso as cold brew, replace coconut milk with dairy, borrow another store's stock, or manufacture quantities from the expected labels. Those would violate CLAUDE.md and restore the charge-for-unmakeable-drinks bug.

## Neighbouring missing-store audit entry checked against CI

CSV line **12**, **MO-20250310-0251**, item **1**, references **STB-10503**, which is absent from the loaded snapshot. The actual run 43600025036 returned **404 STORE_NOT_FOUND**, message `Store STB-10503 was not found.`, null missing component, **0 payment rows / 0 outbox rows**. The source expects refused_unavailable / almond milk. This is a mismatch, not a valid almond-stock decision. Decision: obtain owner rows or an explicit authoritative mapping; keep 404 until supplied.

The PR already has equivalent explicit store-ID findings for all 34 missing-store rows and separate decisions for the four remaining component/catalogue failures. Both resource files are now directly confirmed; the pending action is a consistent owner-provided dataset, not another filename guess or message-comparator change.
