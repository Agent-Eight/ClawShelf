# Slash Command Reference

Use slash commands when the active harness supports command-style invocation.
Every command should also have a natural-language equivalent.

## Key commands

- `/clawshelf status [folder]`: check readiness and missing artifacts.
- `/clawshelf use <folder>`: primary first-run entrypoint; set the current
  working folder, create missing shelf structure, report pending sources, and
  ensure the watcher is running to reconcile them in the background.
- `/clawshelf pwd`: show the current working folder.
- `/clawshelf folders`: list known or recently used shelves.
- `/clawshelf onboard [folder]`: explicit setup command for a folder that is
  not onboarded.
- `/clawshelf refresh [folder]`: update an already ready shelf.
- `/clawshelf repair [folder]`: repair a partial/broken shelf.
- `/clawshelf search [folder] <query>`: answer with source-cited evidence.
- `/clawshelf graph [folder] [topic]`: build or update a keyword/topic graph.
- `/clawshelf explain [folder] <topic-or-claim>`: explain relationships between
  sources, topics, claims, contradictions, and evidence.
- `/clawshelf overview [folder]`: generate an interactive neuron/synapse map
  of the shelf as a local HTML file.
- `/clawshelf brief [folder] [question]`: generate synthesis and gaps.
- `/clawshelf ideas [folder]`: suggest next directions from the shelf.
- `/clawshelf sources [folder] [filter]`: list source and extraction coverage.
- `/clawshelf watch <folder>`: manually start a lightweight watcher that emits
  P1/P2 intake events when stable files are added or changed.
- `/clawshelf language <auto|en|zh>`: set response language.

`[folder]` means optional. Commands may omit it only when a current working
folder or exactly one known shelf makes the target unambiguous.

## Language mode

ClawShelf supports English and Chinese responses.

- Default language: `auto`, matching the user's latest message language.
- Explicit switch: `/clawshelf language <auto|en|zh>`.
- Per-command override: add `--lang auto`, `--lang en`, or `--lang zh`.
- Mixed-language groups: keep command acknowledgements short and use the
  selected language for the result.

Chinese aliases may be accepted by harnesses that support localized commands,
but the canonical command names remain English for portability.

## Working folder

Most commands accept an optional `<folder>` argument. Resolve the working folder
in this order:

1. Explicit `<folder>` argument in the command.
2. Current ClawShelf working folder for the chat/session.
3. The only known ClawShelf folder when exactly one exists.
4. Ask the user to choose/provide a folder.

Do not write files when multiple folders are possible and no folder is selected.
Read-only commands may explain the ambiguity and list candidate folders.

Recommended commands:

- `/clawshelf use <folder>`: set the current working folder for this
  chat/session. This is the recommended first command for users. In OpenClaw,
  run `scripts/openclaw-use.py <folder>` so the use command also checks
  readiness, returns the next action for new or partial folders, and
  auto-starts the watcher when the folder is ready and no watcher is running.
  The OpenClaw adapter automatically discovers the current session key from
  the command-logger record when the host does not inject one explicitly.
- `/clawshelf pwd`: show the current working folder.
- `/clawshelf folders`: list known or recently used ClawShelf folders.

The working folder is a convenience pointer, not proof that the folder is ready.
Always run Folder Readiness / Onboard Detection before onboard, refresh, repair,
search, graph, overview, explain, brief, or idea-generation work.
`/clawshelf use` also performs this readiness check before auto-starting watch.

## Core commands

`/clawshelf status [folder] [--lang auto|en|zh]`

- Runs Folder Readiness / Onboard Detection.
- Returns `ready`, `not_onboarded`, or `partial/broken`.
- Reports missing artifacts and the resolved working folder.
- Does not write files.

`/clawshelf use <folder> [--lang auto|en|zh] [--no-reset]`

- Sets the current working folder for the chat/session.
- Runs Folder Readiness / Onboard Detection.
- In OpenClaw, invokes `scripts/openclaw-use.py <folder>`.
- Persists the originating `agent`, canonical `session`, concrete `channel`,
  owner-DM `target`, and `account` under `delivery_binding` in
  `clawshelf-config.json`. The binding contains routing identifiers only, not
  provider credentials.
- If the folder is not onboarded, automatically runs quick onboarding. Infer a
  Shelf Plan when possible, prefill all five Shelf Plan fields, ask the user to
  confirm or edit the five-field result, keep unanswered fields as `unknown`,
  and continue setup.
- If shelf structure is missing, creates it without running normalization in
  the request path; pending sources are reconciled by the watcher.
- If the folder is ready, stops any existing watcher for that exact resolved
  shelf root, then starts `scripts/openclaw-watch-adapter.py` in the background.
  This keeps the watcher bound to the latest skill code, session key, delivery
  route, and watch policy.
- `--no-reset` is a diagnostic escape hatch: keep an existing watcher when one
  is already running and do not start a duplicate.
- If the user accidentally passes the generated `clawshelf/` directory, resolves
  the watched root to its parent shelf folder instead of onboarding
  `clawshelf/clawshelf/`.
- If `watch-state.json` exists but the recorded watcher process is gone or does
  not match the folder, treats it as stale and restarts the watcher.
- If multiple watcher processes exist for the same resolved shelf root, stops
  all of them and starts one fresh watcher.
- Reports a compact status card: folder, readiness state, normalized record
  count, watcher status (`running`, `missing`, `stale`, `reset_started`,
  `reset_failed`, or `restarted`), watched root, event directory, and suggested
  next action.

`/clawshelf reset <folder> [--lang auto|en|zh]`

- Restarts only the watcher for the resolved shelf root.
- In OpenClaw, invokes `scripts/openclaw-use.py <folder> --reset-only`.
- Reads `delivery_binding` from `clawshelf-config.json`, validates that its
  agent and channel match the canonical session, and starts the watcher with
  that exact route. This is how a user applies a manually edited binding.
- Does not run onboarding, repair, refresh, or normalization.
- Requires the folder to be ready. If the folder is `not_onboarded` or partial,
  return the readiness state and suggested next action instead of starting a
  watcher.
- Stops every watcher process matching the resolved shelf root, clears stale
  `watch-state.json`, starts one fresh watcher, and writes a new watch state.

`/clawshelf onboard [folder] [--lang auto|en|zh]`

- Initializes the resolved folder only when it is `not_onboarded`.
- If `folder` is omitted, use the working-folder resolution rules.
- If the folder is already ready, switch to `status` or suggest `refresh`.
- If the folder is partial/broken, switch to `repair` unless the user explicitly
  asks for a full rebuild.
- Prefer quick onboarding unless the user asks to configure every Shelf Plan
  field. Quick onboarding may infer values from folder names, filenames, file
  types, and the current request.

`/clawshelf refresh [folder] [--lang auto|en|zh]`

- Updates a ready shelf by detecting changed, new, or deleted files.
- Reuses normalized records whose `source_sha256` still matches.

`/clawshelf repair [folder] [--lang auto|en|zh]`

- Repairs a partial/broken shelf.
- Rebuilds only missing, empty, or invalid artifacts.

`/clawshelf search [folder] <query> [--lang auto|en|zh]`

- Searches the resolved shelf with natural language.
- Returns concise, cited answers from normalized records or original sources.
- If the folder is not ready, report the readiness state first.

`/clawshelf graph [folder] [topic] [--lang auto|en|zh]`

- Generates or updates the keyword/topic graph for the resolved shelf.
- Optional `topic` narrows the graph.
- Return the graph artifact path and a short interpretation.

`/clawshelf explain [folder] <topic-or-claim> [--lang auto|en|zh]`

- Explains relationships between sources, topics, claims, contradictions, and
  evidence.
- Separates source-backed findings from speculation.

## Useful supporting commands

`/clawshelf overview [folder] [--lang auto|en|zh]`

- Generates `<folder>/clawshelf/clawshelf-overview.html` by running
  `scripts/render-overview.py` against a ready shelf.
- Draws every valid normalized source as a **neuron**, with one dendrite
  branch per dendrite signal and one axon terminal per axon signal. Detail is
  adaptive: zoomed out shows soma and arbor silhouette only, zooming in or
  focusing a neuron reveals every branch and terminal individually, each
  hoverable with its own signal text and evidence.
- **Synapses** join two records' signals — axo-dendritic (one record's axon
  signal meets another's dendrite signal) or axo-axonic (two axon signals
  meet) — scored by type compatibility and shared evidence, so every synapse
  names the two signals it joined. Persisted P1 links that independently clear
  the shelf's configured score and confidence gates, retain a `p1_candidate`
  verdict, and contain evidence from both sources render as a stronger,
  distinctly colored *confirmed* class on top. Hidden weighted
  RAG-term/topic/keyword similarity links keep related sources close even
  without a synapse.
- Supports zoom, pan, drag, search, source/confidence/map-role/synapse-kind/
  idea filters, and neuron/synapse/signal evidence inspection.
- Rebuilds only when invoked and returns the artifact path, node count,
  synapse count, validated P1 edge count, warnings, an explicit `file_url`,
  and a complete `markdown_link`.
- Emit `markdown_link` verbatim as the clickable local artifact and `path` as
  the filesystem location. Never convert `/Users/...` into
  `https://users/...` or any other HTTP URL.
- If the channel blocks `file://` links, send the HTML through the channel's
  structured file-attachment tool using `path`; do not render fake linked text.
- It does not start a server or open the browser.
- Fully self-contained — no network access is needed to open it.

`/clawshelf brief [folder] [question] [--lang auto|en|zh]`

- Creates or refreshes `clawshelf-brief.md` with themes, contradictions, gaps,
  reusable ideas, and next directions.

`/clawshelf ideas [folder] [--lang auto|en|zh]`

- Proactive companion mode.
- Suggests new connections, changed conclusions, missing evidence, and the
  strongest next research directions.

`/clawshelf sources [folder] [filter] [--lang auto|en|zh]`

- Lists indexed sources, normalized records, extraction status, skipped files,
  and citation coverage.

`/clawshelf watch <folder> [--lang auto|en|zh]`

- Starts a foreground watcher for a local folder. In OpenClaw agents, the watch
  capability is automatically enabled when the skill is installed; users still
  provide the folder explicitly.
- Detects stable new or changed files and ignores `clawshelf/`, hidden files,
  virtual environments, VCS folders, bytecode, and common partial-download
  suffixes.
- Runs refresh/normalization behavior through the active host, compares the new
  file's normalized record with current shelf records, then writes a JSON event
  under `<folder>/clawshelf/events/`.
- Emits P1 for source-backed cross-file relationships that may create a new
  research spark. Emits P2 for intake-only changes.
- P1 and P2 notification delivery is host-defined by default. OpenClaw should use
  `scripts/openclaw-watch-adapter.py` to write `clawshelf.notification`
  records and deliver enabled notifications through `openclaw agent
  --agent <agent-id> --session-key <key> --deliver`, where the canonical
  `<key>` is the OpenClaw session that enabled the watcher through `/clawshelf
  use` and `<agent-id>` is parsed from that key. Agent, channel, session,
  owner-DM target, and account are one bound route; ClawShelf does not fall
  back to the skill path, a default agent, or `channel=last`. Set
  `notification_policy` to `p1_only` to keep P2 log-only.
- Stops with Ctrl-C. Do not install system services unless the user asks
  for that separate setup.

## Minimum command set

Implement these first:

- `/clawshelf status`
- `/clawshelf use`
- `/clawshelf pwd`
- `/clawshelf onboard`
- `/clawshelf refresh`
- `/clawshelf search`
- `/clawshelf graph`
- `/clawshelf overview`
- `/clawshelf explain`
