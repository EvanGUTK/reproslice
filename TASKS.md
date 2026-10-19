# First increment: local patch minimizer

Epic: [#1](https://github.com/EvanGUTK/reproslice/issues/1).

| Issue | Owner | Responsibility | Dependencies |
|---|---|---|---|
| [#2](https://github.com/EvanGUTK/reproslice/issues/2) | Engine | Capture, candidate execution, failure oracle, bounded reduction | None |
| [#3](https://github.com/EvanGUTK/reproslice/issues/3) | Chief | CLI, portable artifacts, demo, agent skill | #2 contract |
| [#4](https://github.com/EvanGUTK/reproslice/issues/4) | Chief + Validator | Engineering docs and independent verification | #2, #3 |
| [#5](https://github.com/EvanGUTK/reproslice/issues/5) | Chief | Prevent demo Git environment redirection; regression | Found during #3 review |
| [#6](https://github.com/EvanGUTK/reproslice/issues/6) | Engine + Chief | Bound output cleanup for detached children | Found during #2 review |
| [#7](https://github.com/EvanGUTK/reproslice/issues/7) | Engine + Chief | Use bounded literal failure matching | Found during #2 review |
| [#8](https://github.com/EvanGUTK/reproslice/issues/8) | Engine + Chief | Preserve dependent-file reductions and reuse the passing base | Found during #2 review |

Writers use separate sibling worktrees. Chief integrates focused commits on `feat/cli-chief`; every push requires CodeRabbit dispositions plus Validator and Chief approval of exact HEAD. This increment is delivered as a coherent PR with linked task closures. The user retains final merge authority.

Later candidates, not authorized for this increment: hunk-level refinement; Claude/Codex transcript adapters; MCP job interface; local visual inspection. Prioritize these using feedback and reproducible failures, not achievement quotas.
