<div align="center">

# ReproSlice

**A smaller failing patch. A command to reproduce it.**

Local patch reduction for developers and coding agents.

[Quick start](#quick-start) · [Guarantees](#what-the-result-means) · [Design](ARCHITECTURE.md) · [Roadmap](TASKS.md)

</div>

---

A coding session leaves three changed files and a failing test. Only one change causes the failure. ReproSlice checks smaller combinations and exports a patch that still triggers the error you chose.

You provide a passing Git base, a trusted check command, and a failure signature. ReproSlice does the repeated elimination work in disposable checkouts.

```text
Source patch             Candidate checks          Reproducer
calculator.py ─┐                                  calculator.py
messages.py ───┼──────► remove / run / confirm ──► reduced.patch
notes.txt ─────┘                                  report.json
                                                 reproduction.md
```

**Status:** first increment. Whole-file reduction. No model, API key, cloud account, or runtime Python dependencies. Linux/WSL is the initial verification target; native Windows is unsupported.

## Quick start

Requires Python 3.11+, Git, and a POSIX environment. Run from a clone of this repository:

```sh
git clone https://github.com/EvanGUTK/reproslice.git
cd reproslice
PYTHONPATH=src python3 -m reproslice --help
```

Try the included example. Use new paths for both directories:

```sh
python3 examples/make_demo.py /tmp/reproslice-demo

PYTHONPATH=src python3 -m reproslice minimize \
  --repo /tmp/reproslice-demo \
  --base HEAD \
  --check 'python3 check.py' \
  --signature 'AssertionError: reproslice-demo: expected total 42' \
  --output /tmp/reproslice-result
```

The bundled demo was verified through the installed CLI: three changed files reduced to one in 16 check executions. Its report includes:

```json
{
  "status": "file_minimal",
  "kept_files": ["calculator.py"],
  "dropped_files": ["messages.py", "notes.txt"],
  "checks_run": 16
}
```

This is a controlled example, not a benchmark of arbitrary repositories.

To install the CLI into your own virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/reproslice --help
```

The project is not published to PyPI. Installation above uses this checkout. Some Linux distributions package `venv` and `pip` separately; the source invocation above needs neither.

## Use it on your project

```sh
reproslice minimize \
  --repo /path/to/project \
  --base <passing-commit> \
  --check 'your trusted test command' \
  --signature 'specific assertion or error text' \
  --output /path/outside/project/reproducer \
  --max-checks 100 \
  --timeout 30 \
  --json
```

The output directory must be new and outside the source checkout. Stage intended new files first: untracked input is rejected to avoid silently omitting it. The check must already run and pass at the base; a newly added test that does not exist there needs a separate stable test harness. Dependencies and services needed by the check must already be available to disposable checkouts. Use a command that tests the candidate, not an editable installation or absolute import pointing back to the original source.

| Artifact | Purpose |
|---|---|
| `reduced.patch` | Remaining whole-file changes, applicable to the recorded base. |
| `report.json` | Failure identifier, base, source fingerprint, retained paths, status, and check count. |
| `reproduction.md` | Steps for applying the patch in a fresh checkout and running the check. |

Original source files and the index stay in place. Generated artifacts are published together after successful verification. Nothing is automatically uploaded, committed, pushed, or merged.

## What the result means

ReproSlice requires a passing base, repeated reproduction from the full patch, and final repeated reproduction from the reduced patch. A target failure must exit with a code from 1 through 127 **and** have output matching your regex. Higher exit codes are conservatively treated as abnormal. An unrelated error or timeout is not the target failure.

| Exit | Meaning |
|---|---|
| `0` | Verified result, file-level 1-minimal: no single remaining file change could be removed under the configured check. |
| `3` | Verified result, execution budget exhausted: no minimality claim. |
| `2` | Invalid input, setup, or reproduction failure. No successful artifact bundle is published. |
| `130` | Interrupted by the user. |

**1-minimal is not globally smallest.** Files are the reduction unit in this release. A matching signature is a practical failure identifier, not proof of the same root cause. Repetition catches some instability; it cannot prove a test will always behave the same way.

`--max-checks` includes baseline and verification executions. `--timeout` bounds each check, not total wall time. Git operations, environment setup, and process cleanup also take time.

## Trust and isolation

Disposable checkouts isolate repository files. **They are not a security sandbox.** The supplied command and checked-out code run with your user permissions and may access the network, credentials, services, or absolute paths. Use trusted code and a trusted check. Do not execute commands copied from an untrusted agent transcript.

The bundle is a patch and instructions, not a hermetic environment. It does not package dependencies or external service state. Reports include the supplied command and paths; review artifacts before sharing them.

## How it fits agent workflows

Use ReproSlice after an agent introduces a reproducible regression and before asking another agent to debug the entire patch. Hand off the reduced patch, base, signature, and reproduction guide together.

The repository includes a narrow [agent skill](.agents/skills/reproslice/SKILL.md). The reduction engine is executable code; the skill explains when and how to invoke it. MCP and transcript adapters are future increments, not current capabilities.

## Verify locally

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

The example and focused regression tests exercise failure identity, source preservation, execution limits, and artifact reproduction. See [ARCHITECTURE.md](ARCHITECTURE.md) for the engine contract and [TASKS.md](TASKS.md) for linked issues. This repository uses local checks and independent review; GitHub Actions is disabled.

## Scope and prior work

ReproSlice applies established delta-debugging ideas to a practical coding handoff. It does not claim to invent patch minimization. [TRIM](https://arxiv.org/abs/2607.18161) studies removal of unnecessary changes from successful agent patches; [Samsara](https://github.com/Maher-Reven/samsara) explores agent effect replay and fault minimization. ReproSlice's first increment targets a reproducible failing Git patch with an explicit user-defined check.

## Contributing and licensing

Start with a concrete [issue](https://github.com/EvanGUTK/reproslice/issues) and follow [CONTRIBUTING.md](CONTRIBUTING.md). Small, coherent PRs should carry reproduction evidence and accurate attribution.

No license has been granted for this repository. The source is publicly visible; public visibility alone does not make it open source.
