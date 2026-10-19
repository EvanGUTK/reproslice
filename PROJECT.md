# ReproSlice

## Problem
Coding sessions can leave a large patch and a failing check. Reconstructing the few changes needed to reproduce that failure costs developer and agent time.

## Approved first increment
A local Python CLI reduces whole-file changes against an explicit Git commit, keeping a candidate only when a trusted check exits unsuccessfully with the user's chosen failure signature. Deliver a reproducible patch, structured report, runnable demonstration, and an agent skill. No model or cloud service is required.

Journey: choose a passing base → reproduce the failure → remove irrelevant file changes → verify the result → apply the smaller patch in a new checkout.

## Boundaries
This increment reduces code changes, not prompts, model behavior, tool-call histories, or arbitrary agent policies. No transcript importer, MCP server, plugin packaging, web UI, native Windows support, remote CI, automatic merge, or license file. Public availability does not grant an open source license.

## Success
- The bundled example reduces three changed files to the single file needed for the same assertion failure.
- A passing baseline, repeated full-patch failure, and final repeated reproduction are mandatory.
- Reports distinguish file-level 1-minimality, budget exhaustion, and reproduction errors.
- Tests independently exercise wrong failure identity, workspace preservation, and command limits.
- Independent Validator and CodeRabbit review precede a topic-branch push; the user approves merges.

## Budget and delivery
No paid APIs or recurring services. CPU time is bounded by explicit command-count and per-command time limits. One user-testable increment is authorized; later increments require feedback. Achievement progress comes from meaningful merged PRs and correct attribution, not a predetermined volume of trivial changes.

## Repository discovery
This is a fresh repository. PROJECT.md, ARCHITECTURE.md, and TASKS.md did not exist at discovery; these documents establish the approved contracts rather than infer project facts.
