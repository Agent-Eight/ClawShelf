# ClawShelf

ClawShelf turns a folder of notes, PDFs, spreadsheets, and articles into an
ongoing research companion. It builds a source-traceable library, answers
questions across your files, highlights contradictions and gaps, and suggests
useful connections as the collection grows.

Your original files stay untouched. ClawShelf keeps everything it creates in a
separate `clawshelf/` folder beside your sources.

## Who ClawShelf is for

ClawShelf is useful when you have more material than you can reliably keep in
your head and want more than one-off summaries. For example:

- Researchers comparing papers, methods, evidence, and open questions.
- Product and market teams organizing reports, interviews, and meeting notes.
- Engineers tracking decisions, experiments, benchmarks, and technical risks.
- Writers building source-backed arguments and finding missing citations.
- Analysts watching a folder for new evidence, changed conclusions, or useful
  cross-source connections.

## What it does

- **Builds a durable source library.** Each inspected file becomes a searchable
  Markdown record with a summary, evidence, limitations, source path, and
  confidence.
- **Answers questions across files.** Search the whole shelf in natural language
  and receive concise answers grounded in the original material.
- **Connects related evidence.** Ask ClawShelf to explain agreements,
  contradictions, gaps, and relationships between sources.
- **Suggests next directions.** Generate briefs and source-backed ideas for what
  to investigate, test, read, or write next.
- **Keeps up with a growing folder.** New and changed files are processed in the
  background after you activate a shelf.
- **Creates an interactive overview.** Generate a self-contained local HTML map
  for exploring sources and their connections.

## Quick start

### 1. Check the prerequisites

You need:

- OpenClaw with permission to read your source folder and run local commands.
- Python 3.11 or later and [`uv`](https://docs.astral.sh/uv/).
- Node.js 22 or later for the search backend.
- On macOS, Homebrew SQLite (`brew install sqlite`) if prompted.

OpenClaw can offer to install `uv` and the search backend when the skill needs
them.

### 2. Install ClawShelf from GitHub

```bash
openclaw skills install git:https://github.com/Agent-Eight/ClawShelf.git --as clawshelf
openclaw skills info clawshelf
```

This installs ClawShelf for the current OpenClaw agent. Add `--global` to the
install command if you want it available from the shared skills directory.

Start a new OpenClaw session after installation so the skill and its commands
are discovered.

If you already downloaded the repository, you can install that local folder
instead:

```bash
openclaw skills install /path/to/ClawShelf --as clawshelf
```

### 3. Choose a folder of source material

Create or select a local folder containing the material you want ClawShelf to
work with:

```text
project-research/
├── meeting-notes.md
├── market-report.pdf
└── budget.xlsx
```

Use the source folder itself, not a `clawshelf/` subfolder.

### 4. Activate the shelf

In OpenClaw, run:

```text
/clawshelf use /absolute/path/to/project-research
```

ClawShelf will:

1. Set this as the shelf for the current session.
2. Create the shelf workspace if it does not exist.
3. Infer a starting research plan from the folder and your request.
4. Report files waiting to be processed.
5. Start watching the folder for new and changed files.

Initial processing continues in the background. ClawShelf will show a compact
status update and may ask you to confirm or adjust the inferred research plan.

### 5. Ask your first question

Use a slash command:

```text
/clawshelf search "What evidence supports the main recommendation?"
```

Or ask naturally:

```text
Compare the reports in this shelf. Summarize where they agree, where they
conflict, and what evidence is still missing.
```

## Everyday use

| What you want to do | Example |
| --- | --- |
| Search across sources | `/clawshelf search "evidence about liquidity risk"` |
| Explain a topic or claim | `/clawshelf explain "crowded trades"` |
| Create a synthesis brief | `/clawshelf brief "What should I investigate next?"` |
| Generate source-backed ideas | `/clawshelf ideas` |
| Refresh after changing files | `/clawshelf refresh` |
| Create the interactive map | `/clawshelf overview` |
| List indexed sources | `/clawshelf sources` |
| Check shelf health | `/clawshelf status` |
| Show the active folder | `/clawshelf pwd` |
| List known shelves | `/clawshelf folders` |

You can also describe the outcome you want in ordinary language. For example:

- “Find contradictions about customer retention.”
- “What changed after I added the latest report?”
- “Which claims have the strongest evidence?”
- “Turn these papers into a literature-review brief.”
- “Suggest the most promising next research direction.”

Most commands accept an optional folder. After `/clawshelf use`, you can
normally omit it for the rest of that session.

## When the folder changes

Activating a shelf starts its background watcher. When you add or change a
supported source, ClawShelf can send:

- A short confirmation that the source was archived.
- A richer update when the new material creates a useful, evidence-backed
  connection with the existing shelf.

Both types of updates are enabled by default. Advanced users can keep routine
archive updates in the shelf without receiving them as notifications; see the
[command reference](references/commands.md) for the notification setting.

Run `/clawshelf refresh` whenever you want to check for changes immediately.
Use `/clawshelf repair` if ClawShelf reports that a shelf is incomplete or
damaged.

## Supported sources

ClawShelf has built-in extraction for:

| Source | Notes |
| --- | --- |
| Markdown | `.md` files |
| Plain text | `.txt` files |
| PDF | Text is converted into section-aware Markdown |
| Excel workbooks | `.xlsx` files, including individual sheets |
| Web pages | Only URLs you explicitly provide |

Other readable local files may work through the active agent's file-reading
tools. ClawShelf skips files it cannot read instead of guessing from their
names.

## What ClawShelf creates

All generated content stays under `<your-folder>/clawshelf/`:

```text
project-research/
├── meeting-notes.md
├── market-report.pdf
├── budget.xlsx
└── clawshelf/
    ├── normalized/
    ├── clawshelf-metadata.md
    ├── clawshelf-brief.md
    └── clawshelf-overview.html
```

| Output | Purpose |
| --- | --- |
| `normalized/` | One source-traceable Markdown record for each processed source |
| `clawshelf-metadata.md` | Source inventory, topics, coverage, claims, and confidence |
| `clawshelf-brief.md` | Optional synthesis, contradictions, gaps, ideas, and next directions |
| `clawshelf-overview.html` | Optional interactive map generated by `/clawshelf overview` |

The brief is created only when synthesis is useful or requested. The overview
is generated only when you ask for it, opens locally, and does not need a web
server or an internet connection.

## Language and notifications

ClawShelf supports English and Chinese. Its default `auto` mode follows the
language of your latest message.

```text
/clawshelf language en
/clawshelf language zh
/clawshelf language auto
```

You can also add `--lang en`, `--lang zh`, or `--lang auto` to override a
single command.

Background updates are delivered through the OpenClaw agent and conversation
where you activated the shelf. ClawShelf stores routing information, but never
provider passwords, API keys, or access tokens, in the shelf.

## Privacy and safety

- Source files are read-only; ClawShelf does not edit, rename, move, or delete
  them.
- Generated files are written only inside the source folder's `clawshelf/`
  directory.
- URL extraction fetches only the exact pages you provide and does not crawl
  links.
- Local-only collections can stay local. Network access is needed only for
  user-provided URLs and any services used by the active agent.
- Answers and suggestions identify their supporting sources and distinguish
  evidence from speculation.

ClawShelf can support research and decision-making, but it is not a substitute
for professional legal, medical, or financial advice and should not make
autonomous high-stakes decisions.

## Known limitations

- Image-only or heavily scanned PDFs may need external OCR, especially for
  unsupported scripts or poor-quality scans.
- Password-protected, corrupted, or unsupported files may be skipped.
- Spreadsheet extraction reads workbook content but does not reproduce complex
  interactive Excel behavior.
- Web-page extraction does not sign in, bypass paywalls, or follow links.
- Generated summaries and ideas should be checked against the cited sources
  before important use.
- Other agent harnesses may use ClawShelf, but installation, command discovery,
  and local-file permissions vary by harness.

## Troubleshooting

### ClawShelf is not available after installation

Start a new OpenClaw session, then verify the installation:

```bash
openclaw skills info clawshelf
openclaw skills check
```

### A required tool is missing

Confirm that `uv` and Node.js 22 or later are installed. On macOS, install
Homebrew SQLite if requested:

```bash
brew install uv sqlite
```

ClawShelf's setup scripts install the compatible search backend when needed.

### ClawShelf is using the wrong folder

Select the exact source folder again:

```text
/clawshelf use /absolute/path/to/the/source-folder
```

Use `/clawshelf pwd` to confirm the active shelf or `/clawshelf folders` to see
known shelves.

### Files are missing from search

Run `/clawshelf status`, then `/clawshelf refresh`. Check that the files use a
supported format and that OpenClaw has permission to read them. If the status
reports a partial shelf, run `/clawshelf repair`.

### The interactive overview does not open from chat

Some chat channels block local `file://` links. Open the reported
`clawshelf-overview.html` path directly on the computer that owns the shelf, or
ask the agent to attach the HTML file.

## Documentation

- [Full command reference](references/commands.md)
- [Architecture and skill design](docs/skill-design.md)
- [Compatibility with other agent harnesses](references/harness-compatibility.md)
- [Idea-generation method](docs/idea-generation-method.md)
- [Release history](CHANGELOG.md)
- [Security and responsible disclosure](SECURITY.md)

## License

Copyright 2026 ClawShelf.

Licensed under the [MIT License](LICENSE). Third-party notices are listed in
[NOTICE](NOTICE).
