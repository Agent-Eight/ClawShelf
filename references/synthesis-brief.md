# Synthesis Brief Reference

Structure and discipline for the synthesis brief rendered from
`templates/synthesis-brief.md`.

## Sections

- `Scope` — document set, collection name, research question, date generated.
- `Shelf Plan` — user domain, direction, concrete problem, and companion mode
  when known.
- `Source Map` — overview of document clusters and notable sources.
- `Knowledge Map` — topics, methods/evidence, tensions, and gaps.
- `Core Themes` — recurring ideas with source references.
- `Contradictions And Tensions` — conflicts across sources, with evidence.
- `Gaps And Open Questions` — missing evidence, unresolved questions, next reading.
- `Reusable Concepts` — concepts, frameworks, methods, or definitions to reuse.
- `Idea Cards` — source-backed ideas or synergies.
- `What Changed` — how newly added files changed the shelf's understanding.
- `Best Next Direction` — the strongest source-backed recommended next move.
- `Speculative Leads` — clearly labeled lower-confidence ideas.

## Source-traceability rule

Every generated claim must carry a source reference. If a claim cannot be cited,
remove it or label it as speculation. Keep enough references for another agent or
human to audit the output.

## Proactive idea rule

An idea card should not be a generic suggestion. It needs a connection, source
evidence, missing evidence, next action, and confidence. If the shelf cannot
support a recommendation yet, say what evidence is missing instead of forcing an
idea.

## Watcher-managed P1 region

P1 watcher events maintain a marker-delimited region in
`clawshelf-brief.md`. The region contains deduplicated source-backed research
connections and candidate ideas. Watcher updates must preserve all content
outside the markers, use atomic replacement, and never expose normalized
Markdown paths as user-facing sources.
