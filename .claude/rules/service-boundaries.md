---
paths:
  - "services/**"
  - "tests/**"
  - "contracts/**"
---

Stock alone MUST load stock data, own hours/counts and publish atomic basket
holds. Order and gateway MUST communicate over HTTP and MUST NOT access another
service's persistence, source data or business implementation.

Payment MUST follow successful full-basket reservation and current-stock
confirmation. Refusals MUST retain the exact code, line, missing component and
usable message. No refusal may create a payment or accepted queue entry.

Do not skip, delete or weaken existing contract tests. Fix implementation
failures. Full pytest and lint MUST pass before finishing; the latest required
contract-tests check MUST pass before merge. Hooks are not a CI bypass.

Each service MUST have its own Dockerfile and private credentials/state. Runtime
secrets MUST NOT enter code, logs, example response evidence or Docker images.
