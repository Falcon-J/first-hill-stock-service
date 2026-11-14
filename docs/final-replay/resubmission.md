# Comparator correction and fresh snapshot confirmation

## Corrected match definition

I mistakenly added exact display-message, source scenario-code, source-selected-line and other fields to the final CSV oracle. The task requires only **expected_outcome** and **expected_missing_component**. The corrected `mismatch_reasons` reads those two expected columns only. Actual outcomes map from the versioned accepted response or a defined stock-unavailability refusal; unknown-store 404, validation 422 and infrastructure errors do not become unavailable-drink matches.

Messages and source tags remain visible diagnostics. The two oat refusals match despite different wording. The two per-line display messages for MO-20250310-0167 are not an oracle contradiction and no longer require a source/contract change. The v1 store-closed sentinel denotes no missing ingredient and maps to the CSV's blank component. No source value or runtime response was rewritten.

Frozen response-schema, correlation, accepted-store identity, coherent refusal details and payment/outbox checks still run independently in `boundary_failures`. A safety violation fails the job even if the two source columns match. Their failures have a separate report field and summary count; they are not hidden extra CSV predicates. The 85 original contract tests remain unchanged.

Red proof: new tests showed the old matcher rejecting a correct outcome/component on different wording and requiring unrelated fields. New tests also reject wrong components and unknown-store errors, and retain independent safety-gate coverage. All 16 final input/oracle/catalogue tests pass (7.18s), with Ruff green. Fresh GitHub source-row totals are linked in the PR.

## Named resource confirmed again

After feedback I reopened **Store Stock Snapshot for Final Replay (10 March 2025, 06:45)** in Zero, observed its 30-row preview and downloaded a fresh copy. It is byte-identical to the loaded CSV: SHA-256 `651326beceb9273dddd0b993bfd6912574efdc1ea52ea3ab5c67d99afeaffeeb`.

The actual resource store IDs are **STB-10342, STB-10518, STB-10877, STB-11203, STB-11456**. The orders instead use **STB-10342, STB-10358, STB-10417, STB-10466, STB-10503, STB-10529, STB-10588, STB-10611**. All use the same STB- format. Comparing numeric suffixes still overlaps only at 10342. This rules out a wrong local filename or prefix-only discrepancy; it does not authorize a new mapping. `snapshot-reconfirmation.json` records both sets, hashes and confirmation time.

The seven missing stores still require corrected owner data. Four overlapping lines still require unsupported/missing catalogue components. Those are genuine remaining row failures; unlike message wording, they cannot be removed from the matcher. Each remaining row must retain an individual audit entry and reason in the PR.

Request routing is still pending: Falcon-J is the tracker, not the platform intake owner. No delivery to a feed/intake owner has occurred. A green 40/40 replay remains the merge requirement; no check will be skipped or changed into a success while source outcomes/components disagree.
