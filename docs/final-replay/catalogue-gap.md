# Why the original six overlapping source lines returned 422

Baseline inspected: `a7a6fd5`, `services/stock/catalogue.py`. The original demo supported only Caffè Latte, Iced Brown Sugar Oatmilk Shaken Espresso, Matcha Latte and Iced Matcha Latte. Its milk spellings were exactly `Oatmilk`, `Almondmilk`, `2% Milk`, or `None`. Its component IDs were the earlier snapshot IDs such as `oat_milk` and `espresso_signature`. It is explicitly a small demo catalogue, not a complete Starbucks menu.

The new snapshot instead uses `CMP-*` IDs, lowercase component display names and `milk`/`base`/`syrup`/`topping` categories. The new orders also use short milk names and new drink names. No implicit conversion between those catalogues was configured.

| CSV line | Source order/line | Current catalogue result and actual discrepancy |
|---:|---|---|
| 11 | MO-20250310-0209 / 1 | Caffè Latte is supported, but `oat` is not the supported `Oatmilk` spelling. The recipe's `oat_milk`/`espresso_signature` IDs also differ from CMP-104/CMP-201. At STB-10342 the actual oat row is zero on hand and zero reserved; the 422 happens before that valid shortage can produce the requested business refusal. |
| 13 | MO-20250310-0302 / 1 | `Cold Brew` has no demo recipe and `none` differs from `None`. This store has no cold-brew stock component in the supplied snapshot; the presence of a cold-brew row at a different store cannot authorize this order. |
| 14 | MO-20250310-0302 / 2 | `Caffè Americano` has no demo recipe and `none` differs from `None`. Espresso exists at this store as CMP-201 (118 on hand, 22 reserved), but stock cannot silently invent an Americano recipe/unit conversion or substitute the old ID. |
| 24 | MO-20250310-0553 / 1 | `Pink Drink` has no demo recipe and `coconut` has no milk mapping. This store has no coconut milk or strawberry açaí base row. The expected coconut shortage does not supply those counts or recipe inputs. |
| 26 | MO-20250310-0624 / 1 | The shaken-espresso drink exists, but `oat` and lowercase `brown sugar syrup` differ from `Oatmilk` and `Brown Sugar Syrup`. Its espresso/oat/syrup IDs are old-schema IDs. The new store's oat row is genuinely 0/0, but unsupported input prevents the named business refusal. |
| 40 | MO-20250310-1268 / 1 | `Chai Tea Latte` has no demo recipe and `2%` differs from `2% Milk`. The supplied store has CMP-101 milk (64 on hand, 9 reserved) but no chai-concentrate component. Other stores' chai rows cannot fill this gap. |

## Narrow adapter implemented after manager review

The stock owner now registers explicit milk/add-in spellings and maps existing recipe component identities to an unambiguous same-store feed name and compatible category. It does not strip store prefixes, choose a near-match store, create a recipe, change unit demand, overwrite counts, or change the original basket. The old explicit IDs and injected recipe maps retain their authority. Syrup/topping feed categories map to add-in semantics for refusal selection.

Red proof: both real-source oat requests returned 422 rather than 409; the ambiguity test failed because no mapping API existed. The real Ballard caramel-topping request also returned 422. A separate mixed-case duplicate add-in regression exposed silent deduplication, then was fixed by rejecting duplicate canonical spellings. Green proof: all **96 frozen-contract plus final-input/catalogue tests passed in 44.07s**, with Ruff green.

For 0209 and 0624, stock reaches the supplied CMP-104 oat row (0 on hand / 0 reserved), returns **409 BASE_OUT_OF_STOCK / oat milk**, retains no reservation and leaves every stock count unchanged. It preserves the versioned refusal message template. The resubmission corrects the oracle to compare only outcome and missing component, so display wording no longer prevents those two rows from matching. The four other overlapping lines still need missing recipes/component stock. Fresh gateway/CI evidence is reported in the PR.

Decision: KEEP this explicit stock-owned adapter; FIX REQUIRED for the missing catalogue/feed/event inputs. Preserve original source values and frozen contracts. Do not normalize unknown stores or manufacture quantities from expected labels.

Independent review caught a compatibility regression for a known recipe with an absent ingredient: it initially changed UNKNOWN_ITEM into INVALID_ORDER. A failing original-snapshot regression proved it, and unresolved ingredients now retain the existing UNKNOWN_ITEM membership-check path. The six adapter cases and six replay-helper cases pass together (**12 passed in 3.33s**). There is no change to a frozen contract or existing assertion.
