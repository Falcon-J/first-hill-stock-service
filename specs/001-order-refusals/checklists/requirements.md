# Specification Quality Checklist: Order refusals

**Purpose**: Check this draft before implementation planning.
**Created**: 2026-11-14
**Feature**: [Order specification](../spec.md)

## Content quality

- [x] User value and no-payment-before-fulfilment intent are explicit.
- [x] Mandatory user scenarios, requirements, entities, success criteria and assumptions exist.
- [x] No service implementation is included or claimed complete.
- [x] Technology constraints are limited to the user's Python/FastAPI/container requirements.

## Requirement completeness

- [x] All 40 source orders are accounted for: 21 refused, 19 accepted.
- [x] All five refused tags have exactly one firm CLAUDE.md refusal rule.
- [x] Every refusal rule maps to an acceptance criterion with input and exact refusal.
- [x] Every refused source order has an exact expected HTTP status and JSON body.
- [x] Expected messages match the source CSV verbatim.
- [x] All business refusals prohibit payment, partial holds and queue entries.
- [x] Stock is explicitly reserved before payment in Clarifications and requirements.
- [x] Accepted race-tag order remains accepted when its hold succeeds.
- [x] Stock aggregation, concurrent holds, expiry and uncertain replies are covered.
- [x] Store-ID mismatch and limits of historical snapshot evidence are explicit.
- [x] No unresolved clarification markers or weak normative wording remain.

## Readiness boundaries

- [x] Fixed OpenAPI, no shared database and contract-test merge gate are mandatory.
- [x] Test-first work and external secrets are constitutional requirements.
- [x] Executed stock tests are distinguished from future order contract tests.
- [x] Stock code, tests, dependencies, snapshot and workflow remain unchanged.

## Notes

This checklist validates the **draft specification**, not an implemented order
service. Exact response/status examples are intentionally included at the user's
request, overriding the generic upstream checklist's API-free-spec preference.
Frozen OpenAPI files, contract-test jobs, branch protection and order-service
implementation remain future work. They cannot be marked passed from this draft.
