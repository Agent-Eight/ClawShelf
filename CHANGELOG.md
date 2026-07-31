# Changelog

All notable changes to ClawShelf are documented in this file.

## [Unreleased]

### Changed

- Reworked the interactive shelf overview as a 3D-only neuron map with orbit,
  dolly, depth-aware rendering, and draggable neurons.
- Load the four version-pinned rendering bundles from jsDelivr with SRI checks;
  the page now shows a localized offline notice when they are unavailable.

### Removed

- Bundled examples and fixture-only smoke tooling from the public release.
- The fixture-only `pypdf` dependency and lockfile entry.
- Vendored D3 and d3-force-3d bundles, which are no longer embedded in each
  generated overview.

## [0.1.0] - 2026-07-28

### Added

- Initial public release of the ClawShelf OpenClaw skill.
- Source-traceable document normalization, retrieval, knowledge-map, and
  proactive idea-generation workflows.
- Watcher-driven intake, local fixture tests, and a self-contained interactive
  shelf overview.
- MIT licensing, release documentation, and vendored-library notices.
