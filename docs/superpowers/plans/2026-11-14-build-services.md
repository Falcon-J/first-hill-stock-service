# Build the approved stock, order and gateway contracts

> **For agentic workers:** Use test-driven development and parallel independent service tasks; integrate and review the whole PR before submission.

**Goal:** Implement the three existing contracts without skipping, deleting or loosening contract assertions, then demonstrate a First Hill oat-milk refusal through a live gateway.
**Architecture:** Stock alone owns snapshot data, recipes, hours and reservation transactions. Order uses HTTP stock/payment adapters; gateway uses HTTP order requests. Each Python/FastAPI service has its own Dockerfile and private state. Existing PR #1 and branch codex/order-service-contracts are reused.
**Spec:** specs/001-order-refusals/spec.md and specs/002-service-contracts/plan.md; contracts/*.openapi.yaml.

## Global constraints
Preserve error/code/message/request_id, exact line/component and /v1 paths. Reserve and confirm allocation before payment. Shared deadline is 3 seconds. Holds expire at 120 seconds; active reservations reduce availability. Never read another service's files/database. Credentials are runtime configuration. Every existing contract must pass unchanged.

## Review focus
Uncertain dependency/payment outcomes, same-key retries and changed payloads, owner isolation, expiry and POS updates, and a real HTTP refusal with no payment/queue side effects.

## Tasks
- [x] Guardrails: add tests for Stop hook/gates and no forbidden cross-service imports, see them fail, implement hooks/rules and spec build notes. Run tests and lint.
- [x] Stock: run existing stock contract cases red; implement services/stock/app.py factory(initial_state, clock, authenticate), snapshot loader, atomic lifecycle and Dockerfile. Re-run stock cases green.
- [x] Order: run existing order contract cases red; implement services/order/app.py factory(stock_client, payment_client, queue, clock, authenticate), durable attempts, HTTP orchestration and Dockerfile. Re-run order cases green.
- [x] Gateway: run existing gateway contract cases red; implement services/gateway/app.py factory(order_client, clock, authenticate), routing/deadlines/envelope and Dockerfile. Re-run gateway cases green.
- [x] Integration: run all tests unchanged; add real HTTP tests and capture a live First Hill oat refusal and call trace. Review whole implementation, fix material findings, run tests/lint, commit and push the same PR, verify latest-SHA Actions green and submit in Zero.

User approved the contract design in the preceding stage and explicitly requested its implementation. No new design approval is required.
