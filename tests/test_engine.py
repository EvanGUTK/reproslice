from pathlib import Path
import os
import subprocess
import shlex
import tempfile
import unittest
from unittest.mock import patch

from reproslice.engine import ReproSliceError, minimize


def git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(path), *args], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.decode().strip()


def failing_check(needle: str = "BUGSIG") -> str:
    code = ("import pathlib,sys; found=any(" + repr(needle) +
            " in p.read_bytes().decode('latin1') for p in pathlib.Path('.').rglob('*') if p.is_file()); "
            "print(" + repr(needle) + " if found else 'ok'); sys.exit(1 if found else 0)")
    return "python3 -c " + shlex.quote(code)


class MinimizeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="reproslice-test-")
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "base.txt").write_text("base\n")
        git(self.repo, "add", "base.txt")
        git(self.repo, "commit", "-qm", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name: str, content: bytes, staged: bool = False):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        literal = ":(literal)" + name
        was_tracked = subprocess.run(["git", "-C", str(self.repo), "ls-files", "--error-unmatch", "--", literal],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        path.write_bytes(content)
        if staged or not was_tracked:
            git(self.repo, "add", "--", literal)

    def run_minimize(self, **kwargs):
        options = dict(repo=self.repo, base=self.base, check=failing_check(),
                       signature="BUGSIG", timeout=4, max_checks=50, repeats=2)
        options.update(kwargs)
        return minimize(**options)

    def test_ddmin_keeps_only_causal_file_and_preserves_source(self):
        self.write(":(glob)causal file.txt", b"BUGSIG\n", staged=True)
        self.write("irrelevant.txt", b"noise\n")
        before = git(self.repo, "status", "--porcelain=v1", "-z")
        result = self.run_minimize()
        after = git(self.repo, "status", "--porcelain=v1", "-z")
        self.assertEqual(result.report["status"], "file_minimal")
        self.assertEqual(result.report["kept_files"], [":(glob)causal file.txt"])
        self.assertEqual(result.report["dropped_files"], ["irrelevant.txt"])
        self.assertEqual(before, after)
        self.assertIn(b"BUGSIG", result.patch)
        self.assertEqual(result.report["checks_run"] % 2, 0)

    def test_binary_addition_round_trip(self):
        self.write("old.bin", b"old\x00\xff")
        git(self.repo, "add", "old.bin")
        git(self.repo, "commit", "-qm", "add old binary")
        self.base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "old.bin").unlink()
        self.write("new binary.bin", b"BUGSIG\x00\xff")
        result = self.run_minimize(max_checks=20)
        self.assertEqual(set(result.report["kept_files"]), {"new binary.bin"})
        check_tree = Path(self.temp.name) / "verify"
        git(self.repo, "worktree", "add", "--detach", str(check_tree), self.base)
        try:
            subprocess.run(["git", "-C", str(check_tree), "apply", "--binary", "-"],
                           input=result.patch, check=True)
            self.assertEqual((check_tree / "new binary.bin").read_bytes(), b"BUGSIG\x00\xff")
            self.assertTrue((check_tree / "old.bin").exists())
        finally:
            git(self.repo, "worktree", "remove", "--force", str(check_tree))

    def test_binary_deletion_round_trip(self):
        self.write("old binary.bin", b"old\x00\xff")
        git(self.repo, "commit", "-qm", "add old binary")
        self.base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "old binary.bin").unlink()
        check = "test -e 'old binary.bin' || { echo BUGSIG; exit 1; }"
        result = self.run_minimize(check=check, max_checks=20)
        self.assertEqual(result.report["kept_files"], ["old binary.bin"])
        check_tree = Path(self.temp.name) / "verify-delete"
        git(self.repo, "worktree", "add", "--detach", str(check_tree), self.base)
        try:
            subprocess.run(["git", "-C", str(check_tree), "apply", "--binary", "-"],
                           input=result.patch, check=True)
            self.assertFalse((check_tree / "old binary.bin").exists())
        finally:
            git(self.repo, "worktree", "remove", "--force", str(check_tree))

    def test_untracked_nonignored_input_is_rejected(self):
        self.write("tracked.txt", b"BUGSIG")
        (self.repo / "stray.txt").write_bytes(b"unknown")
        with self.assertRaisesRegex(ReproSliceError, "untracked nonignored"):
            self.run_minimize()

    def test_git_environment_is_cleared_and_checkout_hooks_do_not_run(self):
        self.write("tracked.txt", b"BUGSIG")
        marker = Path(self.temp.name) / "hook-ran"
        hook = self.repo / ".git" / "hooks" / "post-checkout"
        hook.write_text("#!/bin/sh\nprintf called > " + shlex.quote(str(marker)) + "\n")
        hook.chmod(0o755)
        command = "git rev-parse --show-toplevel >/dev/null && " + failing_check()
        with patch.dict(os.environ, {
            "GIT_DIR": "/missing/inherited-git-dir",
            "GIT_WORK_TREE": "/missing/inherited-work-tree",
            "GIT_INDEX_FILE": "/missing/inherited-index",
            "GIT_CONFIG": "/missing/inherited-config",
        }):
            result = self.run_minimize(check=command)
        self.assertEqual(result.report["status"], "file_minimal")
        self.assertFalse(marker.exists())

    def test_base_must_pass(self):
        self.write("tracked.txt", b"BUGSIG")
        with self.assertRaisesRegex(ReproSliceError, "base check did not pass"):
            self.run_minimize(check="echo BUGSIG; exit 1")

    def test_incidental_non_target_failure_is_rejected(self):
        self.write("tracked.txt", b"BUGSIG")
        command = "echo unrelated-error >&2; exit 7"
        with self.assertRaisesRegex(ReproSliceError, "incidental failure"):
            self.run_minimize(check=command)

    def test_inconsistent_repeats_are_rejected(self):
        self.write("tracked.txt", b"BUGSIG")
        stamp = Path(self.temp.name) / "counter"
        code = ("from pathlib import Path; import sys; p=Path(" + repr(str(stamp)) +
                "); n=int(p.read_text()) if p.exists() else 0; p.write_text(str(n+1)); "
                "print('BUGSIG'); sys.exit(1 if n % 2 else 0)")
        command = "python3 -c " + shlex.quote(code)
        with self.assertRaisesRegex(ReproSliceError, "inconsistent across repeats"):
            self.run_minimize(check=command)

    def test_timeout_and_output_overflow_are_inconclusive(self):
        self.write("tracked.txt", b"BUGSIG")
        with self.assertRaisesRegex(ReproSliceError, "timed out"):
            self.run_minimize(check="sleep 3", timeout=0.1)
        with self.assertRaisesRegex(ReproSliceError, "output exceeded"):
            self.run_minimize(check="yes x", timeout=3)

    def test_background_descendants_are_killed_after_shell_exit(self):
        self.write("tracked.txt", b"BUGSIG")
        command = "if grep -q BUGSIG tracked.txt 2>/dev/null; then sleep 30 & echo BUGSIG; exit 1; else echo ok; fi"
        result = self.run_minimize(check=command, timeout=3)
        self.assertEqual(result.report["status"], "file_minimal")

    def test_source_mutation_during_reduction_discards_result(self):
        self.write("tracked.txt", b"BUGSIG")
        from reproslice import engine

        snapshot = engine._source_snapshot
        calls = 0

        def mutate_before_final_check(repo, base):
            nonlocal calls
            calls += 1
            if calls == 3:
                (self.repo / "tracked.txt").write_bytes(b"changed while reducing")
            return snapshot(repo, base)

        with patch("reproslice.engine._source_snapshot", side_effect=mutate_before_final_check):
            with self.assertRaisesRegex(ReproSliceError, "source changed during reduction"):
                self.run_minimize()

    def test_budget_reserves_final_repeats_and_reports_exhaustion(self):
        self.write("tracked.txt", b"BUGSIG")
        self.write("noise.txt", b"noise")
        with self.assertRaisesRegex(ReproSliceError, "at least 6"):
            self.run_minimize(max_checks=5)
        result = self.run_minimize(max_checks=6)
        self.assertEqual(result.report["status"], "budget_exhausted")
        self.assertEqual(result.report["checks_run"], 6)

    def test_empty_signature_is_invalid(self):
        with self.assertRaisesRegex(ReproSliceError, "must be nonempty"):
            self.run_minimize(signature="")
        with self.assertRaisesRegex(ReproSliceError, "at least 2"):
            self.run_minimize(repeats=1)


if __name__ == "__main__":
    unittest.main()
