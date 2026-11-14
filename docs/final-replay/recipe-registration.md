# Recipe registration correction

The requested correction separates known drink recipes from missing stock rows.
Stock remains the sole catalogue and inventory owner. No contract, source CSV,
store alias, inventory count or expected outcome is changed.

## Explicit implementation assumption

The existing catalogue uses one demo stock unit per required component per
drink, for each supported size. The four new registrations extend that same
convention; they are not verified commercial Starbucks quantities. Recipe
validation with an authoritative size/unit feed remains necessary before real
deployment. These definitions are independent of the CSV expected labels.

| Drink | Required demo components per item |
|---|---|
| Cold Brew | cold brew: 1 |
| Caffè Americano | espresso: 1 |
| Chai Tea Latte | chai concentrate: 1, plus chosen milk: 1 |
| Pink Drink | strawberry açaí base: 1, coconut milk: 1 |

Quantity multiplies demand through the existing basket aggregation. Pink Drink
retains its required coconut milk even if a client submits milk `none`.
Unique same-store name/type resolution maps these identities to real feed IDs.
Missing rows retain the frozen `422 UNKNOWN_ITEM` behavior; they are not zero
stock. A registered recipe never creates a stock row.

## Test design and red proof

`tests/test_final_recipe_registry.py` first produced **11 failures**, all from
the missing registrations / resulting INVALID_ORDER responses. The tests cover
the four exact held-out lines; all three original whole baskets against the
unchanged snapshot; allocation and quantity multiplication with explicitly
synthetic supplemental stock; and coconut omission prevention.

Synthetic rows exist only inside test functions, with `synthetic-*` IDs and ten
units each. They are not final replay data and their successful reservations do
not establish a real 40/40 result. The unchanged real-source tests require no
inventory mutation or retained hold when a component is absent.

## Remaining source requirements

- Seven absent stores still affect 34 lines: STB-10358, STB-10417, STB-10466,
  STB-10503, STB-10529, STB-10588 and STB-10611. Supply their real rows or an
  authoritative mapping, hours and component inventories.
- STB-10342 still lacks cold brew for MO-20250310-0302; coconut milk and
  strawberry açaí base for MO-20250310-0553; and chai concentrate for
  MO-20250310-1268. Espresso and 2% milk already exist at this store.
- Other held-out drinks at absent stores require complete stock-owned recipe
  coverage as well; fixing these four registrations is not full-menu coverage.
- A start-of-day snapshot does not record mid-order depletion. Authoritative
  stock-change inputs and their timing are needed to reproduce those scenarios.
- Every supplement requires provenance and SHA-256; expected answers remain fixed.

The final gateway replay must still run all 40 original lines as 28 baskets,
without synthetic stock, inferred aliases or expected-label-driven decisions.

## Observed local gateway result and manager review

The fresh three-container replay completed 28 baskets, matched 2/40 source
lines, and reported 38 mismatches with zero independent boundary failures.
All 28 attempts left zero payment/outbox rows. The four affected lines now
return `422 UNKNOWN_ITEM`, `Recipe component is not in this store catalogue.`
They no longer fail drink registration. The unchanged source still cannot
support a complete hold. `recipe-fix-local-evidence.json` contains the raw
three affected basket responses, counts and source hashes; it is local evidence,
not a GitHub Actions artifact.

Amara reviewed this in Zero and counted the four recipe-registry failures as
closed. She confirmed no additional stock resource is available to her and
identified the missing store rows/hours or authoritative mapping, the four
STB-10342 ingredient counts, and timed feed changes. The PR remains draft and
the real held-out replay remains red. Four lines across three baskets remain
mismatched at this known store; the Americano belongs to the rejected whole
Cold Brew basket and is not submitted separately to manufacture a pass.

Local verification also exposed timing failures in existing tests. One full
Windows run reported 176 passed and a gateway race deadline failure during a
Docker rebuild; the isolated unchanged race subsequently passed. A second full
run reported 176 passed and a deadline failure in one prior-sample replay row.
These are not recipe-registry assertion failures, but they are recorded rather
than counted as a passing full suite. No deadlines or assertions were relaxed.
The current commit's GitHub full-suite result must be inspected independently.
