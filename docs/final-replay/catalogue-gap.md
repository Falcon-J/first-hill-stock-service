# Why the six overlapping source lines returned 422

Provider file inspected: `services/stock/catalogue.py`. The demo supports only Caffè Latte, Iced Brown Sugar Oatmilk Shaken Espresso, Matcha Latte and Iced Matcha Latte. Its milk spellings are exactly `Oatmilk`, `Almondmilk`, `2% Milk`, or `None`. Its component IDs are the earlier snapshot IDs such as `oat_milk` and `espresso_signature`. It is explicitly a small demo catalogue, not a complete Starbucks menu.

The new snapshot instead uses `CMP-*` IDs, lowercase component display names and `milk`/`base`/`syrup`/`topping` categories. The new orders also use short milk names and new drink names. No implicit conversion between those catalogues was configured.

| CSV line | Source order/line | Current catalogue result and actual discrepancy |
|---:|---|---|
| 11 | MO-20250310-0209 / 1 | Caffè Latte is supported, but `oat` is not the supported `Oatmilk` spelling. The recipe's `oat_milk`/`espresso_signature` IDs also differ from CMP-104/CMP-201. At STB-10342 the actual oat row is zero on hand and zero reserved; the 422 happens before that valid shortage can produce the requested business refusal. |
| 13 | MO-20250310-0302 / 1 | `Cold Brew` has no demo recipe and `none` differs from `None`. This store has no cold-brew stock component in the supplied snapshot; the presence of a cold-brew row at a different store cannot authorize this order. |
| 14 | MO-20250310-0302 / 2 | `Caffè Americano` has no demo recipe and `none` differs from `None`. Espresso exists at this store as CMP-201 (118 on hand, 22 reserved), but stock cannot silently invent an Americano recipe/unit conversion or substitute the old ID. |
| 24 | MO-20250310-0553 / 1 | `Pink Drink` has no demo recipe and `coconut` has no milk mapping. This store has no coconut milk or strawberry açaí base row. The expected coconut shortage does not supply those counts or recipe inputs. |
| 26 | MO-20250310-0624 / 1 | The shaken-espresso drink exists, but `oat` and lowercase `brown sugar syrup` differ from `Oatmilk` and `Brown Sugar Syrup`. Its espresso/oat/syrup IDs are old-schema IDs. The new store's oat row is genuinely 0/0, but unsupported input prevents the named business refusal. |
| 40 | MO-20250310-1268 / 1 | `Chai Tea Latte` has no demo recipe and `2%` differs from `2% Milk`. The supplied store has CMP-101 milk (64 on hand, 9 reserved) but no chai-concentrate component. Other stores' chai rows cannot fill this gap. |

Decision: fix these through an explicit inventory-owned, authoritative catalogue/feed integration, with tests for spellings, component IDs, component categories and recipe units. Preserve the caller's original basket and the frozen API. Do not solve the missing feed by normalizing unknown stores or creating quantities from expected labels. The current errors are fail-closed behavior, not successful final acceptance criteria.
