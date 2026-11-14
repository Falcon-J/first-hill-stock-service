# Mobile Ordering Constitution

## Core Principles

### I. Confirm ability to fulfil before taking money

Every accepted order MUST have an authoritative open-store result and an atomic
reservation covering every required component, every line and all quantities.
The reservation MUST precede every payment-provider request. A read-only stock
check MUST NOT be treated as a hold. Refused orders MUST cause no payment or
barista queue entry. Failed checks MUST fail closed with a defined refusal.

### II. Python/FastAPI services with independent ownership

The gateway, order service and stock service MUST use Python and FastAPI.
Each service MUST have one separately built, versioned and deployed container
image and its own data ownership. There MUST NOT be a shared service database,
shared credentials or direct cross-service persistence access. Communication
MUST use explicit API contracts; stock holds MUST be owned by the stock service.
These are future implementation constraints, not a claim containers exist now.
Store stock is the sole authority for quantity_on_hand, reserved_quantity,
store_open, recipe-based fulfilability and reservations. No other service may
read replicas/reporting copies or retain stock/open-state caches as truth.
Confirmation MUST recheck current inventory and hours against POS/feed changes
before payment; an earlier successful hold/read is not current acceptance proof.

### III. Contract-first compatibility

Every service boundary MUST have a checked-in OpenAPI contract frozen before
implementation. Providers and consumers MUST agree on request/response fields,
status codes, error codes, units, identifiers and idempotency. Breaking changes
MUST use a new API version. A service MUST NOT silently reinterpret a store ID,
replace a requested ingredient or accept a partial basket.
Public routes MUST use /v1 and retain the legacy error/code/message/request_id
envelope, with additive machine-readable line/component details. Gateway has
no order or stock business logic. All synchronous order work shares a 3-second
deadline; retries cannot reset it. Business refusals MUST NOT use 502/503/504.

### IV. Tests first; evidence gates merges

Write and run a failing test before implementing behavior. Every refusal rule
MUST map to an acceptance criterion specifying input, authoritative precondition,
exact refusal and prohibited side effects. Service pytest suites and both sides
of every affected contract test MUST pass for the proposed merge commit. Missing
or skipped contract tests MUST block merge. Stock-only pytest success MUST NOT
be presented as passing order-service tests. Configure required CI checks and
branch protection before merging future implementation.

### V. No secrets in source

Credentials, signing keys, payment tokens and secrets MUST NOT be hard-coded,
committed, embedded in images or exposed in logs/test evidence. Inject secrets
at runtime from environment variables or a secret manager. Examples MUST use
non-secret placeholders. Each service MUST receive only its own credentials.

## Additional Constraints

Stock MUST remain available only after subtracting reserved quantities. Exact
store/component identifiers MUST be preserved. Historical sample labels MUST NOT
be treated as live inventory or as client authorization to accept an order.
Acceptance criteria MUST explicitly separate source-recorded facts from designed
test preconditions. A menu-time stock read is evidence of availability at that
read, not a reservation or permission to take payment at checkout.
Reserve-before-payment ordering MUST be asserted for the same order and store
used in each accepted race criterion; another store's successful-order test
MUST NOT substitute for that assertion.
An atomic basket reservation MUST publish all required component holds or none.
On failure, tentative changes MUST be discarded without altering another
order's committed reservations; compensating release of published partial
holds MUST NOT be described as an atomic full-basket reservation.
Rollback acceptance criteria MUST name numeric committed-state baselines and
post-failure totals, and distinguish source values from synthetic overrides.
Reviewers MUST be able to identify those assertions directly within the
criterion, rather than inferring them from a narrative or an external message.

## Development Workflow and Quality Gates

Use Spec Kit constitution -> specify -> clarify before implementation planning.
Keep requirements, decisions and refusal mappings versioned with the code.
The order service MUST enforce atomic full-basket holds before payment, bounded
hold lifetimes, idempotent payment/confirmation and release on failure. A
dependency timeout or malformed reply MUST block payment and acceptance.

Review every change against this constitution, CLAUDE.md and the feature spec.
For specification-only changes, inspect the full diff and verify production
code is unchanged. Planned acceptance criteria MUST be identified as planned,
not reported as executed service tests.

## Governance

This constitution governs all services and overrides conflicting local design
choices. Amendments MUST state the rationale, affected contracts/tests and
migration impact in a reviewed commit. Use semantic versions: major for removed
or incompatible principles; minor for new principles; patch for clarifications.
Any exception MUST be explicit, reviewed and recorded with an expiry and owner;
no exception can permit payment before a confirmed stock reservation.

**Version**: 1.1.0 | **Ratified**: 2026-11-14 | **Last Amended**: 2026-11-14
