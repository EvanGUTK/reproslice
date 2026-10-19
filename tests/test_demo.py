"""Demo generation must never redirect Git writes into an unrelated checkout."""
from pathlib import Path
import os
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
make_demo = runpy.run_path(str(ROOT / "examples" / "make_demo.py"))["make_demo"]


class DemoSafetyTests(unittest.TestCase):
    def test_inherited_git_overrides_cannot_mutate_another_repository(self):
        with tempfile.TemporaryDirectory(prefix="reproslice-demo-regression-") as temporary:
            root = Path(temporary)
            victim = make_demo(root / "unrelated")
            def git(*args):
                return subprocess.check_output(["git", "-C", str(victim), *args])
            (victim / "unrelated.txt").write_text("staged work must remain staged")
            git("add", "unrelated.txt")
            git("config", "user.name", "Fixture Owner")
            head, index, config, status = (git("rev-parse", "HEAD"), git("ls-files", "--stage"), git("config", "--local", "--list"), git("status", "--porcelain"))
            with patch.dict(os.environ, {"GIT_DIR": str(victim / ".git"), "GIT_WORK_TREE": str(victim), "GIT_INDEX_FILE": str(victim / ".git" / "index")}):
                new = make_demo(root / "new-demo")
            self.assertEqual(git("rev-parse", "HEAD"), head)
            self.assertEqual(git("ls-files", "--stage"), index)
            self.assertEqual(git("config", "--local", "--list"), config)
            self.assertEqual(git("status", "--porcelain"), status)
            self.assertTrue((new / ".git").is_dir())


if __name__ == "__main__":
    unittest.main()
