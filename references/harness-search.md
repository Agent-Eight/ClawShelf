# Harness Search Reference

ClawShelf search is user-facing through the active harness, not through QMD
commands. The agent translates natural-language shelf requests into backend
retrieval, then returns source-cited answers.

## User-facing prompts

Use examples like these in final setup reports:

- "Search this shelf for a topic."
- "What does this shelf say about liquidity risk?"
- "Find contradictions about crowded trades."
- "Show sources for this claim."
- "What changed after I added these new files?"
- "What is the best next research direction?"

Do not show QMD commands unless the user explicitly asks for backend details.

## Backend behavior

- Use `qmd search` internally for lexical retrieval over LLM-curated keywords,
  RAG terms, and normalized records.
- Use `qmd query` internally for hybrid retrieval when available and useful.
- Use `qmd embed` only when semantic/vector retrieval is needed and the runtime
  allows the extra indexing step.
- If QMD is unavailable, read `clawshelf/normalized/*.md` directly and report
  that retrieval is degraded.

## Response shape

- Answer the user's question directly.
- Cite original sources or normalized records.
- Separate strong source-backed findings from speculation.
- Offer follow-up search angles as natural-language prompts, not commands.
