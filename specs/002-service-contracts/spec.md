# Stock-owned service boundaries

Input: the existing order refusal specification in ../001-order-refusals/spec.md
and Service Boundary Review: Asks from the Owning Teams (7 March 2025), read in
Zero resources. The order sample and snapshot remain immutable evidence.

Draft a reviewable HTTP boundary for stock, order and gateway. Stock alone owns
counts, hours, recipes, fulfilability and atomic reservations. Order coordinates
durable attempts and payment only after current-stock confirmation. Gateway
routes /v1 without deciding acceptance. Preserve error.code, error.message and
request_id; add line/component detail. Enforce a shared three-second deadline.

Deliver one standalone OpenAPI contract per service, a plan, executable pytest
contract checks, a criterion-to-test mapping, and GitHub Actions on push and PR.
Provider tests must fail visibly until the services exist; document validation
and existing snapshot tests must pass. Submit a draft PR, without implementing
the new services or merging. See plan.md for decisions and coverage.md for the
original acceptance criteria and their exact pytest tests.
