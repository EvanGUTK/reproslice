"""Deterministic, whole-file patch reduction for reproducible failures."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time


class ReproSliceError(Exception):
    """Raised when a patch cannot safely be reduced or validated."""


@dataclass
class ReductionResult:
    patch: bytes
    report: dict


_MAX_OUTPUT_BYTES = 1024 * 1024
_GIT_TIMEOUT = 30.0


def _git(repo: Path, *args: str, input: bytes | None = None) -> bytes:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        result = subprocess.run(
            ["git", "-C", os.fspath(repo), "-c", "core.hooksPath=/dev/null", *args], input=input,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=_GIT_TIMEOUT,
            check=False, env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReproSliceError(f"git {' '.join(args[:2])} failed: {exc}") from exc
    if result.returncode:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise ReproSliceError(f"git {' '.join(args[:2])} failed: {message or result.returncode}")
    return result.stdout


def _safe_repo(repo: Path) -> Path:
    try:
        root = Path(os.fsdecode(_git(repo, "rev-parse", "--show-toplevel").strip())).resolve()
    except ReproSliceError:
        raise
    if not root.is_dir():
        raise ReproSliceError("repository root is unavailable")
    git_dir = Path(os.fsdecode(_git(root, "rev-parse", "--absolute-git-dir").strip()))
    if _git(root, "ls-files", "-u", "-z"):
        raise ReproSliceError("repository has unmerged index entries; resolve them first")
    git_dir = git_dir.resolve()
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-apply", "rebase-merge"):
        if (git_dir / marker).exists():
            raise ReproSliceError(f"repository operation in progress ({marker}); finish or abort it first")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked:
        names = [os.fsdecode(p) for p in untracked.split(b"\0") if p]
        raise ReproSliceError("untracked nonignored input is present: " + ", ".join(names[:5]))
    return root


def _validate_path(raw: bytes) -> str:
    path = os.fsdecode(raw)
    posix = PurePosixPath(path)
    if not path or "\0" in path or posix.is_absolute() or "\\" in path:
        raise ReproSliceError(f"unsafe changed path: {path!r}")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ReproSliceError(f"unsafe changed path: {path!r}")
    if path.startswith("-"):
        raise ReproSliceError(f"unsafe changed path: {path!r}")
    return path


def _run_command(repo: Path, base: str, patch: bytes, command: str, timeout: float) -> tuple[str, str]:
    """Run once in a new disposable worktree; return (outcome, detail)."""
    temp_root = Path(tempfile.mkdtemp(prefix="reproslice-run-"))
    worktree = temp_root / "tree"
    try:
        _git(repo, "worktree", "add", "--detach", "--force", os.fspath(worktree), base)
        if patch:
            _git(worktree, "apply", "--binary", "--whitespace=nowarn", "-", input=patch)
        process = subprocess.Popen(
            command, cwd=worktree, shell=True, executable="/bin/sh",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        )
        output = bytearray()
        output_lock = threading.Lock()
        overflow = threading.Event()

        def drain(stream) -> None:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    return
                with output_lock:
                    room = _MAX_OUTPUT_BYTES - len(output)
                    if room > 0:
                        output.extend(chunk[:room])
                    if len(chunk) > room:
                        overflow.set()
                if overflow.is_set():
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

        readers = [threading.Thread(target=drain, args=(pipe,), daemon=True)
                   for pipe in (process.stdout, process.stderr)]
        for reader in readers:
            reader.start()
        start = time.monotonic()
        timed_out = False
        while process.poll() is None:
            if overflow.is_set():
                break
            if time.monotonic() - start >= timeout:
                timed_out = True
                break
            time.sleep(min(0.02, max(0.001, timeout / 100)))
        if timed_out or overflow.is_set():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        for reader in readers:
            reader.join(timeout=2)
        for pipe in (process.stdout, process.stderr):
            pipe.close()
        text = output.decode("utf-8", "replace")
        if timed_out:
            return "inconclusive", f"command timed out after {timeout:g}s"
        if overflow.is_set():
            return "inconclusive", f"command output exceeded {_MAX_OUTPUT_BYTES} bytes"
        if process.returncode is None or process.returncode < 0 or process.returncode >= 128:
            return "inconclusive", f"command exited abnormally ({process.returncode})"
        return ("exit-zero" if process.returncode == 0 else "exit-nonzero"), text
    except ReproSliceError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        return "inconclusive", f"could not run candidate: {exc}"
    finally:
        if worktree.exists():
            try:
                _git(repo, "worktree", "remove", "--force", os.fspath(worktree))
            except ReproSliceError:
                # Git worktree removal is the primary cleanup; rmtree does not
                # follow symlinked entries and only targets our private temp dir.
                shutil.rmtree(temp_root, ignore_errors=True)
        else:
            shutil.rmtree(temp_root, ignore_errors=True)
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)


def minimize(
    repo: Path,
    base: str,
    check: str,
    signature: str,
    timeout: float = 30.0,
    max_checks: int = 100,
    repeats: int = 2,
) -> ReductionResult:
    """Reduce tracked changes by whole-file ddmin and verify single deletions.

    ``check`` is trusted shell input and runs in disposable worktrees; it is not
    an operating-system sandbox. Candidate checks are bounded by ``timeout``
    and one MiB of captured output per execution.
    """
    if not isinstance(check, str) or not check.strip():
        raise ReproSliceError("check command must be a nonempty string")
    if not isinstance(signature, str) or not signature:
        raise ReproSliceError("signature regex must be nonempty")
    try:
        matcher = re.compile(signature)
    except re.error as exc:
        raise ReproSliceError(f"invalid signature regex: {exc}") from exc
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ReproSliceError("timeout must be a positive number")
    if not math.isfinite(float(timeout)):
        raise ReproSliceError("timeout must be finite")
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
        raise ReproSliceError("repeats must be a positive integer")
    if not isinstance(max_checks, int) or isinstance(max_checks, bool) or max_checks < 3 * repeats:
        raise ReproSliceError(f"max_checks must be at least {3 * repeats} to check base, patch, and final confirmation")

    if not isinstance(base, str) or not base or base.startswith("-") or "\0" in base:
        raise ReproSliceError("base must be a nonempty commit reference")
    root = _safe_repo(Path(repo))
    resolved_base = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
    names_raw = _git(root, "diff", "--name-only", "-z", "--no-renames", resolved_base, "--")
    files = [_validate_path(part) for part in names_raw.split(b"\0") if part]
    original_patch = _git(root, "diff", "--binary", "--full-index", "--no-renames", resolved_base, "--")
    fingerprint = hashlib.sha256(original_patch).hexdigest()
    checks_run = 0

    def make_patch(selected: list[str]) -> bytes:
        if not selected:
            return b""
        literal_paths = [f":(literal){path}" for path in selected]
        return _git(root, "diff", "--binary", "--full-index", "--no-renames", resolved_base, "--", *literal_paths)

    def evaluate(patch: bytes, expected: str) -> bool:
        nonlocal checks_run
        outcomes: list[str] = []
        for _ in range(repeats):
            outcome, detail = _run_command(root, resolved_base, patch, check, float(timeout))
            checks_run += 1
            if outcome == "inconclusive":
                raise ReproSliceError(f"candidate check was inconclusive: {detail}")
            target = outcome == "exit-nonzero" and matcher.search(detail) is not None
            if outcome == "exit-nonzero" and not target:
                raise ReproSliceError("candidate had a nonzero exit without the requested signature; treating it as an incidental failure")
            outcomes.append("target" if target else "pass")
        if len(set(outcomes)) != 1:
            raise ReproSliceError("candidate result was inconsistent across repeats")
        actual = outcomes[0]
        if expected == "target" and actual != "target":
            return False
        if expected == "pass" and actual != "pass":
            return False
        return True

    if not evaluate(b"", "pass"):
        raise ReproSliceError("base check did not pass on every repeat; fix the check or choose another base")
    if not evaluate(original_patch, "target"):
        raise ReproSliceError("full tracked patch did not reproduce the requested failure on every repeat")

    kept = list(files)
    budget_exhausted = False

    def candidate_preserves(candidate: list[str]) -> bool | None:
        nonlocal budget_exhausted
        if checks_run + 2 * repeats > max_checks:
            budget_exhausted = True
            return None
        return evaluate(make_patch(candidate), "target")

    # Classic complement-based ddmin, with deterministic path ordering.
    granularity = 2
    while len(kept) >= 2:
        chunk_size = (len(kept) + granularity - 1) // granularity
        reduced = False
        for offset in range(0, len(kept), chunk_size):
            candidate = kept[:offset] + kept[offset + chunk_size:]
            if not candidate:
                continue
            preserves = candidate_preserves(candidate)
            if preserves is None:
                break
            if preserves:
                kept = candidate
                granularity = max(granularity - 1, 2)
                reduced = True
                break
        if budget_exhausted:
            break
        if reduced:
            continue
        if granularity >= len(kept):
            break
        granularity = min(len(kept), granularity * 2)

    # Verify irreducibility by trying every single-file deletion, including
    # candidates newly exposed after a successful deletion.
    if not budget_exhausted:
        index = 0
        while index < len(kept):
            candidate = kept[:index] + kept[index + 1:]
            preserves = candidate_preserves(candidate)
            if preserves is None:
                break
            if preserves:
                kept = candidate
                index = 0
            else:
                index += 1

    final_patch = make_patch(kept)
    if checks_run + repeats > max_checks:
        raise ReproSliceError("internal budget reservation error: final confirmation cannot run")
    if not evaluate(final_patch, "target"):
        raise ReproSliceError("final reduced patch failed its repeated confirmation")
    kept_set = set(kept)
    return ReductionResult(
        patch=final_patch,
        report={
            "schema_version": 1,
            "status": "budget_exhausted" if budget_exhausted else "file_minimal",
            "base_commit": resolved_base,
            "source_fingerprint": fingerprint,
            "check": check,
            "signature": signature,
            "checks_run": checks_run,
            "initial_files": files,
            "kept_files": kept,
            "dropped_files": [path for path in files if path not in kept_set],
            "repeats": repeats,
            "timeout_seconds": float(timeout),
        },
    )
