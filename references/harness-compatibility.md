# Harness Compatibility

OpenClaw is the reference integration for ClawShelf. The same `SKILL.md`,
Python scripts, QMD CLI calls, and Markdown artifacts are intended to work in
Codex, Claude Code, OpenCode, and similar harnesses.

## Required capabilities

A compatible harness must provide:

- local filesystem reads and Markdown artifact writes;
- command execution for `uv` and `qmd`;
- an LLM able to reason over extracted content;
- a local-file reading path for the `llm_fallback` route;
- outbound network access for the URL extractor (only needed when a source is
  a URL; local-only collections work without it).

## Portability boundaries

| Concern | Portable behavior | Harness-specific behavior |
| --- | --- | --- |
| Skill workflow | `SKILL.md` and relative references | Discovery/invocation command |
| Extraction | `uv run --locked` scripts | Shell permission model |
| URL fetching | `urllib` inside `UrlExtractor`, no crawling | Network/proxy/allowlist policy |
| Retrieval | Global `qmd` CLI | Installation location/PATH |
| Fallback | `extraction_method: llm_fallback` | Native file-reading tools |

If a harness cannot access an unsupported source's real content, it must record
a skip warning instead of creating a summary.
