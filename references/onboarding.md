# Onboarding Reference

ClawShelf onboarding should feel like confirming a starting configuration, not
filling out a blank form. For quick onboarding, infer and prefill all five
Shelf Plan questions from the folder, files, and current request, then ask the
user to confirm or edit the prefilled result. Each question must include
selections and allow a custom free-form answer.

## Folder readiness

Onboarding is per folder. Before asking onboarding questions or generating new
artifacts, inspect the target folder itself.

- Ready folder: `<folder>/clawshelf/` exists, `clawshelf/normalized/` exists,
  `clawshelf/clawshelf-metadata.md` exists, and at least one normalized record
  exists unless the source folder genuinely has no supported files.
- Not onboarded: `<folder>/clawshelf/` is missing. Run onboard for that folder.
- Partial or broken: `clawshelf/` exists but required artifacts are missing,
  empty, or inconsistent. Run repair and rebuild only missing or invalid pieces.

Do not reuse onboarding state across folders. A user, agent, or chat may have
used ClawShelf before, but each folder needs its own readiness check. For
example, `/path/to/quant-trading`
already contains `clawshelf/`, so inspect readiness and skip onboard when its
artifacts are usable.

## Initialization procedure

Use this procedure only for a not-onboarded or partial folder. Normal daily
refresh, search, and watch work should return to `SKILL.md`.

1. Require a local collection root. Individual sources may include explicit
   URLs, but ClawShelf does not crawl or synchronize cloud storage.
2. Run `scripts/openclaw-use.py <folder>` for the normal OpenClaw entrypoint.
   It resolves accidental `clawshelf/` subdirectory inputs, checks readiness,
   quick-onboards new folders, and restarts one watcher for a ready folder.
3. For a new folder, list candidate sources, fingerprint their bytes, and
   preserve each original relative path or URL.
4. Extract Markdown and text directly. For PDF, XLSX, or URL input, run:

   ```bash
   uv run --locked --project {baseDir} python {baseDir}/scripts/extract-source.py <source-path-or-url>
   ```

5. For unsupported files, use harness file-reading tools only when they expose
   actual content. Mark such records `llm_fallback`; otherwise skip them with a
   limitation. Never summarize from a filename or metadata alone.
6. Create and validate one record per inspected source under
   `<folder>/clawshelf/normalized/` using
   `templates/normalized-record.md`. Do not write invalid or low-quality
   records.
7. Create `clawshelf/clawshelf-metadata.md` using
   `templates/metadata-table.md`.
8. Register the normalized directory with QMD idempotently. Follow
   `references/qmd-integration.md`; an already registered collection is not an
   error.
9. Create `clawshelf/clawshelf-brief.md` only when the user requests synthesis
   or the confirmed Shelf Plan makes proactive analysis useful.
10. Return a compact status card with the resolved folder, readiness,
    normalized-record count, watcher state, and suggested next action.

## Question set

| Field | Question | Suggested selections |
| --- | --- | --- |
| `domain_background` | What kind of work are you doing? | Basic science; industrial/product research; financial/investment research; engineering R&D; writing/knowledge work; custom |
| `work_direction` | What direction is this shelf supporting? | Literature review; idea discovery; project knowledge management; product/market research; experiment/design tracking; report writing; custom |
| `concrete_problem` | What should this shelf help solve first? | Find new research directions; organize and cite sources; compare competing views; track what changed after new files; identify gaps/risks; custom |
| `collection_pattern` | How will this shelf grow? | One-time batch; steadily growing shelf; project-by-project archive; fast-changing market/product watchlist; custom |
| `companion_mode` | How should ClawShelf behave? | Research secretary; product secretary; investment research assistant; engineering knowledge assistant; writing assistant; custom |

## Interaction rules

- Keep onboarding compact. In chat, batch the questions when the harness can
  show structured choices; otherwise show a compact five-line prefill summary
  and ask the user to confirm or edit it.
- Prefer quick onboarding for first use. Infer reasonable defaults from the
  folder name, source filenames, file types, and the user's latest request, then
  prefill all five Shelf Plan fields.
- Quick onboarding automatically accepts the inferred five-field plan and
  writes it to the shelf config; users may edit the JSON at any time.
- Mark unanswered fields as `unknown` instead of blocking quick setup.
- Prefer the user's own wording when they provide a custom answer.
- Persist inferred or user-edited answers in `<folder>/clawshelf/clawshelf-config.json`.
- Use selections to tune metadata, knowledge-map sections, search prompts, and
  idea-generation triggers.

## Onboarding modes

| Mode | When to use | Behavior |
| --- | --- | --- |
| Quick | Default for `/clawshelf use <folder>` when the folder is not onboarded | Automatically create the shelf and persist inferred Shelf Plan fields in `clawshelf-config.json`. |
| Default | User asks to configure the shelf or inference is weak | Ask the canonical question set with selections and custom answers. |
| Pro | User asks for detailed setup or strict tuning | Ask the canonical set plus any project-specific metadata, update-pattern, or companion-behavior choices needed for that shelf. |

For quick onboarding, show the complete prefilled Shelf Plan before or alongside
the status card:

- Domain/background
- Work direction
- Concrete problem
- Collection/update pattern
- Companion mode

Ask the user to confirm the five fields or reply with edits. The harness may
start deterministic setup immediately, but companion behavior should treat the
prefill as provisional until the user confirms or edits it.

After onboarding, return a small status card:

- Folder
- Status
- Normalized records
- Watcher state
- Suggested next question or action

## Mode guidance

| Mode | Metadata emphasis | Idea triggers |
| --- | --- | --- |
| Research secretary | Hypotheses, methods, evidence, limitations, unresolved questions | Theory tensions, method transfer, missing experiments, strongest next reading |
| Product secretary | User pain, scenarios, requirements, competitors, validation signals | Product gaps, roadmap conflicts, underserved users, validation plan |
| Investment research assistant | Thesis, signal, risk, data source, market structure | Regime change, flow/risk link, crowded trade warning, missing dataset |
| Engineering knowledge assistant | Decisions, designs, benchmarks, issues, dependencies | Tradeoff shift, technical debt, experiment plan, reusable component |
| Writing assistant | Arguments, citations, outline role, examples, counterpoints | Better structure, missing citation, strongest claim, weak section |
