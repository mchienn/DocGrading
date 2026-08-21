## Project-wide agent rules

- Read `docs/requirements/SRS.docx` and `docs/design/DESIGN.md` before making architectural changes.
- Treat the SRS as product requirements and `DESIGN.md` as the approved architecture.
- Report conflicts instead of silently changing requirements or architecture.
- Use Context7 for current third-party API documentation.
- Use CodeGraph before broad changes to inspect dependencies and blast radius.
- Add or update tests for implementation changes.
- Run relevant lint, typecheck, tests and build before reporting completion.
- Never commit secrets or access production resources without explicit approval.

## Orca coordinator rules

These rules apply only when an agent has explicitly been assigned the
Orca coordinator role.

- Use Orca orchestration for tracked multi-agent work.
- Small, focused tasks may be handled directly without creating workers.
- Decompose large objectives into a task DAG.
- Dispatch the minimum useful number of supervised workers.
- Create child worktrees only for independent code changes.
- Avoid overlapping file ownership between parallel workers.
- Define scope, dependencies, acceptance criteria and verification commands
  before dispatch.
- Track worker completion, escalation, questions and retries.
- Integrate completed work in dependency order.
- Ask for approval before changing:
  - product requirements
  - approved architecture
  - database schemas
  - public APIs
  - core dependencies
  - security-sensitive behavior
- Run final integration tests and verify the result against the SRS.

## Orca worker rules

These rules apply to agents dispatched as supervised workers.

- Work only within the assigned task scope.
- Do not expand scope or change architecture independently.
- Do not modify files owned by another parallel task.
- Ask the coordinator when requirements are ambiguous.
- Report files changed, tests run, findings and remaining risks.
- Send exactly one completion report through Orca orchestration.
