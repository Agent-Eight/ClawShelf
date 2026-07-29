# Metadata Fields Reference

Document-level metadata field definitions for the Markdown table rendered
from `templates/metadata-table.md`.

| Field | Purpose |
| --- | --- |
| `id` | Stable local row id assigned by ClawShelf. |
| `source` | File path, QMD URI, or docid. |
| `title` | Document title or best inferred name. |
| `type` | File/document type. |
| `date` | Explicit or inferred date, when available. |
| `authors_or_origin` | Author, organization, meeting source, or unknown. |
| `topics` | Short tags for retrieval and scanning. |
| `keywords` | Eight to fifteen source-grounded key terms, each with evidence. |
| `rag_terms` | Curated watcher/search terms with role, weight, aliases, and evidence. |
| `map_role` | Role in the knowledge map: background, method, evidence, contradiction, gap, or idea seed. |
| `summary` | Six-question research-reading summary: problem, contribution, method/data/setting, findings, use conditions/limits, and transferable value. |
| `key_claims` | Main claims, findings, or assertions. |
| `methods_or_basis` | Evidence type, method, dataset, or reasoning basis. |
| `limitations` | Author-stated limits, scope boundaries, or extraction limits. |
| `useful_for` | How this document may help the user's goal. |
| `idea_signals` | Potential connections, changed conclusions, gaps, or next-step signals tied to the Shelf Plan. |
| `confidence` | High, medium, or low confidence in extracted metadata. |

## Conventions

- Keep metadata document-level. Section- and chunk-level metadata are
  future extensions.
- Keywords are not generic tags. Each keyword must be central to the source and
  have an evidence location.
- `rag_terms` are the preferred input for lightweight RAG retrieval and watcher
  comparison. Prefer specific multi-word terms over broad isolated tokens.
- Mark inferred metadata separately from explicit source metadata when the
  distinction matters.
- On conflicting metadata, preserve both candidates and mark the field uncertain.
- Keep `map_role` and `idea_signals` source-backed when possible. If an idea
  signal is speculative, mark it speculative and lower confidence.
