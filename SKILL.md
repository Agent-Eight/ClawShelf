---
name: clawshelf
description: "Turn a local document shelf into a proactive research/file companion: source-traceable archive, knowledge map/search, and idea generation."
license: MIT
metadata: { "author": "OpenClaw ClawShelf maintainers", "tags": ["research", "document-management", "retrieval", "knowledge-map", "idea-generation"], "permissions": ["file_read", "file_write", "shell_execute", "network"], "openclaw": { "emoji": "🐚", "requires": { "bins": ["uv"] }, "install": [{ "id": "brew-uv", "kind": "brew", "formula": "uv", "bins": ["uv"], "label": "Install uv (brew)" }, { "id": "node-qmd", "kind": "node", "package": "@tobilu/qmd", "bins": ["qmd"], "label": "Install QMD (npm)" }], "watch": { "autoEnableWhenInstalled": true, "useCommand": "scripts/openclaw-use.py", "command": "scripts/openclaw-watch-adapter.py", "eventSchema": "clawshelf.watch-event", "eventDir": "<folder>/clawshelf/events", "pushPolicy": { "P1": "notify", "P2": "notify" } } } }
---

# ClawShelf

Use ClawShelf as an ongoing research and file companion for a local document
collection. Archive inspected sources into source-traceable records, retrieve
them by natural language, compare evidence across records, and surface useful
new connections when the shelf changes.

All paths below are relative to the skill directory, `{baseDir}`.

## Daily operating rules

- Resolve the shelf from an explicit folder, the current session folder, or the
  only known shelf. Ask before writing when the target is ambiguous.
- Keep generated files under `<folder>/clawshelf/`; never modify source files.
- Ground every factual claim in inspected source content and cite the source
  record or original source. Label speculation explicitly.
- Match the user's language. Do not expose QMD commands unless asked for
  developer or backend details.
- Treat `clawshelf/normalized/` as the durable evidence layer. Preserve
  conflicting metadata as uncertain rather than choosing a winner.

For command names, folder resolution, language handling, and command-specific
behavior, read `{baseDir}/references/commands.md`.

## Use or refresh a shelf

For `/clawshelf use <folder>` in OpenClaw, run:

```bash
uv run --locked --project {baseDir} python {baseDir}/scripts/openclaw-use.py <folder> --session-key <current-openclaw-session-key>
```

The session key must be canonical (`agent:<agent-id>:<channel>:...`).
`openclaw-use.py` derives and binds the originating agent from that key; it
must not substitute the skill installation path or a default agent.
The resulting `agent`, `session`, `channel`, owner-DM `target`, and `account`
are written as `delivery_binding` in `clawshelf/clawshelf-config.json`.
They may be edited together and applied with `/clawshelf reset`; never place
app credentials, tokens, or secrets in this binding.

Use the returned resolved folder as the session's current shelf. Report its
readiness, normalized-record count, watcher state, and next action. If the
result requests onboarding or repair, read
`{baseDir}/references/onboarding.md` and follow only that one-time path.

For new or changed sources:

1. Fingerprint the source and preserve its original relative path or URL.
2. Extract supported content and normalize it into one Markdown record under
   `clawshelf/normalized/`.
3. Reuse a structurally complete record when its parsed `source_sha256`
   matches. Validate new output before writing it.
4. Update metadata and retrieval. If QMD is unavailable, keep the records and
   use direct Markdown retrieval with a degraded-retrieval warning.
5. Do not write a low-quality record when extraction or the keyword worker
   fails; record the failure and continue with other sources.

Read `{baseDir}/references/component-contracts.md` before changing extraction,
normalization, scoring, or record schemas. Use
`{baseDir}/references/qmd-integration.md` only for backend registration or
debugging.

## Search and companion requests

When the user asks a shelf question:

1. Resolve the intended shelf.
2. Retrieve relevant normalized records with QMD when available, otherwise
   read them directly.
3. Answer concisely with source citations.
4. For synthesis or idea requests, distinguish evidence from speculation and
   identify useful connections, contradictions, changed conclusions, missing
   evidence, and the strongest next direction.

Use `{baseDir}/references/harness-search.md` for retrieval behavior and
`{baseDir}/references/synthesis-brief.md` for briefs or idea artifacts. Output
templates live in `{baseDir}/templates/`.

## Generate an interactive neural overview

For `/clawshelf overview [folder]`, resolve a ready shelf and run:

```bash
uv run --locked --project {baseDir} python {baseDir}/scripts/render-overview.py <folder> --lang <auto|en|zh>
```

The command atomically writes
`<folder>/clawshelf/clawshelf-overview.html` and returns its path, node count,
filesystem URL (`file_url`), synapse count, validated P1 edge count, and any
skipped-record/event warnings. It also returns `markdown_link`, a complete
`[打开概览](file:///...)` link. In the user-facing response:

1. Emit `markdown_link` verbatim on its own line. Do not replace it with plain
   linked text or reconstruct its target.
2. Also show `path` as a local filesystem path.
3. Never rewrite either value as `http://` or `https://`, and never lowercase
   `/Users`.
4. If the active channel strips or blocks `file://` links, use its structured
   file-attachment/message tool with `filePath` set to `path` and tell the user
   to open the attached HTML. Do not claim a stripped link is clickable.

Every normalized source is a **neuron**, drawn with one dendrite branch per
dendrite signal and one axon terminal per axon signal. **Synapses** join two
records' signals: axo-dendritic (one record's axon signal meets another's
dendrite signal) and axo-axonic (two axon signals meet). Both require evidence
on each side and compatible signal types, and each one names the two signals it
joined. Validated P1 idea-spark links — those that independently clear the
configured score, confidence, verdict, and bidirectional-evidence gates — are
drawn on top as a stronger *confirmed* class, anchored to the same signals when
their spark text can be matched. Hidden RAG/topic similarity links still
position related neurons near each other.
The HTML embeds its rendering library, so it opens and stays fully interactive
with no network access. Generate only on explicit overview requests;
watch intake must not refresh or open the artifact automatically.

## Watch events

Normalize each stable new or changed source before comparing it with existing
records. Write the event under `clawshelf/events/`.

Run deterministic RAG, structured-concept, and evidence-backed relation recall
first. If the candidate set is below the configured target, use QMD vector
search only to fill candidate slots. Preserve vector similarity as audit
metadata and never add it to `creativity_score` or use it as a direct P1 gate.
In `auto` mode, QMD failure is a recorded degraded-retrieval state; in
`required` mode, it produces `intake_deferred`.

- P1: `creativity_score`, confidence, `p1_candidate` verdict, and bidirectional
  evidence all clear their configured gates; automatically update the managed
  P1 synthesis region, then explain the linked sources, evidence, brief status,
  and up to three candidate ideas. Do not ask the user to update the brief or
  show a suggested next action.
- P2: successful intake that does not clear every P1 gate; keep it indexed and
  send only a concise archive receipt when policy enables P2 delivery.
- `intake_deferred`: normalization or required scoring did not complete; do not
  mislabel it as P2 or send an archive-success receipt.

Use `{baseDir}/references/watch-hooks.md` for watcher lifecycle, event and
notification schemas, dedupe, retry, ignored paths, and delivery rules.

## Shelf configuration

Each shelf uses `<folder>/clawshelf/clawshelf-config.json` as its single durable
configuration source. It contains the notification policy, structured Shelf
Plan, and `creativity_scoring` controls. Create it from inferred Shelf Plan values
on first use; malformed config is a blocking error until the user fixes it.
`novelty_preference` ranges from 0 (favor strong overlap) to 1 (favor
evidence-backed novelty). Advanced `threshold` and `min_confidence` remain the
P1 quality gates. `semantic_retrieval` controls the QMD fallback and
`semantic_candidate_target` controls its small candidate-set target.

## Failure behavior

- Continue the batch when one source, extractor, worker, refresh command, or
  notification fails.
- Never infer a summary from a filename or metadata alone.
- Retain normalized records when indexing fails.
- Keep provider credentials and channel-specific destination identifiers out
  of shelf data.
- Read `{baseDir}/references/harness-compatibility.md` only when adapting
  ClawShelf to a non-OpenClaw harness.
