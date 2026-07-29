# Watch Hooks

ClawShelf watches an explicitly selected local folder. `/clawshelf use
<folder>` starts one background watcher through `scripts/openclaw-use.py`;
`/clawshelf watch` remains a developer/debug entry point. Do not install an OS
service, cron job, or other persistent scheduler unless the user separately
asks for it.

## Pipeline

For each stable new or changed source:

1. Extract, normalize, validate, and refresh shelf metadata.
2. Stop with `intake_deferred` if a valid normalized record is unavailable.
3. Retrieve candidates through exact/alias RAG matching, structured concept
   bridges, and evidence-bearing structural relation candidates over title,
   summary, methods, limitations, improvement directions, axon/dendrite
   signals, idea signals, and connection hooks. Structural relations do not
   require an existing exact RAG match.
4. Score candidates with the single creativity contract.
5. Classify P1/P2 and write an event under `<folder>/clawshelf/events/`.
6. Render an enabled notification under
   `<folder>/clawshelf/notifications/`, deliver through the active OpenClaw
   session, and update the dedupe ledger.

Generated/internal paths, hidden files, VCS folders, virtual environments,
bytecode, and partial-download suffixes are ignored. A new normalized record is
excluded from its own comparison set.

## Commands

```bash
uv run --locked --project <skill-dir> python <skill-dir>/scripts/openclaw-use.py <folder> \
  --session-key <current-openclaw-session-key>

uv run --locked --project <skill-dir> python <skill-dir>/scripts/openclaw-watch-adapter.py <folder> \
  --agent-id <current-openclaw-agent-id> --session-key <current-openclaw-session-key>

uv run --locked --project <skill-dir> python <skill-dir>/scripts/openclaw-watch-adapter.py <folder> \
  --agent-id <current-openclaw-agent-id> --session-key <current-openclaw-session-key> \
  --once <new-file>
```

`openclaw-use.py` resets the selected folder's watcher by default so the
process loads current code, configuration, and routing. When no explicit
session key is supplied, it may resolve a recent matching entry from the
OpenClaw command log. The selected canonical session is the source of truth for
the originating agent. The watcher persists the bound agent, channel, session,
owner-DM target, and account together and passes the same agent to
normalization, creativity scoring, and notification delivery. The route is
visible as `delivery_binding` in `clawshelf-config.json`; editing it and running
`/clawshelf reset` applies the new binding. It must never contain provider
credentials or tokens.

## Creativity Contract

`creativity_score` is:

```text
relationship + evidence + novelty_or_tension + actionability - risk
```

The positive components are integers from 0 to 5; risk is 0 to 3. A P1
requires all of:

- score at or above the configured threshold (default 13);
- confidence at or above the configured minimum (default 0.65);
- `verdict: p1_candidate`;
- at least one matched-evidence item with source evidence from both records.

Anything else that completed normalization is P2. No candidate means
`creativity_score: null` and `verdict: not_scored`; zero is reserved for an
actual completed score of zero. Host scoring uses the same contract as the
deterministic fallback, receives only normalized evidence packets, and cannot
retain a P1 verdict when its returned evidence cannot be traced to both
records.

Folder configuration:

```json
{
  "schema": "clawshelf.config",
  "notification_policy": "p1_p2",
  "creativity_scoring": {
    "mode": "auto",
    "model": "",
    "novelty_preference": 0.5,
    "candidate_limit": 10,
    "semantic_retrieval": "auto",
    "semantic_candidate_target": 3,
    "advanced": {
      "threshold": 13,
      "min_confidence": 0.65
    }
  },
  "shelf_plan": {
    "domain_background": "unknown",
    "work_direction": "literature review",
    "concrete_problem": "organize and cite sources",
    "collection_pattern": "one-time batch",
    "companion_mode": "research secretary"
  }
}
```

Runtime overrides use `--creativity-scorer`, `--creativity-model`,
`--creativity-threshold`, `--creativity-min-confidence`, `--candidate-limit`,
`--novelty-preference`, `--semantic-retrieval`, and
`--semantic-candidate-target`. OpenClaw owns provider credentials.

Exact RAG, structured-concept, and evidence-backed relation recall run first.
When fewer than `semantic_candidate_target` candidates remain, `auto` asks QMD
vector search to fill the set. QMD similarity is retrieval audit metadata; it
is never added to `creativity_score` and cannot directly produce P1. `required`
defers intake if QMD is unavailable, while `auto` records the degraded state
and continues with deterministic candidates.

## Event Shape

```json
{
  "schema": "clawshelf.watch-event",
  "status": "classified",
  "classification": "P1",
  "priority": "P1",
  "classification_reason": "creative score gates passed",
  "new_files": ["/path/to/new-paper.pdf"],
  "creativity_score": 14,
  "score_breakdown": {
    "relationship": 4,
    "evidence": 4,
    "novelty_or_tension": 3,
    "actionability": 4,
    "risk": 1
  },
  "confidence": 0.78,
  "verdict": "p1_candidate",
  "candidate_retrieval_path": [
    "structured_concept_bridge",
    "structured_relation_candidate",
    "qmd_vector"
  ],
  "semantic_retrieval": {
    "backend": "qmd_vector",
    "mode": "auto",
    "status": "used",
    "candidate_target": 3,
    "queries": []
  },
  "linked_sources": [
    {
      "new_source_path": "/path/to/new-paper.pdf",
      "linked_source_path": "/path/to/existing-paper.pdf",
      "normalized_record_path": "/path/to/clawshelf/normalized/existing-paper.md",
      "matched_evidence": [
        {
          "signal": "prediction market execution",
          "new_evidence": "section: Arbitrage",
          "linked_evidence": "section: Benchmark",
          "why_it_matters": "connects an edge to an executable evaluation method"
        }
      ],
      "idea_candidates": [
        {
          "idea_type": "innovation",
          "new_signal_type": "Strong Method",
          "linked_signal_type": "Extension Hint",
          "new_signal": "source-backed method",
          "linked_signal": "source-backed extension",
          "new_evidence": "section: Arbitrage",
          "linked_evidence": "section: Benchmark",
          "total_score": 18
        }
      ]
    }
  ],
  "matched_evidence": [
    {
      "signal": "prediction market execution",
      "new_evidence": "section: Arbitrage",
      "linked_evidence": "section: Benchmark",
      "why_it_matters": "connects an edge to an executable evaluation method"
    }
  ],
  "normalization_outcomes": [
    {
      "source": "/path/to/new-paper.pdf",
      "status": "normalized",
      "record_path": "/path/to/clawshelf/normalized/new-paper.md",
      "coverage": "full",
      "warnings": []
    }
  ],
  "synthesis_brief_update": {
    "status": "updated",
    "path": "/path/to/clawshelf/clawshelf-brief.md",
    "new_connections": 1,
    "candidate_ideas": 3,
    "error": ""
  }
}
```

An `intake_deferred` event has no classification or priority and is not an
archive-success notification. Normalization distinguishes host/runtime
unavailability (`llm_unavailable`) from exhausted schema or evidence repair
(`validation_failed`).

## Notifications and Delivery

`notification_policy` is either:

- `p1_only`: deliver P1; keep P2 log-only.
- `p1_p2`: deliver P1 and P2.

Before an enabled P1 is persisted and delivered, the watcher updates the
auto-managed region in `clawshelf-brief.md`. It deduplicates source-backed
connections and candidate ideas while preserving all content outside the
managed markers. A write failure is recorded in `synthesis_brief_update` but
does not suppress the P1 event.

P1 messages include linked original sources, bidirectional evidence, brief
update status, and up to three candidate ideas. They do not include a suggested
next action. Normalized Markdown paths remain event audit data and are not
rendered in the notification.
Each matched-evidence item is rendered as a numbered evidence card with the
connection, named new-source location, linked original-source location, and
relationship explanation. When structured evidence is unavailable, messages
show compact candidate-keyword tags instead.
P2 messages contain original source names and up to five key arguments per
source copied from the normalized record's `Key Claims` section. They do not
render normalized Markdown paths and must not claim a cross-source research
connection or include matched signals, idea text, or research recommendations.

Enabled notifications use schema `clawshelf.notification` and delivery policy
schema `clawshelf.delivery-policy`. The adapter calls:

```bash
openclaw agent --session-key <current-openclaw-session-key> --deliver --message-file <prompt>
```

Failed delivery is retried up to three total attempts. Successful P1 and P2
deliveries update `clawshelf.notify-state`; dedupe keys include notification
kind plus source path, and values are normalized source hashes. Thus the same
content can produce one P1 and one P2 receipt over its lifetime, but repeated
delivery of the same kind and source hash is suppressed.
