# Build verification

Implementation commit: b9c78971919e214a5ec7e819f7483895677bf728.
GitHub PR-event run: https://github.com/Falcon-J/first-hill-stock-service/actions/runs/43579040115 .
It passed frozen provider contracts, full regression suite, lint, building and
starting all three Compose containers, the actual gateway refusal and artifact
publication. JUnit downloaded from that run reports 85 tests, zero failures,
zero errors and zero skips. The full suite reports 137 passed. The original
stock-only check also passes. Subsequent evidence-only commits run the same
workflow; the PR description links checks attached to the final SHA.

The complete original tests/contracts directory and three OpenAPI YAML sources
are unchanged from 2dfe62e. All 59 previously missing-provider failures are now
passing real provider checks. Added regression tests cover owner isolation,
restart idempotency, menu/POS stock changes, alias handling across all three
providers, and recovery after a failed authorization connection.

Fresh review found two material issues: canonical stock IDs did not match the
submitted alias at the order boundary; and authorization could remain pending
after a connection failed before payment creation. Both received failing
regression tests before fixes and then passed. No material review finding was
left unresolved. The known historical-catalogue, one-stock-worker and explicit
development-payment limits are documented in service READMEs and quickstart.

The live CI Compose request/response is preserved in
evidence/ci-gateway-refusal.json and its container POST receipt logs in
evidence/ci-http-calls.txt. These are executed observations, not mock-server
answers. The separate local observation is in evidence/gateway-oat-refusal.json.
The stock loader uses the original zero oat row; no synthetic race unit is
inserted into the runtime seed. No authorization, capture or queue call occurs
on this refusal. The HTTP-chain regression also explicitly asserts zero payment
calls and an otherwise available almond latte follows the payment sequence once.

See hook-gate-proof.md for the actual blocking exit 2 and restored exit 0.

Local final Compose run: all three containers report running/healthy. The saved
request ID is demo-firsthill-311ce91c-28e3-4fd1-b659-cbae665ee600. The public
gateway returned 409 BASE_OUT_OF_STOCK, line 1, Oatmilk. Local receipt logs show
order -> stock POST /v1/reservations and gateway -> order POST /v1/orders, both
409. An inspection inside the order owner's container confirms zero development
payment rows and zero queue outbox rows. See evidence/container-health.txt,
evidence/local-http-calls.txt and evidence/order-side-effects.json. An earlier
request during container recreation received the expected infrastructure 502;
the saved refusal was queried after the final stack became healthy.
