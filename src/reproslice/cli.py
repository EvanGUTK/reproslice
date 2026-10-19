"""Command-line adapter and atomic artifact publication."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from . import __version__
from .engine import ReproSliceError, minimize


def parser() -> argparse.ArgumentParser:
    app = argparse.ArgumentParser(description="Reduce whole-file changes while preserving a chosen check failure.")
    app.add_argument("--version", action="version", version=f"reproslice {__version__}")
    commands = app.add_subparsers(dest="command", required=True)
    run = commands.add_parser("minimize", help="Minimize a tracked Git patch using a trusted local check.")
    run.add_argument("--repo", type=Path, default=Path.cwd(), help="Source repository (default: current directory).")
    run.add_argument("--base", required=True, help="Commit at which the check passes.")
    run.add_argument("--check", required=True, help="Trusted shell command; runs in disposable checkouts, not an OS sandbox.")
    run.add_argument("--signature", required=True, help="Exact, case-sensitive text identifying the target failure (not a regex).")
    run.add_argument("--output", type=Path, required=True, help="New artifact directory outside the source checkout.")
    run.add_argument("--timeout", type=float, default=30.0, help="Seconds per check (default: 30).")
    run.add_argument("--max-checks", type=int, default=100, help="Maximum actual check executions, including verification (default: 100).")
    run.add_argument("--repeats", type=int, default=2, help="Repeated confirmations per candidate (default: 2; minimum: 2).")
    run.add_argument("--json", action="store_true", help="Print the final report as JSON.")
    return app


def source_root(repo: Path) -> Path:
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True, text=True, env=git_env)
    if result.returncode:
        raise ReproSliceError("--repo must identify a non-bare Git working tree")
    return Path(result.stdout.strip()).resolve()


def publish(output: Path, patch: bytes, report: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".reproslice-", dir=output.parent))
    try:
        (temporary / "reduced.patch").write_bytes(patch)
        (temporary / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        guide = (
            "# Reproduce this failure\n\n"
            "Use a fresh checkout of the same repository. Run only trusted code and commands.\n"
            "This patch reproduces a failure; do not apply it to your active working tree.\n\n"
            f"Base commit: `{report['base_commit']}`\n\n"
            "1. Create a disposable checkout at that commit with `git worktree add --detach <new-path> <base-commit>`.\n"
            "2. Apply `reduced.patch` there with `git -C <new-path> apply <absolute-path-to-reduced.patch>`.\n"
            "3. In that checkout, run the check below using the environment/dependencies required by the project.\n\n"
            "```sh\n" + report["check"] + "\n```\n\n"
            "Expected: a normal nonzero exit whose combined output matches the signature in `report.json`.\n"
            "The bundle does not include dependencies, secrets, service state, or a full repository.\n"
        )
        (temporary / "reproduction.md").write_text(guide, encoding="utf-8")
        if output.exists() or output.is_symlink():
            raise ReproSliceError("output already exists; choose a new directory")
        os.rename(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        repo = source_root(args.repo.resolve())
        output = args.output.absolute()
        if output.is_symlink():
            raise ReproSliceError("output must not be a symlink")
        output = output.resolve()
        if output == repo or repo in output.parents:
            raise ReproSliceError("output must be outside the source checkout")
        if output.exists():
            raise ReproSliceError("output already exists; choose a new directory")
        result = minimize(repo, args.base, args.check, args.signature, args.timeout, args.max_checks, args.repeats)
        report = dict(result.report)
        report["artifacts"] = ["reduced.patch", "report.json", "reproduction.md"]
        publish(output, result.patch, report)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=True))
        else:
            print(f"{report['status']}: {len(report['initial_files'])} files -> {len(report['kept_files'])} files")
            print(f"Checks executed: {report['checks_run']} / {args.max_checks}")
            print(f"Verified artifacts: {output}")
        return 0 if report["status"] == "file_minimal" else 3
    except (ReproSliceError, OSError, ValueError) as error:
        print(f"reproslice: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("reproslice: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
