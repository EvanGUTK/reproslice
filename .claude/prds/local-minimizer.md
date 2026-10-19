---
name: local-minimizer
description: Reduce a failing Git patch while preserving an explicit failure signature.
status: active
created: 2026-10-19T17:02:49Z
---

# PRD: Local minimizer

## Executive summary
ReproSlice replaces manual elimination of irrelevant code changes with a bounded local check-and-reduce process.

## Problem and users
Developers and coding-agent operators need a portable small reproducer after a large coding session introduces a deterministic regression.

## User stories and acceptance
- As a developer, I supply a passing base and failing check, and obtain a smaller patch matching the same explicit error.
- As an agent operator, I obtain structured status and paths without needing to interpret a conversation.
- As a reviewer, I can apply the patch at the recorded base in a separate checkout and reproduce it.
- As a source owner, my working tree and index remain unchanged, including on failure.

## Requirements
Python CLI; whole-file reduction; signature plus exit-code oracle; repeated base/full/final checks; actual-execution budget; process timeout/output bounds; explicit unsupported or unstable cases; portable patch, JSON report, and guide; runnable demo and skill.

## Success criteria
The controlled three-file demo reduces to one file and the exported patch reproduces the same assertion. Wrong failures, invalid baseline, timeouts, untracked files, and insufficient budget cannot produce misleading success. Local regression checks, CodeRabbit dispositions, and independent Validator verdict precede push.

## Constraints and non-goals
No API or hosted dependencies, no remote CI, no license file. A temporary checkout is not a sandbox. No globally smallest claim. No transcript import, MCP, plugin, GUI, automatic merge, or model-quality evaluation in this increment.

## Dependencies
Python >=3.11, Git, POSIX process management, and user-provided trusted check environment. Tests and examples use the standard library.
