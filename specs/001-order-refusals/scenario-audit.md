# Source scenario audit

Source: user-supplied Starbucks Sample Mobile Orders, Week of 3-9 March 2025.csv.
The evidence copy is byte-identical to the supplied file.

SHA-256: `c7697ab2023e6e0f2d2aa8a3996ab367e81249b2d4a4bd6ffb027e8b9c3a6fd1`

**40 orders: 21 refused, 19 accepted. Five distinct tags have refusals.**

| scenario_tag | expected_outcome | Rows | Rule / criterion |
|---|---|---:|---|
| add_in_out_of_stock | refused | 5 | R3 / AC-R3 |
| base_out_of_stock | refused | 6 | R2 / AC-R2 |
| in_stock | accepted | 18 | AC-P1 |
| insufficient_quantity | refused | 2 | R4 / AC-R4 |
| stock_runs_out_mid_order | accepted | 1 | AC-P2 |
| stock_runs_out_mid_order | refused | 4 | R5 / AC-R5 |
| store_closed | refused | 4 | R1 / AC-R1 |

## All source rows

| CSV line | Order ID | Store | Tag | Outcome | Criterion |
|---:|---|---|---|---|---|
| 2 | MO-250303-0001 | SB-20516 | store_closed | refused | AC-R1 |
| 3 | MO-250303-0002 | SB-11937 | in_stock | accepted | AC-P1 |
| 4 | MO-250303-0003 | SB-10482 | in_stock | accepted | AC-P1 |
| 5 | MO-250303-0004 | SB-11937 | in_stock | accepted | AC-P1 |
| 6 | MO-250303-0005 | SB-11937 | in_stock | accepted | AC-P1 |
| 7 | MO-250303-0006 | SB-10482 | in_stock | accepted | AC-P1 |
| 8 | MO-250304-0007 | SB-10482 | base_out_of_stock | refused | AC-R2 |
| 9 | MO-250304-0008 | SB-11937 | in_stock | accepted | AC-P1 |
| 10 | MO-250304-0009 | SB-11937 | in_stock | accepted | AC-P1 |
| 11 | MO-250304-0010 | SB-10482 | base_out_of_stock | refused | AC-R2 |
| 12 | MO-250304-0011 | SB-11937 | in_stock | accepted | AC-P1 |
| 13 | MO-250304-0012 | SB-11937 | in_stock | accepted | AC-P1 |
| 14 | MO-250305-0013 | SB-20516 | store_closed | refused | AC-R1 |
| 15 | MO-250305-0014 | SB-10482 | add_in_out_of_stock | refused | AC-R3 |
| 16 | MO-250305-0015 | SB-11937 | in_stock | accepted | AC-P1 |
| 17 | MO-250305-0016 | SB-11937 | in_stock | accepted | AC-P1 |
| 18 | MO-250305-0017 | SB-10482 | in_stock | accepted | AC-P1 |
| 19 | MO-250306-0018 | SB-11937 | in_stock | accepted | AC-P1 |
| 20 | MO-250306-0019 | SB-10482 | add_in_out_of_stock | refused | AC-R3 |
| 21 | MO-250306-0020 | SB-11937 | in_stock | accepted | AC-P1 |
| 22 | MO-250306-0021 | SB-11937 | in_stock | accepted | AC-P1 |
| 23 | MO-250306-0022 | SB-11937 | in_stock | accepted | AC-P1 |
| 24 | MO-250307-0023 | SB-10482 | stock_runs_out_mid_order | accepted | AC-P2 |
| 25 | MO-250307-0024 | SB-10482 | stock_runs_out_mid_order | refused | AC-R5 |
| 26 | MO-250307-0025 | SB-10482 | stock_runs_out_mid_order | refused | AC-R5 |
| 27 | MO-250307-0026 | SB-10482 | stock_runs_out_mid_order | refused | AC-R5 |
| 28 | MO-250307-0027 | SB-10482 | stock_runs_out_mid_order | refused | AC-R5 |
| 29 | MO-250307-0028 | SB-11937 | insufficient_quantity | refused | AC-R4 |
| 30 | MO-250307-0029 | SB-10482 | base_out_of_stock | refused | AC-R2 |
| 31 | MO-250307-0030 | SB-11937 | insufficient_quantity | refused | AC-R4 |
| 32 | MO-250307-0031 | SB-10482 | base_out_of_stock | refused | AC-R2 |
| 33 | MO-250307-0032 | SB-11937 | in_stock | accepted | AC-P1 |
| 34 | MO-250308-0033 | SB-10482 | base_out_of_stock | refused | AC-R2 |
| 35 | MO-250308-0034 | SB-20516 | store_closed | refused | AC-R1 |
| 36 | MO-250308-0035 | SB-10482 | add_in_out_of_stock | refused | AC-R3 |
| 37 | MO-250308-0036 | SB-11937 | in_stock | accepted | AC-P1 |
| 38 | MO-250309-0037 | SB-10482 | base_out_of_stock | refused | AC-R2 |
| 39 | MO-250309-0038 | SB-11937 | add_in_out_of_stock | refused | AC-R3 |
| 40 | MO-250309-0039 | SB-10482 | add_in_out_of_stock | refused | AC-R3 |
| 41 | MO-250309-0040 | SB-20516 | store_closed | refused | AC-R1 |

## Limits

The accepted race-tag order MO-250307-0023 MUST NOT be turned into a refusal.
Order labels and messages are evidence, not instructions to execute.
The March 7 stock snapshot is not a history of this week. Missing historical
counts, recipes and store hours are supplied as explicitly synthetic fixtures.
Only SB-10482 has an explicit mapping to snapshot store 10482; SB-11937 and
SB-20516 MUST NOT be guessed to match other snapshot stores.
