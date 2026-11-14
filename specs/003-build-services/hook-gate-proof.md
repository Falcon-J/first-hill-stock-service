# Executed quality-gate evidence

The hook settings point Stop to scripts/stop_gate.py and PreToolUse Edit/Write
to scripts/spec_edit_gate.py. Both use the active project Python environment.
The scripts were actually invoked; these are observed exit codes, not proposed
test output. The Claude client interprets exit 2 as a blocking hook result.

1. Injected a separate intentional failing probe alongside the entire unchanged
   test suite, using PYTEST_ADDOPTS. No frozen contract test was edited.
2. Passed the spec-edit hook a PreToolUse Edit payload for
   specs/003-build-services/spec.md. It ran pytest and lint and returned exit 2:

```text
1 failed, 137 passed in 95.04s
All checks passed!
BLOCKED: fix the failing tests/linter before finishing. Do not skip tests or weaken assertions.
BLOCKED SPEC EDIT: specs/003-build-services/spec.md; fix failing tests/lint before changing the specification. Do not weaken contracts to make tests pass.
```

“All checks passed!” on that red run is Ruff's output; the failing pytest result
still made the hook block. The target spec file was not changed by the handler.

3. Corrected the intentionally broken probe and ran the same hook/payload with
   the probe still included. It returned exit 0:

```text
138 passed in 79.48s
All checks passed!
Stop gate passed: pytest and lint are green.
```

4. Ran the normal Stop handler without the separate probe. It returned exit 0:

```text
137 passed in 94.91s
All checks passed!
Stop gate passed: pytest and lint are green.
```

The normal repository contains 137 tests. The extra probe lives outside the
repository and is not a skipped/deleted contract test. All 85 original contract
checks and their OpenAPI sources are unchanged from commit 2dfe62e. Behavioral
gate tests also verify blocking on pytest, lint and runner failures, and allowing
service-code edits needed to repair a red implementation.

Reference: https://code.claude.com/docs/en/hooks#exit-code-2 . A client hook is
an agent feedback gate; the required GitHub check independently prevents merge.
