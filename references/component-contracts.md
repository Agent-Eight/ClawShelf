# Component Contracts

These are internal extension seams, not a public plugin API.

## Shared records

- `SourceRecord`: absolute path or URL, input-relative path, type, SHA-256 of
  the file bytes or fetched response body.
- `ExtractionResult`: source, extraction method, Markdown-ready content, warnings.
- `NormalizedRecord`: source record plus summary, keywords, RAG terms, claims,
  methods/basis, limitations, evidence, confidence, and output path.
- `KeywordExtractionPacket`: compact source-backed main-body sections with
  heading, heading path, semantic role, and Markdown text (including nested
  subsections), sent to the
  keyword worker under a fixed character budget; never includes secrets or
  channel-specific routing data.
- `KeywordExtraction`: strict JSON keyword-worker response with six-question
  summary, evidence-bearing paper role, keywords, RAG terms, limitations, axon
  signals, dendrite signals, idea hooks, evidence, and non-secret model label.
  Repair calls return a JSON Merge Patch that is merged into the prior complete
  candidate before validation.
- `RagTerm`: canonical term, weight, aliases, evidence location, and role for
  lightweight retrieval and watcher comparison.
- `CreativityScoreRequest`: a compact evidence packet for a new normalized record
  plus up to ten candidate `{linked_record_path, linked_record}` packets in one
  fan-in request; never includes full source PDFs or secrets.
- `CreativityScoreResult`: validated score breakdown, confidence, bidirectional
  matched evidence, verdict, and non-secret model label.
- `RetrievalHit`: normalized record path/docid, snippet, score, backend name.
- `ShelfPlan`: domain, direction, concrete problem, collection/update pattern,
  companion mode, and idea-generation triggers.
- `ProcessingWarning`: source (optional), code, message, and suggested action.

## Components

| Component | Contract | Default |
| --- | --- | --- |
| `SourceExtractor` | Expose an expected extraction method, `supports(source)`, and `extract(source)` returning `ExtractionResult`; the method is checked before expensive extraction for cache reuse. | Markdown/text, PyMuPDF4LLM PDF-to-Markdown, XLSX, and URL extractors. |
| `LLMFallback` | Read an unsupported source through harness tools; return content or a warning. | Harness LLM, labelled `llm_fallback`. |
| `KeywordWorker` | Convert compact main-body section packets into strict JSON summary, keywords, RAG terms, limitations, axon/dendrite signals, and idea hooks. Recoverable term-level defects are omitted with warnings; malformed JSON and structural defects still fail. | `scripts/clawshelf/keyword_worker.py`; OpenClaw owns model credentials; default is the host model with no override. |
| `Normalizer` | Render validated keyword-worker output into `templates/normalized-record.md`; replace narrative placeholders with source-metadata unknowns and retain partial records with warnings. Do not write malformed or structurally invalid records. | `scripts/clawshelf/auto_normalize.py`. |
| `NormalizedRecordValidator` | Parse and validate normalized records before they are indexed or used by the watcher. | `scripts/clawshelf/normalize.py`. |
| `CandidateRetriever` | Combine exact/alias RAG matches with conservative structured concept bridges. Retrieval proposes candidates but never decides P1. | `scripts/clawshelf/terms.py`, `scripts/clawshelf/creativity_score.py`. |
| `CreativityScorer` | Apply one score contract to deterministic and host-scored candidates; require threshold, confidence, verdict, and bidirectional evidence for P1. | `scripts/clawshelf/creativity_score.py`; OpenClaw owns model credentials. |
| `RetrievalBackend` | Register, status, search, get, and multi-get normalized records. | QMD CLI. |
| `ShelfPlanner` | Collect or infer onboarding context and tune archive/map/idea behavior. | Harness chat flow. |
| `ArtifactRenderer` | Render archive, knowledge map, and idea Markdown from normalized records/hits. | Existing templates. |
| `CompanionResponder` | Answer natural-language shelf requests with cited search results and proactive recommendations. | Harness LLM + QMD backend. |
| `StorageLayout` | Resolve `clawshelf/normalized/` and final artifact paths from input root. | Local filesystem. |
| `WatchHook` | Ensure a selected folder has one watcher, reconcile a bounded set of stale sources on startup, then emit P1/P2 intake events for stable new or changed files. Saved partial records remain eligible for comparison; events expose per-source normalization outcomes. | `scripts/openclaw-use.py`, `scripts/watch-shelf.py`, `references/watch-hooks.md`. |
| `AgentHarness` | Provide local reads, commands, Markdown writes, and LLM reasoning. | OpenClaw. |

Add a new deterministic source type by implementing and registering a
`SourceExtractor`; do not change orchestration or the normalized-record schema.
Do not add deterministic keyword extraction back into the normalizer; keyword
quality is owned by the LLM worker and its schema validator.
