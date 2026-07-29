# Vendored third-party JavaScript

The overview artifact (`clawshelf-overview.html`) inlines its rendering library so the
generated file opens and stays fully interactive with **no network access**. Nothing here is
modified from upstream — `d3.min.js` is byte-identical to what npm and jsDelivr serve, so its
provenance is a single hash check.

## d3 7.9.0

| | |
|---|---|
| File | `d3.min.js` (279,706 bytes) |
| Source | `https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js` |
| sha256 | `f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539` |
| npm integrity | `sha512-e1U46jVP+w7Iut8Jt8ri1YsPOvFpg46k+K8TpCb0P+zjCkjkPnV7WzfDJzMHy1LnA+wj5pLT1wjO901gLXeEhA==` |
| License | ISC — see `d3.LICENSE`, redistributed with the bundle |

The sha256 is pinned as `D3_SHA256` in
[`../overview_template.py`](../overview_template.py) and re-verified on **every** render;
a mismatch raises `OverviewError` rather than emitting a page with unverified code.

### Refetch / verify

```bash
curl -fsSL https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js -o scripts/clawshelf/vendor/d3.min.js
shasum -a 256 scripts/clawshelf/vendor/d3.min.js
```

### Upgrading

`D3_VERSION`, `D3_SHA256`, this file, and (if the scanner fires) the
`.skillspector-baseline.yaml` fingerprint all move together. Re-run
`uv run --locked python -m unittest tests.test_overview` — `test_vendored_d3_matches_its_pinned_hash`
and `test_rendered_html_has_no_external_subresources` are the guards.

### If this file is missing

A sparse or partial checkout without `d3.min.js` makes `generate_overview` raise
`OverviewError` (CLI exit code 3) instead of writing a broken page. Refetch with the command
above.

## d3-force-3d family (3.0.6 / 1.1.0 / 1.0.2)

Powers the optional "Switch to 3D (beta)" toggle in the overview page (billboarded arbors,
off by default — see [`docs/overview-3d-feasibility.md`](../../../docs/overview-3d-feasibility.md)).
Unlike D3 itself, none of these ship a source map to strip, and — critically — **load order
matters**: `d3-force-3d`'s browser build expects `d3.octree`/`d3.binaryTree` to already exist on
the shared `d3` global, so `octree` and `binarytree` must be concatenated before `force-3d`.
`force3d_source()` in [`../overview_template.py`](../overview_template.py) does this concatenation;
don't inline the three files as separate `<script>` tags in a different order.

All three are MIT-licensed, same author (Vasco Asturiano) — one shared
`d3-force-3d-family.LICENSE` covers all three rather than tripling identical boilerplate.

| | |
|---|---|
| `d3-force-3d.min.js` | 3.0.6, 10,794 bytes, sha256 `412b4aadc3218aa65de10b70ba3324dd365d4bf7a061299fa682f530e8506ee9` |
| `d3-octree.min.js` | 1.1.0, 7,234 bytes, sha256 `62c23034a7a7e9c3d5cb3118e108ac82ceffed0351f2d7b6400ddc66cd2643a2` |
| `d3-binarytree.min.js` | 1.0.2, 4,006 bytes, sha256 `34ee89660516611365de94ab44ff8e06d968f6bfb7b3772667d12793a4bc5b57` |

Each sha256 is pinned (`FORCE3D_SHA256`/`OCTREE_SHA256`/`BINARYTREE_SHA256`) and re-verified on
every render, same as D3.

### Refetch / verify

```bash
curl -fsSL https://cdn.jsdelivr.net/npm/d3-force-3d@3.0.6/dist/d3-force-3d.min.js -o scripts/clawshelf/vendor/d3-force-3d.min.js
curl -fsSL https://cdn.jsdelivr.net/npm/d3-octree@1.1.0/dist/d3-octree.min.js -o scripts/clawshelf/vendor/d3-octree.min.js
curl -fsSL https://cdn.jsdelivr.net/npm/d3-binarytree@1.0.2/dist/d3-binarytree.min.js -o scripts/clawshelf/vendor/d3-binarytree.min.js
shasum -a 256 scripts/clawshelf/vendor/d3-force-3d.min.js scripts/clawshelf/vendor/d3-octree.min.js scripts/clawshelf/vendor/d3-binarytree.min.js
```

### Upgrading

Same pattern as D3: the version/sha256 constants in `overview_template.py`, this file, and (if the
scanner fires) `.skillspector-baseline.yaml` move together. Re-run
`uv run --locked python -m unittest tests.test_overview` —
`test_vendored_d3_force3d_family_matches_its_pinned_hashes` is the guard.

### If these files are missing

Same failure mode as D3: `generate_overview` raises `OverviewError` rather than emitting a page
with unverified code. Refetch with the commands above.
