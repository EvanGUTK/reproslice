"""CLI boundaries, artifact contents, and an independently applied reproducer."""
from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from reproslice.cli import main
from reproslice.engine import ReductionResult, ReproSliceError

ROOT = Path(__file__).resolve().parents[1]
make_demo = runpy.run_path(str(ROOT / "examples" / "make_demo.py"))["make_demo"]
SIGNATURE = "AssertionError: reproslice-demo: expected total 42"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="reproslice-cli-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = make_demo(self.root / "source with spaces")
        self.output = self.root / "result"

    def args(self, output=None):
        return ["minimize", "--repo", str(self.repo), "--base", "HEAD", "--check", "python3 check.py", "--signature", SIGNATURE, "--output", str(output or self.output)]

    def invoke(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def report(self, status="file_minimal"):
        return {"schema_version": 1, "status": status, "base_commit": "a"*40, "source_fingerprint": "b"*64, "check": "python3 check.py", "signature": SIGNATURE, "checks_run": 8, "initial_files": ["calculator.py", "notes.txt"], "kept_files": ["calculator.py"], "dropped_files": ["notes.txt"], "repeats": 2, "timeout_seconds": 30}

    def test_rejects_output_inside_source_before_running_checks(self):
        with patch("reproslice.cli.minimize") as engine:
            code, _, error = self.invoke(self.args(self.repo / "artifacts"))
        self.assertEqual(code, 2)
        self.assertIn("outside", error)
        engine.assert_not_called()
        self.assertFalse((self.repo / "artifacts").exists())

    def test_preserves_existing_artifacts(self):
        self.output.mkdir()
        (self.output / "keep.txt").write_text("unrelated")
        with patch("reproslice.cli.minimize") as engine:
            code, _, _ = self.invoke(self.args())
        self.assertEqual(code, 2)
        engine.assert_not_called()
        self.assertEqual((self.output / "keep.txt").read_text(), "unrelated")

    def test_engine_failure_publishes_no_bundle(self):
        with patch("reproslice.cli.minimize", side_effect=ReproSliceError("baseline does not pass")):
            code, _, error = self.invoke(self.args())
        self.assertEqual(code, 2)
        self.assertIn("baseline", error)
        self.assertFalse(self.output.exists())

    def test_budget_result_remains_distinct_from_minimal(self):
        result = ReductionResult(patch=b"verified patch", report=self.report("budget_exhausted"))
        with patch("reproslice.cli.minimize", return_value=result):
            code, output, _ = self.invoke(self.args() + ["--json"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(output)["status"], "budget_exhausted")
        self.assertEqual((self.output / "reduced.patch").read_bytes(), result.patch)

    def test_git_environment_does_not_redirect_explicit_repository(self):
        other = make_demo(self.root / "other repository")
        result = ReductionResult(patch=b"verified patch", report=self.report())
        with patch.dict(os.environ, {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}):
            with patch("reproslice.cli.minimize", return_value=result) as engine:
                code, _, error = self.invoke(self.args())
        self.assertEqual(code, 0, error)
        self.assertEqual(engine.call_args.args[0], self.repo)

    def test_output_symlink_rejected_without_following(self):
        target = self.root / "other"
        self.output.symlink_to(target, target_is_directory=True)
        with patch("reproslice.cli.minimize") as engine:
            code, _, error = self.invoke(self.args())
        self.assertEqual(code, 2)
        self.assertIn("symlink", error)
        engine.assert_not_called()
        self.assertFalse(target.exists())

    def test_end_to_end_bundle_reproduces_in_a_fresh_checkout(self):
        def git(*args):
            return subprocess.check_output(["git", "-C", str(self.repo), *args])
        original_diff = git("diff", "--binary")
        original_status = git("status", "--porcelain")
        original_index = git("ls-files", "--stage")
        code, _, error = self.invoke(self.args())
        self.assertEqual(code, 0, error)
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["kept_files"], ["calculator.py"])
        self.assertEqual(len(report["initial_files"]), 3)
        self.assertEqual(git("diff", "--binary"), original_diff)
        self.assertEqual(git("status", "--porcelain"), original_status)
        self.assertEqual(git("ls-files", "--stage"), original_index)
        reproduction = self.root / "independent-checkout"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "--detach", str(reproduction), report["base_commit"]], check=True, capture_output=True)
        self.addCleanup(subprocess.run, ["git", "-C", str(self.repo), "worktree", "remove", "--force", str(reproduction)], capture_output=True)
        subprocess.run(["git", "-C", str(reproduction), "apply", str(self.output / "reduced.patch")], check=True, capture_output=True)
        check = subprocess.run([sys.executable, "check.py"], cwd=reproduction, text=True, capture_output=True)
        self.assertEqual(check.returncode, 1)
        self.assertIn(SIGNATURE, check.stderr)
        self.assertIn(report["base_commit"], (self.output / "reproduction.md").read_text())


if __name__ == "__main__":
    unittest.main()
