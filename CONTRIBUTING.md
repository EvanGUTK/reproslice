# Contributing

Start with an issue describing a reproducible problem, expected behavior, and the smallest acceptance check. Coordinate ownership before changing shared files.

Use a topic branch in a sibling worktree. Keep each commit focused: `fix(engine): distinguish timeout from target failure (#123)`. Stage explicit paths. A PR should explain the problem, the resulting behavior, its issue, and exact local verification commands.

Run `PYTHONPATH=src python3 -m unittest discover -s tests -v` and `git diff --check`. No GitHub Actions or remote CI gates are used. Local independent review applies before push; only a maintainer with user authorization merges.

Add `Co-authored-by` only for actual coauthored work, using the contributor's approved GitHub-linked identity. Never invent attribution or split changes only to inflate contribution counts.

The repository currently has no license. Public hosting alone is not permission to reuse or redistribute the code. We do not ask contributors to waive rights through this guide.
