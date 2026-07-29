# QMD Integration Reference

ClawShelf indexes generated Markdown in `clawshelf/normalized/`. QMD owns
collection management and retrieval; ClawShelf owns extraction, normalization,
and source traceability.

QMD commands are internal implementation details. In Lark, Feishu, WeChat,
Claude, Codex, OpenClaw, and other harnesses, users should ask natural-language
questions about the shelf. Agents run QMD behind the scenes and return cited
results. Only expose commands for developer/debug requests or explicit backend
questions.

| Command | Use |
| --- | --- |
| `qmd collection show <name>` | Check whether a collection is already registered. |
| `qmd collection add <path> --name <name>` | Register normalized records when the collection is missing. |
| `qmd update` | Refresh existing collections after records change. |
| `qmd status` | Inspect collection/index health. |
| `qmd search "<query>" -c <name>` | Fast keyword retrieval. |
| `qmd vsearch "<query>" -c <name>` | Vector-only candidate recall without reranking. |
| `qmd query "<query>" -c <name>` | Hybrid, reranked retrieval. |
| `qmd get "<path-or-docid>"` | Retrieve one record. |
| `qmd multi-get "<pattern>"` | Retrieve a selected batch. |
| `qmd embed -c <name>` | Generate embeddings when semantic search is needed. |

Use `--format json` or `--format files` where structured output improves
source tracking. If QMD is absent or indexing fails, read normalized Markdown
directly and record the limitation.

For watcher classification, QMD is a recall backend only. The watcher invokes
`vsearch` after deterministic recall when fewer than the configured target
number of candidates were found. Returned similarity values are written to the
event and linked-source audit fields, but never contribute to creativity
scoring or independently upgrade an event to P1.

Registration must be idempotent. Before running `qmd collection add`, check
whether the intended collection already exists:

```bash
if qmd collection show "<name>" >/dev/null 2>&1; then
  qmd update
else
  qmd collection add "<path>" --name "<name>"
fi
```

If `collection add` reports `Collection '<name>' already exists` or `A
collection already exists for this path and pattern`, treat that as an
already-registered state, then run `qmd update` instead of surfacing a failure
to the user.

The bundled scripts resolve QMD from `npm prefix -g` so an unrelated QMD binary
earlier on `PATH` cannot override the configured installation.
