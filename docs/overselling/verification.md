# Overselling verification record

Implementation commit: 58186cf0cc3b2f5676836b2d2838f78aa701f86e.
Passing PR-event run: https://github.com/Falcon-J/first-hill-stock-service/actions/runs/43586308715 .
The downloaded artifacts and JUnit were checked, rather than inferring counts
from the green check alone:

```text
85 passed, 1 warning in 2.70s
144 passed, 1 warning in 6.91s
3 passed in 31.38s
```

The first line is the unchanged frozen contract suite; the second is all normal
repository tests; the third is the real-socket Docker race, complete 40-order
replay and separate stock-outage control. JUnit has no failures, errors or skips.
Later evidence-only commits rerun all checks; the PR links its final-SHA runs.

## Before and after

The new full gateway race initially returned [201, 201]: 1 failed in 15.87s.
The two independent-instance/two-process/crash tests initially reported 3 failed
in 6.51s. After the fix and the reviewed rollback correction:

```text
Gateway race statuses: [201, 409] captures: 1 queue entries: 1 missing: Oatmilk
6 passed in 60.62s (0:01:00)
```

The real local Docker race independently passed in 16.78s, with the losing order
recording zero payment/outbox rows and the winner recording one each; same-key
replays remain stable. See live-race.json. The equivalent CI observation is
ci-live-race.json. Expiry/restart and database-busy behavior have explicit tests.
Review found a SELECT/decode exception could retain the writer lock; its injected
fault failed before the fix, then same/other-worker recovery passed. No material
review finding remains unresolved.

## Complete source replay

live-replay-results.csv is the downloaded **CI Docker/socket** report from the
run above: all 40 rows PASS, 19 accepted and 21 refused. Independently compared
each order ID, outcome, refusal message and missing component against the
unchanged source CSV. evidence-origin.json identifies its source SHA and run.
replay-results.csv is the separate in-process real-provider HTTP report, also
40/40. Recipes/hours/counts are explicitly synthetic historical conditions;
replay-provenance.md documents them. Neither report invents a week-long feed.

MO-250307-0024, physical source line 25, is refused/409/STOCK_CHANGED/Oatmilk,
matching AC-R5. No expected source outcome was changed to obtain this result.
All original contract tests, contracts, spec.md files and CLAUDE.md are unchanged
relative to previous-stage commit fc6aa08.

## Separate outage control

live-stock-outage.json uses MO-250303-0002's valid basket, but labels the stopped
test stock container as a separate AC-E2 fault. The normal CSV expectation stays
accepted. The actual fault response is 503 STOCK_CHECK_UNAVAILABLE with null
line/component, a usable message, and zero payment/outbox rows. It is outside
the 40-row replay table.

## Local Windows diagnostic limit

The local Windows socket replay did not complete successfully: it reached a
gateway 504 on MO-250305-0015. That incomplete diagnostic is retained separately
as local-windows-replay.csv, not presented as the passing 40-order result. A
later original-key probe returned 409 RESERVATION_EXPIRED with zero payment and
queue rows, saved in local-deadline-recovery.json. The clean Linux CI run passed
the same strict tests without changing the three-second budget or assertions.
The green result proves the tested scenarios, not an unbounded latency guarantee
on an overloaded host.

The stock-container crash/expiry rule is the first paragraph of README.md,
beside these artifacts, with the exact storage field and implementation location.
