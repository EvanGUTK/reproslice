---
name: local-minimizer
status: in-progress
created: 2026-10-19T17:02:49Z
updated: 2026-10-19T17:02:49Z
progress: 0%
prd: .claude/prds/local-minimizer.md
github: https://github.com/EvanGUTK/reproslice/issues/1
---

# Epic: Trustworthy local patch minimizer

Engine owns capture, workspace, oracle, budgets and file reduction; Chief owns CLI, artifacts, demo, skill and docs; Validator reviews independently. Two writer worktrees, one coherent user-testable PR, focused conventional commits, exact-SHA review gate. See ARCHITECTURE.md for API and alternative decisions.

## Dependencies
Engine and CLI implement against a fixed result contract. Final integration requires both, then regression tests, live CLI demonstration, CodeRabbit review and Validator approval. No automatic merge.

## Tasks
- [ ] #2 Isolated engine and regression tests.
- [ ] #3 CLI, artifacts, demo and skill.
- [ ] #4 Engineering documentation and independent verification.

## Budget and rollback
No recurring services. Bounded local command executions. Scope is one first increment. Revert focused commits for implementation rollback; original user source is never reset.
