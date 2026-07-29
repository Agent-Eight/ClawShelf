# Security Policy

## Supported Versions

Security fixes are made on the current `main` branch and the latest `0.1.x`
release. Older versions are not supported.

## Reporting a Vulnerability

Please do not disclose vulnerabilities in a public issue, discussion, or pull
request. Report them privately through GitHub's private vulnerability-reporting
flow for `Agent-Eight/ClawShelf`. If that flow is unavailable, contact the
repository owner privately and include a minimal reproduction, affected version,
impact, and any practical mitigation.

Do not include real credentials, private documents, or sensitive personal data
in a report. Redact them or provide a synthetic reproduction instead.

## System and Scope

ClawShelf is a local-document research skill. It reads an explicit user-selected
folder and writes generated artifacts only below `<input_root>/clawshelf/`. It
can process local files, explicitly supplied URLs, OpenClaw runtime metadata,
and model-produced structured text. It invokes host-installed tools such as
OpenClaw, QMD, and `uv` through documented command paths.

This policy covers the published skill code, templates, scripts, manifests,
tests, and bundled example data in this repository.

## Threat Model and Trust Boundaries

- Local source files, supplied URLs, watcher events, model output, and command
  arguments may be attacker-controlled.
- The user selects the source folder and controls their OpenClaw, QMD, model,
  and operating-system environments.
- The host owns provider credentials, model access, and notification delivery;
  ClawShelf must not persist credentials or provider secrets in shelf data,
  logs, or generated artifacts.
- Generated HTML and Markdown are untrusted-output boundaries: source content
  must not become executable script or escape the intended artifact format.

## Security Invariants

- Never modify source documents; write only below `<input_root>/clawshelf/`.
- Fetch only URLs explicitly supplied by the user; do not crawl or discover
  further network targets.
- Keep credentials, tokens, private keys, and channel-specific secrets out of
  repository content, prompts, logs, configuration, and generated shelf data.
- Preserve source traceability without exposing more source content than the
  user selected for processing.
- Treat external command output, model output, and parsed documents as data;
  do not allow them to alter command structure or execute code.

## Reportable Findings and Severity Context

Please report issues that could plausibly cause:

- read or write access outside the selected folder or its `clawshelf/`
  workspace;
- execution of attacker-controlled code or commands through documents, URLs,
  model output, or watcher events;
- disclosure or persistence of credentials, private source content, or delivery
  identifiers beyond their documented scope;
- network access to targets that were not explicitly supplied by the user;
- script injection in generated overview HTML; or
- unauthorized notification delivery, route rebinding, or cross-session data
  disclosure.

Critical and high severity generally require credible code execution, credential
exposure, arbitrary file access, or access across a user or host boundary.
Medium severity includes bounded but meaningful disclosure, integrity, or
network-boundary violations. Low severity includes narrowly scoped issues with
limited practical impact.

## Out of Scope and Limitations

- Vulnerabilities solely in user-managed operating systems, OpenClaw, QMD,
  Python, model providers, or other dependencies are out of scope unless
  ClawShelf's integration or configuration materially enables the issue.
- Availability limits inherent to malformed, extremely large, encrypted, or
  image-only source documents are not security findings unless they bypass a
  ClawShelf security boundary.
- Do not treat a filename alone as trusted content; unsupported or unreadable
  inputs should be skipped rather than inferred.

## Compensating Controls

ClawShelf keeps generated data in a dedicated shelf subdirectory, uses explicit
folder selection, limits URL extraction to user-provided targets, stores only
non-secret delivery bindings, and ships pinned, license-noticed frontend assets.
These controls reduce risk but do not replace responsible disclosure or a
security review of changes to parsing, path handling, subprocess invocation,
network access, or notification delivery.
