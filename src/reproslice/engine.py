"""Deterministic, whole-file patch reduction for reproducible failures."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
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


def _source_snapshot(repo: Path, base: str) -> dict[str, bytes]:
    names_raw = _git(repo, "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", base, "--")
    names = [_validate_path(part) for part in names_raw.split(b"\0") if part]
    return {
        path: _git(
            repo, "diff", "--binary", "--full-index", "--no-renames",
            "--no-ext-diff", "--no-textconv", base, "--", f":(literal){path}",
        )
        for path in names
    }


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
    process = None
    selector = None
    try:
        _git(repo, "worktree", "add", "--detach", "--force", os.fspath(worktree), base)
        if patch:
            _git(worktree, "apply", "--binary", "--whitespace=nowarn", "-", input=patch)
        process = subprocess.Popen(
            command, cwd=worktree, shell=True, executable="/bin/sh",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        )
        output_fd = process.stdout.fileno()
        os.set_blocking(output_fd, False)
        selector = selectors.DefaultSelector()
        selector.register(output_fd, selectors.EVENT_READ)
        output = bytearray()
        start = time.monotonic()
        deadline = start + timeout
        pipe_eof = False
        timed_out = False
        overflow = False
        leader_exited_before_cleanup = False
        while process.poll() is None or not pipe_eof:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            events = selector.select(min(remaining, 0.05))
            for key, _ in events:
                while True:
                    try:
                        chunk = os.read(key.fd, min(65536, _MAX_OUTPUT_BYTES + 1 - len(output)))
                    except BlockingIOError:
                        break
                    if not chunk:
                        pipe_eof = True
                        selector.unregister(key.fd)
                        break
                    room = _MAX_OUTPUT_BYTES - len(output)
                    output.extend(chunk[:room])
                    if len(chunk) > room:
                        overflow = True
                        break
                if overflow:
                    break
            if overflow:
                break
        # A check leader may exit while a detached descendant keeps the output
        # pipe open. Never treat the captured prefix as a complete oracle result.
        leader_exited_before_cleanup = process.poll() is not None
        if timed_out or overflow:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            # Reap any same-group background child that closed its output pipes.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        text = output.decode("utf-8", "replace")
        if timed_out:
            if leader_exited_before_cleanup and not pipe_eof:
                return "inconclusive", "command leader exited but a descendant kept its output pipe open; detached descendants cannot be contained"
            return "inconclusive", f"command timed out after {timeout:g}s before process exit and complete output"
        if overflow:
            return "inconclusive", f"command output exceeded {_MAX_OUTPUT_BYTES} bytes"
        if not pipe_eof:
            return "inconclusive", "command exited but a descendant kept its output pipe open; detached descendants cannot be contained"
        if process.returncode is None or process.returncode < 0 or process.returncode >= 128:
            return "inconclusive", f"command exited abnormally ({process.returncode})"
        return ("exit-zero" if process.returncode == 0 else "exit-nonzero"), text
    except ReproSliceError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        return "inconclusive", f"could not run candidate: {exc}"
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except OSError:
                        pass
        if selector is not None:
            selector.close()
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
    and one MiB of captured output per execution. A detached descendant that
    keeps stdout open makes the result inconclusive; escaped processes are not
    sandboxed or fully reclaimed.
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
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 2:
        raise ReproSliceError("repeats must be an integer of at least 2")
    if not isinstance(max_checks, int) or isinstance(max_checks, bool) or max_checks < 3 * repeats:
        raise ReproSliceError(f"max_checks must be at least {3 * repeats} to check base, patch, and final confirmation")

    if not isinstance(base, str) or not base or base.startswith("-") or "\0" in base:
        raise ReproSliceError("base must be a nonempty commit reference")
    root = _safe_repo(Path(repo))
    resolved_base = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
    file_patches = _source_snapshot(root, resolved_base)
    files = list(file_patches)
    original_patch = b"".join(file_patches.values())
    fingerprint = hashlib.sha256(original_patch).hexdigest()
    if _source_snapshot(root, resolved_base) != file_patches:
        raise ReproSliceError("tracked source changed while the input patch was being captured; retry from a stable checkout")
    checks_run = 0

    def make_patch(selected: list[str]) -> bytes:
        return b"".join(file_patches[path] for path in selected)

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
    if _source_snapshot(root, resolved_base) != file_patches:
        raise ReproSliceError("tracked source changed during reduction; result was discarded")
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
