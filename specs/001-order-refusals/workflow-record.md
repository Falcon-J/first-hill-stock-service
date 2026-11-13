# Spec Kit setup and workflow record

## Installation and initialization

Date: 2026-11-14. Existing repository and branch were reused; no application
source, stock test, dependency file, snapshot or CI workflow was changed.

Official source: https://github.com/github/spec-kit

Installed `specify-cli 1.4.1.dev0` from upstream revision
`2ee2b1e8005905db05f5717300a469b3068b908f` using:

```text
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
specify init --here --force --non-interactive --integration claude --script ps
```

The CLI reported `Project ready`, Claude integration installed, PowerShell
scripts/templates installed and the `speckit` workflow installed. These assets
are checked in under `.claude/skills/` and `.specify/`.

## Executed agent workflows

Current Spec Kit uses hyphenated skills `/speckit-constitution`,
`/speckit-specify`, `/speckit-clarify`; these correspond to the requested older
dotted command names. They are agent instructions, not terminal subcommands.

The current Codex agent read and applied the generated SKILL.md instructions.
A separate Claude Code CLI was present but `claude auth status` reported not
logged in; no Claude subprocess or authenticated Claude session is claimed.

1. **Constitution workflow**: Resolved the active constitution template with
   `.specify/scripts/powershell/resolve-template.ps1 constitution-template -Json`.
   Replaced its placeholders with project principles and ratified v1.0.0.
   Removed the temporary Sync Impact Report before committing, as directed by
   the installed workflow. Constitution-only phase did not implement services.
2. **Specify workflow**: Resolved `spec-template -Json` through the same resolver,
   used its section structure, and created `specs/001-order-refusals/spec.md`.
   The brief was: gateway accepts store ID, drinks and add-ins; order service
   checks hours and stock and refuses unfulfillable baskets before payment.
   Prepared the quality checklist and 21 exact refusal cases from the 40-row CSV.
3. **Clarify workflow**: Ran
   `.specify/scripts/powershell/check-prerequisites.ps1 -Json -PathsOnly` and
   confirmed FEATURE_SPEC resolves to this spec. Read constitution/spec, scanned
   ambiguities and recorded the user-directed hold-before-payment answer and
   delegated drafting decisions in `## Clarifications`. No extra questions were
   asked of the user because the user directed the agent to answer them.
   The quality checklist was then reviewed against the clarified spec.

No `.specify/extensions.yml` existed, so no extension hooks were registered.
The machine-local `.specify/feature.json` pointer is ignored by Spec Kit's
managed gitignore. To select this feature in another checkout, set
`SPECIFY_FEATURE_DIRECTORY=specs/001-order-refusals` in that session.

## Clarification coverage

| Area | Result |
|---|---|
| Functional scope, user flow | Clear: full basket, pre-payment refusals |
| Domain and identities | Resolved: explicit IDs, recipes/stock fixture limits |
| Concurrency and lifecycle | Resolved: atomic holds, 120-second TTL, pinned allocation |
| Integrations and errors | Resolved: exact refusals, fail-closed checks, idempotency |
| Completion signals | Clear: rule-to-criterion map and exact 21 case responses |
| Implementation and operations | Deferred to planning: frozen OpenAPI, contract jobs, branch protection, live deployment |

Deferred implementation work does not prevent review of this draft. The next
Spec Kit phase is planning; this change does not run implement or merge service
code. Planned criteria MUST NOT be represented as passing service tests.

## Verification before push

- All 40 source rows accounted for; all 21 refusals map to R1-R5 and AC-R1-AC-R5.
- Every refusal case's input, missing component and exact response message match
  the source CSV; no weak `should` or `try to` wording remains in CLAUDE.md.
- The evidence CSV is byte-identical to the supplied file; a scoped Git attribute
  preserves its original line endings in the repository.
- Existing stock regression suite: `python -m pytest -q` -> `15 passed in 4.20s`.
- Full staged Git diff generated and reviewed; stock code, tests, dependencies,
  stock snapshot and `.github/workflows/tests.yml` have no changes.
- Independent specification review found no important issues and independently
  confirmed all 21 case inputs/messages and the accepted race case.

Order-service/provider contract tests have not run: those services are not yet
implemented. This distinction is mandatory for subsequent status reports.
