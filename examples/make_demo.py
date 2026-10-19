"""Create a disposable repository with three changes and one reproducible bug."""
from pathlib import Path
import argparse
import os
import subprocess


def make_demo(directory: Path) -> Path:
    directory = directory.resolve()
    if directory.exists():
        raise ValueError("demo directory already exists; choose a new path")
    directory.mkdir(parents=True)
    def git(*args: str) -> None:
        git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        subprocess.run(["git", "-C", str(directory), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, env=git_env, timeout=30)
    git("init", "-b", "main")
    git("config", "user.name", "ReproSlice Demo")
    git("config", "user.email", "demo@example.invalid")
    (directory / "calculator.py").write_text("def total(items, shipping):\n    return items + shipping\n")
    (directory / "messages.py").write_text('WELCOME = "Hello"\n')
    (directory / "notes.txt").write_text("Initial notes.\n")
    (directory / "check.py").write_text(
        'from calculator import total\nassert total(40, 2) == 42, "reproslice-demo: expected total 42"\n'
    )
    git("add", "calculator.py", "messages.py", "notes.txt", "check.py")
    git("commit", "-m", "chore(demo): establish passing baseline")
    (directory / "calculator.py").write_text("def total(items, shipping):\n    return items - shipping\n")
    (directory / "messages.py").write_text('WELCOME = "Welcome"\n')
    (directory / "notes.txt").write_text("Updated unrelated notes.\n")
    return directory


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("directory", type=Path)
    args = cli.parse_args()
    try:
        print(make_demo(args.directory))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        cli.exit(2, f"make_demo: {error}\n")
