"""The overview page: styles, renderer, and the vendored D3 bundle.

The generated artifact is a single self-contained file — the rendering library is
inlined from ``vendor/d3.min.js`` and verified against a pinned hash on every
render, so the page loads no external subresources and works with no network.

Kept separate from :mod:`clawshelf.overview` for two reasons: the page source is
large, and the "no ``.innerHTML``" invariant is asserted against
:data:`_APP_SCRIPT` alone — ``d3-selection`` implements ``selection.html()`` with
``innerHTML``, so a whole-file assertion would be checking upstream code instead
of ours.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import hashlib
import re


D3_VERSION = "7.9.0"
D3_SHA256 = "f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539"
D3_PATH = Path(__file__).resolve().parent / "vendor" / "d3.min.js"

FORCE3D_VERSION = "3.0.6"
FORCE3D_SHA256 = "412b4aadc3218aa65de10b70ba3324dd365d4bf7a061299fa682f530e8506ee9"
FORCE3D_PATH = Path(__file__).resolve().parent / "vendor" / "d3-force-3d.min.js"

OCTREE_VERSION = "1.1.0"
OCTREE_SHA256 = "62c23034a7a7e9c3d5cb3118e108ac82ceffed0351f2d7b6400ddc66cd2643a2"
OCTREE_PATH = Path(__file__).resolve().parent / "vendor" / "d3-octree.min.js"

BINARYTREE_VERSION = "1.0.2"
BINARYTREE_SHA256 = "34ee89660516611365de94ab44ff8e06d968f6bfb7b3772667d12793a4bc5b57"
BINARYTREE_PATH = Path(__file__).resolve().parent / "vendor" / "d3-binarytree.min.js"

_SOURCE_MAP_RE = re.compile(r"(?m)^//# sourceMappingURL=.*$")
_FORBIDDEN_TOKENS = ("</script", "__overview_data__", "__d3_source__", "__d3_force3d_source__")


def _vendored_source(path: Path, expected_sha256: str, label: str) -> str:
    """Read a vendored JS file, verified against its pinned hash.

    Shared by every vendored bundle (D3 itself and the d3-force-3d family) so
    each one gets the same hash check, sourcemap strip, and forbidden-token
    scan as the original D3-only implementation.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OSError(
            f"vendored {label} is missing or unreadable: {path} "
            "(see scripts/clawshelf/vendor/README.md to refetch it)"
        ) from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise ValueError(
            f"vendored {label} failed its pinned sha256 check: expected {expected_sha256}, got {digest}"
        )
    text = _SOURCE_MAP_RE.sub("", raw.decode("utf-8"))
    lowered = text.lower()
    if any(token in lowered for token in _FORBIDDEN_TOKENS):
        raise ValueError(f"vendored {label} contains a script terminator or template token")
    return text


@lru_cache(maxsize=1)
def d3_source() -> str:
    """Return the vendored D3 bundle, verified against its pinned hash."""
    return _vendored_source(D3_PATH, D3_SHA256, "D3")


@lru_cache(maxsize=1)
def force3d_source() -> str:
    """Return the vendored d3-octree + d3-binarytree + d3-force-3d bundle.

    Concatenated in dependency order: d3-force-3d's browser build expects
    ``d3.octree``/``d3.binaryTree`` to already exist on the shared ``d3``
    global before it loads (see vendor/README.md).
    """
    return "\n".join(
        (
            _vendored_source(OCTREE_PATH, OCTREE_SHA256, "d3-octree"),
            _vendored_source(BINARYTREE_PATH, BINARYTREE_SHA256, "d3-binarytree"),
            _vendored_source(FORCE3D_PATH, FORCE3D_SHA256, "d3-force-3d"),
        )
    )


def render_page(data_json: str) -> str:
    """Compose the page. Data is substituted first so it can never inject D3."""
    return (
        _HTML_TEMPLATE.replace("__OVERVIEW_DATA__", data_json)
        .replace("__D3_SOURCE__", d3_source())
        .replace("__D3_FORCE3D_SOURCE__", force3d_source())
    )


_APP_STYLE = r"""
:root {
  color-scheme: light;
  --bg: #fbfaf7;
  --panel: #ffffff;
  --field: #f7f6f2;
  --text: #1c2230;
  --muted: #6b7280;
  --line: #e4e2dc;
  --line-soft: #efedE8;
  --accent: #3563d6;
  --axo-dendritic: #7c5cff;
  --axo-axonic: #0ea5a4;
  --confirmed: #e0562d;
  --innovation: #c026d3;
  --consolidation: #0284c7;
  --relation: #d97706;
  --connection: #64748b;
  --shadow: 0 1px 2px rgba(28, 34, 48, .04), 0 12px 32px rgba(28, 34, 48, .07);
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}
.shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  padding: 0 clamp(14px, 2.6vw, 34px) clamp(14px, 2.6vw, 26px);
}
header {
  padding: 26px 2px 16px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
}
h1 {
  margin: 0 0 6px;
  font-family: var(--serif);
  font-weight: 500;
  font-size: clamp(25px, 3vw, 35px);
  letter-spacing: -.02em;
}
header p { margin: 0; color: var(--muted); max-width: 68ch; }
.stats {
  white-space: nowrap;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  display: flex;
  gap: 14px;
}
.stats b { color: var(--text); font-weight: 600; }

.controls {
  display: grid;
  grid-template-columns: minmax(190px, 1.8fr) repeat(5, minmax(118px, 1fr)) auto auto;
  gap: 8px;
  margin-bottom: 12px;
}
input, select, button {
  font: inherit;
  color: inherit;
  min-width: 0;
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--panel);
  transition: border-color .15s, box-shadow .15s;
}
input:focus-visible, select:focus-visible, button:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(53, 99, 214, .16);
}
button { cursor: pointer; font-weight: 500; white-space: nowrap; }
button:hover { border-color: #cfccc4; }

.workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 12px;
}
.canvas {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 16px;
  background:
    radial-gradient(1200px 700px at 50% 38%, #ffffff, #f4f2ee);
  box-shadow: var(--shadow);
  overflow: hidden;
  min-height: 460px;
}
#graph { display: block; width: 100%; height: 100%; cursor: grab; }
#graph:active { cursor: grabbing; }
.overlay {
  position: absolute;
  left: 50%;
  top: 18px;
  transform: translateX(-50%);
  padding: 7px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, .9);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 12.5px;
  pointer-events: none;
  max-width: 80%;
  text-align: center;
}
.overlay:empty { display: none; }
.overlay.error { color: #b3261e; border-color: #f0c8c4; }
.tip {
  position: absolute;
  z-index: 4;
  max-width: 280px;
  padding: 9px 11px;
  border-radius: 10px;
  background: rgba(255, 255, 255, .97);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  font-size: 12.5px;
  pointer-events: none;
}
.tip b { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); font-weight: 600; margin-bottom: 3px; }
.tip i { display: block; margin-top: 5px; color: var(--muted); font-style: normal; font-size: 11.5px; }
.tip.synapse-tip { max-width: 320px; }
.tip .end { padding: 3px 0; }
.tip .end + .end { margin-top: 7px; padding-top: 7px; border-top: 1px solid var(--line-soft); }
.tip .end b { margin-bottom: 2px; }
.tip .end-title { font-weight: 600; }
.tip .meta { margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--line-soft); color: var(--muted); font-size: 11.5px; }

aside {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel);
  box-shadow: var(--shadow);
  padding: 18px;
  overflow: auto;
  max-height: calc(100vh - 210px);
}
aside h2 {
  margin: 0 0 12px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted);
  font-weight: 600;
}
aside h3 {
  margin: 0 0 4px;
  font-family: var(--serif);
  font-weight: 500;
  font-size: 19px;
  letter-spacing: -.01em;
  line-height: 1.25;
}
.sect {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line-soft);
}
.sect > h4 {
  margin: 0 0 8px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted);
  font-weight: 600;
}
.field { display: flex; gap: 10px; margin: 3px 0; font-size: 13px; }
.field span:first-child { color: var(--muted); min-width: 84px; flex: none; }
.field span:last-child { word-break: break-word; }
.prompt { color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 5px; }
.chip {
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--field);
  border: 1px solid var(--line);
  font-size: 12px;
}
.card {
  border: 1px solid var(--line);
  border-left: 3px solid var(--muted);
  border-radius: 9px;
  padding: 9px 11px;
  margin-bottom: 7px;
  background: #fdfdfc;
  cursor: pointer;
  transition: border-color .15s, background .15s;
}
.card:hover, .card.on { background: #fff; border-color: #cfccc4; }
.card.axon { border-left-color: var(--confirmed); }
.card.dendrite { border-left-color: var(--accent); }
.card .kind { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); font-weight: 600; }
.card .body { margin: 3px 0; }
.card .ev { font-size: 12px; color: var(--muted); }
.bars { display: grid; gap: 5px; }
.bar { display: grid; grid-template-columns: 104px 1fr 26px; gap: 8px; align-items: center; font-size: 12px; }
.bar span:first-child { color: var(--muted); }
.bar span:last-child { text-align: right; font-variant-numeric: tabular-nums; }
.bar .track { height: 6px; border-radius: 3px; background: var(--field); overflow: hidden; }
.bar .fill { height: 100%; border-radius: 3px; background: var(--accent); }
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .03em;
  border: 1px solid currentColor;
  margin-right: 5px;
}
.badge.axo_dendritic { color: var(--axo-dendritic); }
.badge.axo_axonic { color: var(--axo-axonic); }
.badge.confirmed { color: var(--confirmed); }
.badge.computed { color: var(--muted); }
.num { font-variant-numeric: tabular-nums; }
.conn-filter { display: flex; gap: 6px; margin: 8px 0 4px; }
.conn-filter button {
  flex: 1;
  padding: 6px 8px;
  font-size: 12px;
  border-radius: 999px;
  background: var(--field);
}
.conn-filter button.on { background: var(--accent); border-color: var(--accent); color: #fff; }

.legend {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 22px;
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel);
  font-size: 12.5px;
}
.legend h2 { margin: 0; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); font-weight: 600; }
.swatches { display: flex; flex-wrap: wrap; gap: 8px 16px; }
.sw { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); }
.sw i { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
.sw i.line { width: 22px; height: 0; border-radius: 0; border-top: 2px solid currentColor; }
.sw i.dash { width: 22px; height: 0; border-radius: 0; border-top: 2px dashed currentColor; }

/* ---- graph ---- */
.field-bg { fill: url(#dots); }
.neuron { cursor: pointer; }
.soma {
  stroke: #ffffff;
  stroke-width: 2;
  transition: filter .15s;
}
.soma-ring { fill: none; stroke: rgba(15, 23, 42, .10); stroke-width: 1; }
.isolate .soma-ring { stroke-dasharray: 3 3; stroke: rgba(15, 23, 42, .22); }
.dendrite-branch { fill: none; stroke: #9aa3b2; stroke-width: 1.1; stroke-linecap: round; }
.axon-trunk { fill: none; stroke: #5b6472; stroke-width: 1.5; stroke-linecap: round; }
.branchlet { fill: none; stroke: #5b6472; stroke-width: 1.1; stroke-linecap: round; }
.bouton { stroke: #ffffff; stroke-width: 1; }
.dtip { fill: #ffffff; stroke-width: 1.3; }
.silhouette { stroke: none; opacity: .09; }
.nlabel {
  font-size: 11px;
  fill: #414a5b;
  text-anchor: middle;
  paint-order: stroke;
  stroke: rgba(255, 255, 255, .92);
  stroke-width: 3.5;
  stroke-linejoin: round;
  pointer-events: none;
}
.synapse { fill: none; stroke-linecap: round; }
.synapse.axo_dendritic { stroke: var(--axo-dendritic); }
.synapse.axo_axonic { stroke: var(--axo-axonic); stroke-dasharray: 4 3; }
.synapse.faint { stroke-width: .8 !important; stroke-opacity: .18 !important; }
.cleft { stroke: #ffffff; stroke-width: 1; }
.pulse { fill: none; stroke-linecap: round; stroke-width: 3; opacity: 0; pointer-events: none; }
.pulse.run { opacity: 1; animation: travel var(--dur, 900ms) cubic-bezier(.35, 0, .45, 1) forwards; }
@keyframes travel {
  from { stroke-dashoffset: 16; }
  to { stroke-dashoffset: calc(-1 * var(--len, 300px)); }
}
/* the receiving soma brightens — never resizes, which reads as jitter */
.flash { animation: flash 340ms ease-out; }
@keyframes flash {
  0%, 100% { filter: none; }
  35% { filter: brightness(1.32) saturate(1.35) drop-shadow(0 0 9px rgba(28, 34, 48, .3)); }
}
.selected .soma { filter: drop-shadow(0 0 7px rgba(53, 99, 214, .45)); }
.synapse.selected { stroke-opacity: 1 !important; stroke-width: 3.4 !important; }
.synapse.hover { stroke-opacity: 1 !important; }
.hit { fill: none; stroke: transparent; stroke-width: 14; pointer-events: stroke; cursor: pointer; }
.hit.dim { pointer-events: none; }
.dim { opacity: .08; }
.branch-focus { stroke-width: 2.6 !important; }

/* level of detail — a terminal that carries a synapse (.live) always stays
   visible, so no synapse is ever drawn from an invisible endpoint */
.lod-far .branchlet, .lod-far .bouton, .lod-far .dtip,
.lod-far .dendrite-branch, .lod-far .axon-trunk, .lod-far .nlabel { display: none; }
/* on a small shelf the labels are the point, so keep them when zoomed out */
.lod-far.sparse .nlabel { display: block; }
.lod-mid .branchlet, .lod-mid .bouton, .lod-mid .dtip { display: none; }
.lod-far .live, .lod-mid .live { display: block; }
.lod-far .live.branchlet, .lod-far .live.axon-trunk, .lod-far .live.dendrite-branch { display: block; }
.lod-mid .silhouette, .lod-near .silhouette { display: none; }
.lod-far .neuron.focused .branchlet, .lod-far .neuron.focused .bouton,
.lod-far .neuron.focused .dtip, .lod-far .neuron.focused .dendrite-branch,
.lod-far .neuron.focused .axon-trunk, .lod-far .neuron.focused .nlabel,
.lod-mid .neuron.focused .branchlet, .lod-mid .neuron.focused .bouton,
.lod-mid .neuron.focused .dtip { display: block; }
.lod-far .neuron.focused .silhouette { display: none; }

@media (prefers-reduced-motion: reduce) {
  .pulse { display: none; }
  .pulse, .flash, .soma, .synapse { animation: none !important; transition: none !important; }
  .synapse.active { stroke-width: 3px !important; stroke-opacity: 1 !important; }
}
@media (max-width: 1080px) {
  .workspace { grid-template-columns: minmax(0, 1fr); }
  aside { max-height: none; }
  .canvas { min-height: 62vh; }
}
@media (max-width: 700px) {
  .controls { grid-template-columns: 1fr 1fr; }
  header { flex-direction: column; align-items: flex-start; gap: 10px; }
}
"""


_APP_SCRIPT = r"""
(function () {
  "use strict";

  var overlay = document.getElementById("overlay");
  var data = null;
  try {
    data = JSON.parse(document.getElementById("overview-data").textContent);
  } catch (err) {
    overlay.textContent = "Overview data could not be parsed.";
    overlay.classList.add("error");
    return;
  }
  var ui = data.ui || {};

  try {
    boot();
  } catch (err) {
    overlay.textContent = (ui.render_error || "Render failed") + " " + err;
    overlay.classList.add("error");
  }

  function boot() {
    var ROLE_COLORS = {
      "background": "#8b93a3",
      "method": "#3563d6",
      "evidence": "#0f9a72",
      "contradiction": "#d5453f",
      "gap": "#e08a17",
      "idea seed": "#8b5cf6",
      "benchmark": "#0a8ba3",
      "unknown": "#a8adb7"
    };
    var IDEA_COLORS = {
      "innovation": "#c026d3",
      "consolidation": "#0284c7",
      "relation_candidate": "#d97706",
      "connection_candidate": "#64748b"
    };
    var TAU = Math.PI * 2;
    var DEG = 180 / Math.PI;

    // billboarded-3D state (see docs/overview-3d-feasibility.md): arbors stay the
    // exact flat 2D shapes buildAnatomy already draws, only the soma position and
    // camera become 3D. Off by default -- an explicit, reversible toggle.
    var mode3d = false;
    var cam = { rx: -0.35, ry: 0.6, dist: 900 };
    // the point the camera orbits around and looks at. Recomputed every 3D
    // tick as the live centroid of the node cluster (see tick3d) rather than
    // assumed to be the world origin -- the 2D-seeded x/y positions start out
    // centered on the SVG viewport (roughly width/2,height/2), and the weak
    // recentering force in ensureSimulation3d takes many ticks to pull them
    // toward 0,0, if it ever fully does. Orbiting around a fixed origin while
    // the visible cluster sits somewhere else is what made rotation look like
    // a wide, off-axis swing instead of a turn-in-place.
    var camTarget = { x: 0, y: 0, z: 0 };

    // ---------- text ----------
    setText("ui-title", ui.title);
    setText("ui-subtitle", ui.subtitle);
    document.title = ui.title || document.title;
    var search = document.getElementById("search");
    search.setAttribute("placeholder", ui.search || "");
    search.setAttribute("aria-label", ui.search || "");
    setText("fit", ui.fit);
    setText("reset", ui.reset);
    setText("mode-3d", ui.mode_2d);
    setText("inspector-title", ui.inspector);
    setText("legend-title", ui.anatomy);

    var stats = data.stats || {};
    var statsEl = document.getElementById("stats");
    addStat(statsEl, stats.nodes, ui.neurons);
    addStat(statsEl, stats.signals, ui.signals);
    addStat(statsEl, stats.synapses, ui.synapses);
    if (stats.confirmed) { addStat(statsEl, stats.confirmed, ui.confirmed); }

    // ---------- model ----------
    var nodes = (data.nodes || []).map(function (n) {
      var copy = Object.assign({}, n);
      buildAnatomy(copy);
      return copy;
    });
    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });

    var signalIndex = {};
    nodes.forEach(function (n) {
      n.axon.concat(n.dendrite).forEach(function (s) { signalIndex[s.id] = { signal: s, node: n }; });
    });

    var synapses = (data.synapses || []).filter(function (s) {
      return byId[s.source] && byId[s.target];
    }).map(function (s) { return Object.assign({}, s); });

    synapses.forEach(function (s) {
      var pre = s.direction === "source_to_target" ? s.source : s.target;
      s.preNode = pre;
      s.postNode = pre === s.source ? s.target : s.source;
      s.preSignal = pre === s.source ? s.source_signal : s.target_signal;
      s.postSignal = pre === s.source ? s.target_signal : s.source_signal;
      [s.source, s.target].forEach(function (id) {
        var n = byId[id];
        n.synapseList = n.synapseList || [];
        n.outgoing = n.outgoing || [];
        n.incoming = n.incoming || [];
        n.synapseList.push(s);
      });
      byId[s.preNode].outgoing.push(s);
      byId[s.postNode].incoming.push(s);
    });

    var totalSignals = stats.signals || 0;
    var LIGHT = nodes.length > 400 || totalSignals > 4000;

    // ---------- geometry ----------
    function buildAnatomy(n) {
      var seed = parseInt(n.id.slice(-4), 16);
      if (!isFinite(seed)) { seed = 0; }
      n.theta = (seed / 65536) * TAU;
      // Axon signals are what a node provides to others, so axon-heavy nodes
      // read visually as more of a "source" than dendrite-heavy ones with the
      // same total signal count.
      var AXON_SIZE_WEIGHT = 1.75;
      var DENDRITE_SIZE_WEIGHT = 1.0;
      n.r = Math.max(11, Math.min(26, 11 + 3 * Math.sqrt(
        AXON_SIZE_WEIGHT * n.axon.length + DENDRITE_SIZE_WEIGHT * n.dendrite.length
      )));
      n.anchors = {};
      var bow = (seed & 1) ? 1 : -1;
      var tips = [];

      // axon: trunk along +x in the canonical frame, boutons fanned at its tip
      var axonCount = n.axon.length;
      if (axonCount) {
        var L = n.r + 52 + 7 * axonCount;
        var mx = (n.r + L) / 2;
        n.axonPath = "M" + fmt(n.r) + ",0Q" + fmt(mx) + "," + fmt(0.18 * L * bow) + " " + fmt(L) + ",0";
        var spread = (52 / DEG) * Math.min(1, axonCount / 3);
        n.boutons = n.axon.map(function (s, k) {
          var a = axonCount === 1 ? 0 : 2 * spread * ((k + 0.5) / axonCount - 0.5);
          var len = 16 + (k % 3) * 5;
          var bx = L + len * Math.cos(a);
          var by = len * Math.sin(a);
          n.anchors[s.id] = { dx: bx, dy: by, angle: a };
          tips.push([bx, by]);
          return { id: s.id, signal: s, x: bx, y: by, stem: "M" + fmt(L) + ",0L" + fmt(bx) + "," + fmt(by) };
        });
      } else {
        n.axonPath = null;
        n.boutons = [];
      }

      // dendrites: fanned over the opposite hemisphere
      var dCount = n.dendrite.length;
      n.dendrites = n.dendrite.map(function (s, j) {
        var a = Math.PI + (200 / DEG) * (dCount === 1 ? 0 : (j + 0.5) / dCount - 0.5);
        var len = n.r + 30 + (j % 3) * 6;
        var ca = Math.cos(a);
        var sa = Math.sin(a);
        var sx = n.r * ca;
        var sy = n.r * sa;
        var tx = len * ca;
        var ty = len * sa;
        var px = -sa;
        var py = ca;
        var w = (j % 2 ? 1 : -1) * (5 + (j % 3) * 2);
        var c1x = sx + (tx - sx) * 0.4 + px * w;
        var c1y = sy + (ty - sy) * 0.4 + py * w;
        var c2x = sx + (tx - sx) * 0.78 - px * w * 0.6;
        var c2y = sy + (ty - sy) * 0.78 - py * w * 0.6;
        var d = "M" + fmt(sx) + "," + fmt(sy) + "C" + fmt(c1x) + "," + fmt(c1y) +
                " " + fmt(c2x) + "," + fmt(c2y) + " " + fmt(tx) + "," + fmt(ty);
        // bifurcation twiglets in the outer third, kept shorter than the
        // remaining trunk so they read as branches rather than arrowheads
        var bx = sx + (tx - sx) * 0.62;
        var by = sy + (ty - sy) * 0.62;
        var tw = len * 0.22;
        var twig = "M" + fmt(bx) + "," + fmt(by) + "L" + fmt(bx + tw * Math.cos(a - 0.62)) + "," + fmt(by + tw * Math.sin(a - 0.62)) +
                   "M" + fmt(bx) + "," + fmt(by) + "L" + fmt(bx + tw * Math.cos(a + 0.62)) + "," + fmt(by + tw * Math.sin(a + 0.62));
        n.anchors[s.id] = { dx: tx, dy: ty, angle: a };
        tips.push([tx, ty]);
        return { id: s.id, signal: s, x: tx, y: ty, path: d, twig: twig };
      });

      var reach = n.r;
      tips.forEach(function (p) { reach = Math.max(reach, Math.sqrt(p[0] * p[0] + p[1] * p[1])); });
      n.extent = reach + 14;
      n.silhouette = tips.length >= 3 ? hullPath(tips) : null;
    }

    function hullPath(points) {
      var sorted = points.slice().sort(function (a, b) {
        return Math.atan2(a[1], a[0]) - Math.atan2(b[1], b[0]);
      });
      return d3.line().curve(d3.curveCatmullRomClosed.alpha(0.6))(sorted);
    }

    function fmt(v) { return Math.round(v * 10) / 10; }

    // ---------- svg ----------
    var svg = d3.select("#graph");
    var canvas = document.querySelector(".canvas");
    var width = canvas.clientWidth || 960;
    var height = canvas.clientHeight || 620;
    svg.attr("viewBox", "0 0 " + width + " " + height);

    var defs = svg.append("defs");
    var pattern = defs.append("pattern")
      .attr("id", "dots").attr("width", 26).attr("height", 26)
      .attr("patternUnits", "userSpaceOnUse");
    pattern.append("circle").attr("cx", 1).attr("cy", 1).attr("r", 1)
      .attr("fill", "#1c2230").attr("opacity", 0.05);
    svg.append("rect").attr("class", "field-bg").attr("width", "100%").attr("height", "100%");

    var viewport = svg.append("g").attr("class", "viewport lod-mid");
    var synapseLayer = viewport.append("g");
    var pulseLayer = viewport.append("g");
    var hitLayer = viewport.append("g");
    var neuronLayer = viewport.append("g");

    var zoom = d3.zoom().scaleExtent([0.15, 6])
      .filter(function (event) {
        // Plain wheel zooms when the page itself has nothing to scroll (the
        // normal desktop layout). Once the page overflows — narrow windows,
        // where the inspector stacks below — the wheel scrolls the page and
        // zooming needs a modifier, so the graph never traps the scroll.
        if (event.type !== "wheel") { return !event.button; }
        if (document.documentElement.scrollHeight <= window.innerHeight + 2) { return true; }
        return event.ctrlKey || event.metaKey;
      })
      .on("zoom", function (event) {
        viewport.attr("transform", event.transform);
        applyTier(event.transform.k);
      });
    svg.call(zoom);

    // ---------- synapses ----------
    // Visual layers are purely decorative — their strokes are too thin to
    // reliably hover or click. A single invisible wide-stroke "hit" layer
    // (below) carries all pointer/keyboard interaction and highlights the
    // matching visible path.
    // One visual family for every synapse: color is by kind (axo_dendritic /
    // axo_axonic) only -- confirmed vs. computed no longer gets its own
    // color/glow (that's still available as data on s["class"] for the
    // inspector/tooltip/filter, just not a separate line style). Strength
    // (width + opacity) is driven by score instead. score is the same 0-21
    // IdeaCandidate.total_score scale for both classes (overview_synapses.py),
    // so one normalization works for all synapses.
    function scoreStrength(score) {
      return Math.max(0, Math.min(1, (score || 0) / 20));
    }

    var synapseSel = synapseLayer.selectAll("path")
      // paint highest-score synapses last (on top), since they no longer get
      // a separate layer to sit above the rest
      .data(synapses.slice().sort(function (a, b) { return a.score - b.score; }), key)
      .join("path")
      .attr("class", function (s) {
        return "synapse " + s.kind + (s.idea_type === "connection_candidate" ? " faint" : "");
      })
      .attr("stroke-width", function (s) { return 1.2 + scoreStrength(s.score) * 2.4; })
      .attr("stroke-opacity", function (s) { return 0.28 + scoreStrength(s.score) * 0.57; });

    var hitSel = hitLayer.selectAll("path")
      .data(synapses, key)
      .join("path")
      .attr("class", "hit")
      .attr("tabindex", 0)
      .attr("role", "button")
      .attr("aria-label", synapseLabel)
      .on("click", function (event, s) { event.stopPropagation(); selectSynapse(s); })
      .on("keydown", function (event, s) { if (isEnter(event)) { event.preventDefault(); selectSynapse(s); } })
      .on("mouseenter", function (event, s) { setSynapseHover(s, true); showSynapseTip(event, s); })
      .on("mousemove", function (event, s) { showSynapseTip(event, s); })
      .on("mouseleave", function (event, s) { setSynapseHover(s, false); hideTip(); });

    var allSynapseSel = function () { return synapseLayer.selectAll("path").nodes(); };

    function key(s) { return s.id; }
    function synapseLabel(s) {
      // still spoken/informational for accessibility even though the class
      // no longer gets a distinct line color -- see the comment on synapseSel
      return (s["class"] === "confirmed" ? ui.confirmed : ui[s.kind]) + ": " +
        byId[s.source].title + " / " + byId[s.target].title;
    }

    function setSynapseHover(s, on) {
      synapseSel.filter(function (d) { return d === s; }).classed("hover", on);
    }

    // ---------- neurons ----------
    var neuronSel = neuronLayer.selectAll("g.neuron")
      .data(nodes, function (n) { return n.id; })
      .join("g")
      .attr("class", function (n) { return "neuron" + (n.isolate ? " isolate" : ""); })
      .attr("tabindex", 0)
      .attr("role", "button")
      .attr("aria-label", function (n) { return n.title; })
      .on("click", function (event, n) { event.stopPropagation(); selectNode(n); })
      .on("keydown", function (event, n) { if (isEnter(event)) { event.preventDefault(); selectNode(n); } })
      .on("mouseenter", function (event, n) { focusNeuron(n, true); })
      .on("mouseleave", function (event, n) { focusNeuron(n, false); });

    neuronSel.each(function (n) {
      var g = d3.select(this);
      var color = roleColor(n.map_role);
      var arbor = g.append("g").attr("class", "arbor")
        .attr("transform", "rotate(" + fmt(n.theta * DEG) + ")");

      if (n.silhouette) {
        arbor.append("path").attr("class", "silhouette").attr("d", n.silhouette).attr("fill", color);
      }
      n.dendrites.forEach(function (b) {
        var live = b.signal.synapse_count > 0 ? " live" : "";
        arbor.append("path").attr("class", "dendrite-branch" + live).attr("d", b.path);
        if (!LIGHT) {
          arbor.append("path").attr("class", "branchlet").attr("d", b.twig);
        }
      });
      if (n.axonPath) {
        var axonLive = n.axon.some(function (s) { return s.synapse_count > 0; }) ? " live" : "";
        arbor.append("path").attr("class", "axon-trunk" + axonLive).attr("d", n.axonPath);
      }
      if (!LIGHT) {
        n.boutons.forEach(function (b) {
          var live = b.signal.synapse_count > 0 ? " live" : "";
          arbor.append("path").attr("class", "branchlet" + live).attr("d", b.stem);
          arbor.append("circle").attr("class", "bouton" + live)
            .attr("cx", b.x).attr("cy", b.y).attr("r", 3.4).attr("fill", color)
            .attr("data-signal", b.id)
            .on("mouseenter", function (event) { showTip(event, b.signal); })
            .on("mouseleave", hideTip)
            .on("click", function (event) { event.stopPropagation(); selectNode(n, b.id); });
        });
        n.dendrites.forEach(function (b) {
          var live = b.signal.synapse_count > 0 ? " live" : "";
          arbor.append("circle").attr("class", "dtip" + live)
            .attr("cx", b.x).attr("cy", b.y).attr("r", 2.6).attr("stroke", color)
            .attr("data-signal", b.id)
            .on("mouseenter", function (event) { showTip(event, b.signal); })
            .on("mouseleave", hideTip)
            .on("click", function (event) { event.stopPropagation(); selectNode(n, b.id); });
        });
      }
      g.append("circle").attr("class", "soma-ring").attr("r", n.r + 2.5);
      g.append("circle").attr("class", "soma").attr("r", n.r).attr("fill", color);
      g.append("text").attr("class", "nlabel").attr("y", n.r + 14).text(truncate(n.title, 42));
    });

    var arborSel = neuronSel.select("g.arbor");

    // ---------- forces ----------
    var pairLinks = {};
    synapses.forEach(function (s) {
      var k = s.source + "|" + s.target;
      var entry = pairLinks[k];
      if (!entry) {
        entry = pairLinks[k] = { source: s.source, target: s.target, strength: 0, confirmed: false };
      }
      entry.strength += s.strength;
      entry.confirmed = entry.confirmed || s["class"] === "confirmed";
    });
    var forceLinks = Object.keys(pairLinks).map(function (k) { return pairLinks[k]; })
      .concat((data.similarity_links || []).filter(function (l) {
        return byId[l.source] && byId[l.target];
      }).map(function (l) {
        return { source: l.source, target: l.target, similarity: true, weight: l.weight };
      }));

    var simulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(forceLinks).id(function (n) { return n.id; })
        .distance(function (l) {
          if (l.similarity) { return 80 + (1 - l.weight) * 120; }
          // the anchors sit at the arbor tips, so the somata need more than the
          // sum of the extents or the two arbors interleave
          var pad = l.confirmed ? 40 : 76;
          return l.source.extent + l.target.extent + pad;
        })
        .strength(function (l) {
          return l.similarity ? 0.10 : Math.min(0.5, l.strength);
        }))
      .force("charge", d3.forceManyBody().strength(function (n) { return -180 - 6 * (n.signal_count || 0); }))
      .force("collide", d3.forceCollide().radius(function (n) { return n.extent; }).iterations(2))
      .force("x", d3.forceX(width / 2).strength(0.02))
      .force("y", d3.forceY(height / 2).strength(0.02))
      .alphaDecay(0.028)
      .on("tick", tick)
      .on("end", function () { orientArbors(); fitGraph(); });

    function tick() {
      neuronSel.attr("transform", function (n) { return "translate(" + fmt(n.x) + "," + fmt(n.y) + ")"; });
      redrawSynapses();
    }

    function redrawSynapses() {
      synapseSel.attr("d", synapsePath);
      hitSel.attr("d", synapsePath);
    }

    function anchor(node, signalId) {
      if (!signalId || !node.anchors[signalId]) {
        return { x: node.x + node.r * Math.cos(node.theta), y: node.y + node.r * Math.sin(node.theta), a: node.theta };
      }
      var local = node.anchors[signalId];
      var c = Math.cos(node.theta);
      var s = Math.sin(node.theta);
      return {
        x: node.x + local.dx * c - local.dy * s,
        y: node.y + local.dx * s + local.dy * c,
        a: local.angle + node.theta
      };
    }

    function synapsePath(s) {
      // preNode/postNode (not source/target, which are just a canonical id
      // ordering) so the drawn curve -- and the traveling-pulse animation
      // along it -- always runs from the firing side to the receiving side.
      var a = anchor(byId[s.preNode], s.preSignal);
      var b = anchor(byId[s.postNode], s.postSignal);
      // pull back along the tangents so a visible synaptic cleft remains
      var p1x = a.x + 3 * Math.cos(a.a);
      var p1y = a.y + 3 * Math.sin(a.a);
      var p2x = b.x + 3 * Math.cos(b.a);
      var p2y = b.y + 3 * Math.sin(b.a);
      var dist = Math.hypot(p2x - p1x, p2y - p1y);
      // clamped so a long synapse approaches head-on instead of looping wide
      var k = Math.min((s.kind === "axo_axonic" ? 0.22 : 0.35) * dist, 55);
      return "M" + fmt(p1x) + "," + fmt(p1y) +
        "C" + fmt(p1x + k * Math.cos(a.a)) + "," + fmt(p1y + k * Math.sin(a.a)) +
        " " + fmt(p2x + k * Math.cos(b.a)) + "," + fmt(p2y + k * Math.sin(b.a)) +
        " " + fmt(p2x) + "," + fmt(p2y);
    }

    function orientArbors() {
      // Point the axon at the strongest neuron this one drives, and the
      // dendritic field at the strongest neuron driving it. When both exist the
      // arbor takes the bisector, which is what stops synapses from having to
      // loop around a soma to reach a dendrite on its far side.
      nodes.forEach(function (n) {
        var out = strongest(n, true);
        var into = strongest(n, false);
        var vx = 0;
        var vy = 0;
        if (out) { vx += Math.cos(out); vy += Math.sin(out); }
        // dendrites face the driver, so the axon points away from it — but only
        // as a tiebreaker, or reciprocal pairs cancel each other out
        if (into) { vx -= 0.4 * Math.cos(into); vy -= 0.4 * Math.sin(into); }
        if (vx === 0 && vy === 0) { return; }
        n.theta = Math.atan2(vy, vx);
      });

      function strongest(n, outgoing) {
        var best = null;
        (n.synapseList || []).forEach(function (s) {
          var isPre = s.preNode === n.id;
          if (isPre !== outgoing) { return; }
          if (!best || s.strength > best.strength) { best = s; }
        });
        if (!best) { return null; }
        var other = byId[best.preNode === n.id ? best.postNode : best.preNode];
        if (!other || other === n) { return null; }
        return Math.atan2(other.y - n.y, other.x - n.x);
      }

      arborSel.attr("transform", function (n) { return "rotate(" + fmt(n.theta * DEG) + ")"; });
      redrawSynapses();
    }

    // ---------- 3D mode (billboarded arbors) ----------
    // Arbors stay exactly the flat 2D shapes drawn above -- only the soma's
    // position becomes 3D and is projected through a hand-rolled camera each
    // frame. orientArbors() is 2D-only and intentionally not re-run here;
    // node.theta stays frozen at whatever it settled to before the switch.
    var simulation3d = null;
    var mode3dBtn = document.getElementById("mode-3d");
    var initialDist = cam.dist;
    var orbitDragging = false, orbitLastX = 0, orbitLastY = 0, orbitMoved = false;

    function ensureSimulation3d() {
      if (simulation3d) { return simulation3d; }
      nodes.forEach(function (n) {
        if (n.z === undefined) { n.z = (Math.random() - 0.5) * 40; }
      });
      simulation3d = d3.forceSimulation(nodes, 3)
        .force("link", d3.forceLink(forceLinks).id(function (n) { return n.id; })
          .distance(function (l) {
            if (l.similarity) { return 80 + (1 - l.weight) * 120; }
            var pad = l.confirmed ? 40 : 76;
            return l.source.extent + l.target.extent + pad;
          })
          .strength(function (l) { return l.similarity ? 0.10 : Math.min(0.5, l.strength); }))
        .force("charge", d3.forceManyBody().strength(function (n) { return -180 - 6 * (n.signal_count || 0); }))
        .force("collide", d3.forceCollide().radius(function (n) { return n.extent; }).iterations(2))
        // a weak pull toward the origin, purely so the cluster doesn't drift
        // unboundedly far from it over many ticks -- the camera itself
        // orbits around the live centroid (camTarget, see updateCamTarget),
        // not this coordinate, so this is a numerical-stability anchor only
        .force("x", d3.forceX(0).strength(0.02))
        .force("y", d3.forceY(0).strength(0.02))
        .force("z", d3.forceZ(0).strength(0.02))
        .alphaDecay(0.028)
        .on("tick", tick3d)
        .on("end", fitGraph3d)
        .stop();
      return simulation3d;
    }

    function project3d(n) {
      var nx = n.x - camTarget.x;
      var ny = n.y - camTarget.y;
      var nz = (n.z || 0) - camTarget.z;
      var cy = Math.cos(cam.ry), sy = Math.sin(cam.ry);
      var x = nx * cy + nz * sy;
      var z = -nx * sy + nz * cy;
      var cx = Math.cos(cam.rx), sx = Math.sin(cam.rx);
      var y = ny * cx - z * sx;
      z = ny * sx + z * cx;
      var f = cam.dist / (cam.dist + z);
      // rotation happens around camTarget, but the SVG viewBox origin is
      // top-left, not centered -- shift the projected point to the canvas center
      return { sx: width / 2 + x * f, sy: height / 2 + y * f, f: f, z: z };
    }

    function updateCamTarget() {
      var cx = 0, cy = 0, cz = 0;
      nodes.forEach(function (n) { cx += n.x; cy += n.y; cz += (n.z || 0); });
      var count = Math.max(1, nodes.length);
      camTarget.x = cx / count;
      camTarget.y = cy / count;
      camTarget.z = cz / count;
    }

    function anchor3d(node, signalId) {
      var p = node.__proj || project3d(node);
      var local = signalId && node.anchors[signalId];
      var dx = local ? local.dx : node.r;
      var dy = local ? local.dy : 0;
      var localAngle = local ? local.angle : 0;
      var c = Math.cos(node.theta);
      var s = Math.sin(node.theta);
      return {
        x: p.sx + (dx * c - dy * s) * p.f,
        y: p.sy + (dx * s + dy * c) * p.f,
        a: localAngle + node.theta
      };
    }

    // Same cubic-bezier "synaptic cleft" shape as the 2D synapsePath() --
    // pull back along each anchor's tangent so the curve leaves the billboard
    // at a natural angle instead of aiming straight at the other endpoint.
    function synapsePath3d(s) {
      // see synapsePath()'s comment -- preNode/postNode, not source/target
      var a = anchor3d(byId[s.preNode], s.preSignal);
      var b = anchor3d(byId[s.postNode], s.postSignal);
      var p1x = a.x + 3 * Math.cos(a.a);
      var p1y = a.y + 3 * Math.sin(a.a);
      var p2x = b.x + 3 * Math.cos(b.a);
      var p2y = b.y + 3 * Math.sin(b.a);
      var dist = Math.hypot(p2x - p1x, p2y - p1y);
      var k = Math.min((s.kind === "axo_axonic" ? 0.22 : 0.35) * dist, 55);
      return "M" + fmt(p1x) + "," + fmt(p1y) +
        "C" + fmt(p1x + k * Math.cos(a.a)) + "," + fmt(p1y + k * Math.sin(a.a)) +
        " " + fmt(p2x + k * Math.cos(b.a)) + "," + fmt(p2y + k * Math.sin(b.a)) +
        " " + fmt(p2x) + "," + fmt(p2y);
    }

    function redrawSynapses3d() {
      synapseSel.attr("d", synapsePath3d);
      hitSel.attr("d", synapsePath3d);
    }

    function tick3d() {
      updateCamTarget();
      nodes.forEach(function (n) { n.__proj = project3d(n); });
      neuronSel.sort(function (a, b) { return b.__proj.z - a.__proj.z; });
      neuronSel.attr("transform", function (n) {
        var p = n.__proj;
        return "translate(" + fmt(p.sx) + "," + fmt(p.sy) + ") scale(" + fmt(Math.max(0.05, p.f)) + ")";
      });
      neuronSel.select("text.nlabel").style("display", function (n) {
        return n.__proj.f > 0.75 ? null : "none";
      });
      redrawSynapses3d();
      applyTier(initialDist / cam.dist);
    }

    function fitGraph3d() {
      cam.rx = -0.35;
      cam.ry = 0.6;
      updateCamTarget();
      var maxR = 1;
      nodes.forEach(function (n) {
        var dx = n.x - camTarget.x, dy = n.y - camTarget.y, dz = (n.z || 0) - camTarget.z;
        maxR = Math.max(maxR, Math.hypot(dx, dy, dz) + n.extent);
      });
      cam.dist = maxR * 1.6;
      tick3d();
    }

    function centerNode3d(n) {
      cam.ry = Math.atan2(n.x - camTarget.x, (n.z || 0) - camTarget.z || 0.0001);
      tick3d();
    }

    function enterMode3d() {
      mode3d = true;
      simulation.stop();
      svg.on(".zoom", null);
      // the camera projector computes final screen pixels directly; any
      // leftover 2D pan/zoom transform on the shared viewport group would
      // otherwise double-apply on top of it
      viewport.attr("transform", null);
      // d3-force always reads/writes node.x/node.y directly (not configurable),
      // so the 2D and 3D simulations share the same fields. Snapshot the
      // settled 2D layout before the 3D sim (re-centered on the world origin)
      // starts moving x/y, or it would be silently overwritten and unrecoverable
      // on switching back.
      nodes.forEach(function (n) { n.__x2d = n.x; n.__y2d = n.y; });
      ensureSimulation3d().alpha(0.6).restart();
      // fit immediately against the 2D-seeded positions so the very first
      // frame is already centered on the cluster, instead of a stale/default
      // camTarget until the simulation's first tick fires
      fitGraph3d();
      mode3dBtn.setAttribute("aria-pressed", "true");
      setText("mode-3d", ui.mode_3d);
    }

    function exitMode3d() {
      mode3d = false;
      if (simulation3d) { simulation3d.stop(); }
      nodes.forEach(function (n) {
        if (n.__x2d !== undefined) { n.x = n.__x2d; n.y = n.__y2d; }
      });
      svg.call(zoom);
      // d3.zoom kept tracking its own transform internally the whole time
      // (entering 3D only cleared the viewport's visual attribute); reapply it
      // now so the 2D view resumes exactly where the user left it instead of
      // flashing to identity until the next zoom interaction
      svg.call(zoom.transform, d3.zoomTransform(svg.node()));
      neuronSel.select("text.nlabel").style("display", null);
      tick(); // redraw the just-restored 2D positions/paths that tick3d
              // overwrote; the 2D layout itself never changed while in 3D
              // mode, so this resumes the already-settled layout instead of
              // re-simulating from scratch
      mode3dBtn.setAttribute("aria-pressed", "false");
      setText("mode-3d", ui.mode_2d);
    }

    mode3dBtn.addEventListener("click", function () {
      if (mode3d) { exitMode3d(); } else { enterMode3d(); }
    });

    // orbit (drag) + dolly (wheel) -- gated on mode3d so 2D pan/zoom via
    // d3.zoom is completely unaffected when 3D is off
    svg.node().addEventListener("pointerdown", function (event) {
      if (!mode3d) { return; }
      // otherwise the browser's native text/image drag-select gesture starts
      // at the same time, which visibly fights the orbit
      event.preventDefault();
      orbitDragging = true;
      orbitMoved = false;
      orbitLastX = event.clientX;
      orbitLastY = event.clientY;
    });
    window.addEventListener("pointermove", function (event) {
      if (!mode3d || !orbitDragging) { return; }
      event.preventDefault();
      var dx = event.clientX - orbitLastX;
      var dy = event.clientY - orbitLastY;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) { orbitMoved = true; }
      cam.ry += dx * 0.008;
      cam.rx = Math.max(-1.4, Math.min(1.4, cam.rx + dy * 0.008));
      orbitLastX = event.clientX;
      orbitLastY = event.clientY;
      tick3d();
    });
    window.addEventListener("pointerup", function () { orbitDragging = false; });
    svg.node().addEventListener("wheel", function (event) {
      if (!mode3d) { return; }
      event.preventDefault();
      cam.dist = Math.max(150, Math.min(4000, cam.dist + event.deltaY));
      tick3d();
    }, { passive: false });

    neuronSel.call(d3.drag()
      .on("start", function (event, n) {
        // in 3D mode, dragging the background orbits the camera instead
        // (see docs/overview-3d-feasibility.md) -- repositioning a node by hand
        // is 2D-only, so this is a deliberate no-op rather than an omission.
        if (mode3d) { return; }
        if (!event.active) { simulation.alphaTarget(0.2).restart(); }
        n.fx = n.x; n.fy = n.y;
      })
      .on("drag", function (event, n) {
        if (mode3d) { return; }
        n.fx = event.x; n.fy = event.y;
      })
      .on("end", function (event, n) {
        if (mode3d) { return; }
        if (!event.active) { simulation.alphaTarget(0); }
        n.fx = null; n.fy = null;
      }));

    // ---------- level of detail ----------
    var tier = null;
    function applyTier(scale) {
      var dense = nodes.length > 120;
      var next;
      if (LIGHT) {
        next = scale < (dense ? 0.9 : 0.55) ? "lod-far" : "lod-mid";
      } else if (scale < (dense ? 0.9 : 0.55)) {
        next = "lod-far";
      } else if (scale < (dense ? 2.0 : 1.3)) {
        next = "lod-mid";
      } else {
        next = "lod-near";
      }
      if (next === tier) { return; }
      tier = next;
      viewport.attr("class", "viewport " + tier + (nodes.length < 40 ? " sparse" : ""));
    }
    applyTier(1);

    // ---------- interaction ----------
    var tipEl = document.getElementById("tip");
    function showTip(event, signal) {
      clear(tipEl);
      tipEl.classList.remove("synapse-tip");
      var b = document.createElement("b");
      b.textContent = (signal.polarity === "axon" ? ui.axon : ui.dendrite) + " · " + signal.type;
      tipEl.appendChild(b);
      tipEl.appendChild(document.createTextNode(signal.signal));
      if (signal.evidence) {
        var i = document.createElement("i");
        i.textContent = ui.evidence + ": " + signal.evidence;
        tipEl.appendChild(i);
      }
      var rect = canvas.getBoundingClientRect();
      tipEl.hidden = false;
      tipEl.style.left = Math.min(rect.width - 300, Math.max(8, event.clientX - rect.left + 14)) + "px";
      tipEl.style.top = Math.max(8, event.clientY - rect.top + 14) + "px";
    }
    function hideTip() { tipEl.hidden = true; }

    function showSynapseTip(event, s) {
      clear(tipEl);
      tipEl.classList.add("synapse-tip");

      var preIsSource = s.preNode === s.source;
      var preType = preIsSource ? s.source_signal_type : s.target_signal_type;
      var preText = preIsSource ? s.source_signal_text : s.target_signal_text;
      var preEvidence = preIsSource ? s.source_evidence : s.target_evidence;
      var postType = preIsSource ? s.target_signal_type : s.source_signal_type;
      var postText = preIsSource ? s.target_signal_text : s.source_signal_text;
      var postEvidence = preIsSource ? s.target_evidence : s.source_evidence;
      var postLabel = s.kind === "axo_axonic" ? ui.axon : ui.dendrite;

      tipEl.appendChild(synapseEnd(byId[s.preNode].title, ui.axon, preType, preText, preEvidence));
      tipEl.appendChild(synapseEnd(byId[s.postNode].title, postLabel, postType, postText, postEvidence));

      var meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = (s["class"] === "confirmed" ? ui.confirmed : ui.computed) + " · " + ui[s.kind] +
        (s.also_computed ? " · " + ui.also_computed : "");
      tipEl.appendChild(meta);

      positionTip(event);
    }

    function synapseEnd(title, roleLabel, type, text, evidence) {
      var wrap = document.createElement("div");
      wrap.className = "end";
      var b = document.createElement("b");
      var span = document.createElement("span");
      span.className = "end-title";
      span.textContent = title;
      b.appendChild(span);
      b.appendChild(document.createTextNode(" · " + roleLabel + (type ? " · " + type : "")));
      wrap.appendChild(b);
      wrap.appendChild(document.createTextNode(text || ""));
      if (evidence) {
        var i = document.createElement("i");
        i.textContent = ui.evidence + ": " + evidence;
        wrap.appendChild(i);
      }
      return wrap;
    }

    function positionTip(event) {
      var rect = canvas.getBoundingClientRect();
      tipEl.hidden = false;
      tipEl.style.left = Math.min(rect.width - tipEl.offsetWidth - 8, Math.max(8, event.clientX - rect.left + 14)) + "px";
      tipEl.style.top = Math.max(8, event.clientY - rect.top + 14) + "px";
    }

    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function focusNeuron(n, on) {
      neuronSel.filter(function (d) { return d === n; }).classed("focused", on);
      if (on) { firePulses(n); } else { clearPulses(); }
    }

    var pulseNodes = [];
    function clearPulses() {
      pulseLayer.selectAll("*").remove();
      pulseNodes = [];
      d3.selectAll(".synapse.active").classed("active", false);
    }

    function firePulses(n) {
      clearPulses();
      var outgoing = (n.outgoing || []).slice(0, 6);
      outgoing.forEach(function (s, i) {
        // synapsePath3d() produces a real curved path in current screen
        // space, so the same travel-along-the-path animation works in 3D too
        var path = mode3d ? synapsePath3d(s) : synapsePath(s);
        var color = s.kind === "axo_axonic" ? "#0ea5a4" : "#7c5cff";
        var el = pulseLayer.append("path")
          .attr("class", "pulse")
          .attr("d", path)
          .attr("stroke", color);
        if (reduceMotion) {
          markActive(s);
          return;
        }
        var node = el.node();
        var len = node.getTotalLength();
        node.style.setProperty("--len", len + "px");
        node.style.setProperty("--dur", (s.kind === "axo_axonic" ? 500 : 900) + "ms");
        node.style.strokeDasharray = "16 " + (len + 40);
        node.getBoundingClientRect();
        el.classed("run", true);
        pulseNodes.push(node);
        window.setTimeout(function () { flashTarget(s); }, (s.kind === "axo_axonic" ? 500 : 900) + i * 40);
      });
    }

    function markActive(s) {
      allSynapseSel().forEach(function (el) {
        if (d3.select(el).datum() === s) { el.classList.add("active"); }
      });
    }

    function flashTarget(s) {
      var post = byId[s.postNode];
      if (!post) { return; }
      neuronSel.filter(function (d) { return d === post; }).selectAll("circle.soma").each(function () {
        var el = this;
        el.classList.remove("flash");
        el.getBoundingClientRect();
        el.classList.add("flash");
      });
    }

    // ---------- filters ----------
    var filters = [
      buildSelect("filter-type", ui.all_types, unique(nodes.map(function (n) { return n.type; }))),
      buildSelect("filter-confidence", ui.all_confidence, unique(nodes.map(function (n) { return n.confidence; }))),
      buildSelect("filter-role", ui.all_roles, unique(nodes.map(function (n) { return n.map_role; }))),
      buildSelect("filter-kind", ui.all_kinds, [["axo_dendritic", ui.axo_dendritic], ["axo_axonic", ui.axo_axonic], ["confirmed", ui.confirmed], ["computed", ui.computed]]),
      buildSelect("filter-idea", ui.all_ideas, unique(synapses.map(function (s) { return s.idea_type; })))
    ];
    filters.forEach(function (el) { el.addEventListener("change", applyFilters); });
    search.addEventListener("input", applyFilters);
    search.addEventListener("keydown", function (event) {
      if (event.key !== "Enter") { return; }
      var q = search.value.trim().toLowerCase();
      if (!q) { return; }
      for (var i = 0; i < nodes.length; i += 1) {
        if (matchesQuery(nodes[i], q)) { selectNode(nodes[i]); centerNode(nodes[i]); return; }
      }
    });

    function buildSelect(id, allLabel, values) {
      var el = document.getElementById(id);
      clear(el);
      var first = document.createElement("option");
      first.value = "";
      first.textContent = allLabel || "";
      el.appendChild(first);
      values.forEach(function (v) {
        var value = Array.isArray(v) ? v[0] : v;
        var label = Array.isArray(v) ? v[1] : v;
        if (!value) { return; }
        var opt = document.createElement("option");
        opt.value = value;
        opt.textContent = label || value;
        el.appendChild(opt);
      });
      el.setAttribute("aria-label", allLabel || id);
      return el;
    }

    function applyFilters() {
      var type = filters[0].value;
      var conf = filters[1].value;
      var role = filters[2].value;
      var kind = filters[3].value;
      var idea = filters[4].value;
      var q = search.value.trim().toLowerCase();
      var visible = {};

      // connectionFilter restricts the graph to the currently selected node's
      // outgoing ("source") or incoming ("target") neighbors -- set only from
      // that node's own inspector buttons, so `selected` is always a node
      // (never a synapse) whenever this is non-null (clearSelection resets it).
      var connIds = null;
      var connSynapseIds = null;
      if (connectionFilter && selected) {
        var list = connectionFilter === "source" ? (selected.outgoing || []) : (selected.incoming || []);
        connIds = {};
        connIds[selected.id] = true;
        connSynapseIds = {};
        list.forEach(function (s) {
          connIds[connectionFilter === "source" ? s.postNode : s.preNode] = true;
          connSynapseIds[s.id] = true;
        });
      }

      neuronSel.classed("dim", function (n) {
        var ok = (!type || n.type === type) &&
          (!conf || n.confidence === conf) &&
          (!role || n.map_role === role) &&
          (!q || matchesQuery(n, q)) &&
          (!connIds || connIds[n.id]);
        visible[n.id] = ok;
        return !ok;
      });

      function synapseDim(s) {
        if (!visible[s.source] || !visible[s.target]) { return true; }
        if (connSynapseIds && !connSynapseIds[s.id]) { return true; }
        if (idea && s.idea_type !== idea) { return true; }
        if (!kind) { return false; }
        if (kind === "confirmed" || kind === "computed") { return s["class"] !== kind; }
        return s.kind !== kind;
      }
      synapseSel.classed("dim", synapseDim);
      hitSel.classed("dim", synapseDim);
    }

    function matchesQuery(n, q) {
      if (n.title.toLowerCase().indexOf(q) >= 0) { return true; }
      if (n.source.toLowerCase().indexOf(q) >= 0) { return true; }
      var pool = n.topics.concat(n.keywords);
      for (var i = 0; i < pool.length; i += 1) {
        if (String(pool[i]).toLowerCase().indexOf(q) >= 0) { return true; }
      }
      var sigs = n.axon.concat(n.dendrite);
      for (var j = 0; j < sigs.length; j += 1) {
        if (sigs[j].signal.toLowerCase().indexOf(q) >= 0) { return true; }
      }
      return false;
    }

    // ---------- inspector ----------
    var inspector = document.getElementById("inspector-body");
    var selected = null;
    // null | "source" | "target" -- restricts the graph to `selected`'s
    // outgoing or incoming neighbors. Always tied to the current node
    // selection, so clearSelection() resets it (see there for why).
    var connectionFilter = null;

    function clearSelection() {
      neuronSel.classed("selected", false);
      synapseSel.classed("selected", false);
      d3.selectAll(".branch-focus").classed("branch-focus", false);
      if (connectionFilter) { connectionFilter = null; applyFilters(); }
    }

    function selectNode(n, signalId) {
      clearSelection();
      selected = n;
      neuronSel.filter(function (d) { return d === n; }).classed("selected", true);
      clear(inspector);

      var h = document.createElement("h3");
      h.textContent = n.title;
      inspector.appendChild(h);
      if (n.isolate) {
        var badge = document.createElement("span");
        badge.className = "badge computed";
        badge.textContent = ui.isolate;
        inspector.appendChild(badge);
      }
      if ((n.outgoing && n.outgoing.length) || (n.incoming && n.incoming.length)) {
        var connRow = document.createElement("div");
        connRow.className = "conn-filter";
        connRow.appendChild(connFilterButton(n, signalId, "source", ui.filter_as_source));
        connRow.appendChild(connFilterButton(n, signalId, "target", ui.filter_as_target));
        inspector.appendChild(connRow);
      }
      addField(inspector, ui.source, n.source);
      addField(inspector, ui.type, n.type);
      addField(inspector, ui.confidence, n.confidence);
      addField(inspector, ui.map_role, n.map_role);
      addField(inspector, ui.synapses, String(n.synapse_count));
      if (n.topics.length) { addChips(inspector, ui.topics, n.topics); }
      if (n.keywords.length) { addChips(inspector, ui.keywords, n.keywords.slice(0, 14)); }
      if (n.summary) { addBlock(inspector, ui.summary, n.summary); }

      if (n.isolate) {
        var note = document.createElement("p");
        note.className = "prompt";
        note.textContent = ui.no_signals;
        inspector.appendChild(note);
        return;
      }
      addSignals(n, ui.axon_signals, n.axon, "axon", signalId);
      addSignals(n, ui.dendrite_signals, n.dendrite, "dendrite", signalId);
    }

    function addSignals(n, heading, list, cls, activeId) {
      if (!list.length) { return; }
      var sect = section(heading + " (" + list.length + ")");
      list.forEach(function (s) {
        var card = document.createElement("div");
        card.className = "card " + cls + (s.id === activeId ? " on" : "");
        var kind = document.createElement("div");
        kind.className = "kind";
        kind.textContent = s.type + (s.synapse_count
          ? " · " + s.synapse_count + " " + (s.synapse_count === 1 ? ui.synapse : ui.synapses)
          : "");
        card.appendChild(kind);
        var body = document.createElement("div");
        body.className = "body";
        body.textContent = s.signal;
        card.appendChild(body);
        if (s.evidence) {
          var ev = document.createElement("div");
          ev.className = "ev";
          ev.textContent = ui.evidence + ": " + s.evidence;
          card.appendChild(ev);
        }
        card.addEventListener("click", function () { highlightBranch(n, s.id); });
        sect.appendChild(card);
      });
      inspector.appendChild(sect);
      if (activeId) { highlightBranch(n, activeId); }
    }

    function highlightBranch(n, signalId) {
      d3.selectAll(".branch-focus").classed("branch-focus", false);
      neuronSel.filter(function (d) { return d === n; })
        .selectAll("[data-signal]")
        .classed("branch-focus", function () {
          return this.getAttribute("data-signal") === signalId;
        });
    }

    function selectSynapse(s) {
      clearSelection();
      selected = s;
      synapseSel.filter(function (d) { return d === s; }).classed("selected", true);
      clear(inspector);

      var pre = byId[s.preNode];
      var post = byId[s.postNode];
      var h = document.createElement("h3");
      h.textContent = pre.title + " → " + post.title;
      inspector.appendChild(h);

      var badges = document.createElement("div");
      badges.appendChild(badge(s["class"], s["class"] === "confirmed" ? ui.confirmed : ui.computed));
      badges.appendChild(badge(s.kind, ui[s.kind]));
      inspector.appendChild(badges);

      addField(inspector, ui.idea_type, s.idea_type || "");
      if (s.label) { addField(inspector, ui.synapse, s.label); }
      addField(inspector, ui.score, String(s.score));
      addField(inspector, ui.strength, String(s.strength));
      if (s.also_computed) { addField(inspector, "", ui.also_computed); }
      if (s.created_at) { addField(inspector, ui.generated, s.created_at); }

      var comp = s.components || {};
      if (Object.keys(comp).length) {
        var sect = section(ui.components);
        var bars = document.createElement("div");
        bars.className = "bars";
        [["overlap", ui.overlap, 5], ["complementarity", ui.complementarity, 5],
         ["novelty", ui.novelty, 4], ["evidence", ui.evidence, 4],
         ["feasibility", ui.feasibility, 3]].forEach(function (row) {
          if (comp[row[0]] === undefined) { return; }
          bars.appendChild(bar(row[1], comp[row[0]], row[2]));
        });
        sect.appendChild(bars);
        inspector.appendChild(sect);
      }

      var oriented = s.direction === "source_to_target" ? s : flip(s);
      // both ends of an axo-axonic synapse are axon terminals
      var postLabel = s.kind === "axo_axonic" ? ui.bouton : ui.dendrite;
      addSide(ui.axon, oriented, true);
      addSide(postLabel, oriented, false);

      function flip(x) {
        return {
          source_signal_type: x.target_signal_type, target_signal_type: x.source_signal_type,
          source_signal_text: x.target_signal_text, target_signal_text: x.source_signal_text,
          source_evidence: x.target_evidence, target_evidence: x.source_evidence
        };
      }
      function addSide(heading, obj, isPre) {
        var text = isPre ? obj.source_signal_text : obj.target_signal_text;
        if (!text) { return; }
        var sect = section(heading + (isPre ? " · " + (obj.source_signal_type || "") : " · " + (obj.target_signal_type || "")));
        var p = document.createElement("p");
        p.style.margin = "0 0 5px";
        p.textContent = text;
        sect.appendChild(p);
        var ev = isPre ? obj.source_evidence : obj.target_evidence;
        if (ev) {
          var e = document.createElement("div");
          e.className = "ev";
          e.textContent = ui.evidence + ": " + ev;
          sect.appendChild(e);
        }
        inspector.appendChild(sect);
      }
    }

    function showPrompt() {
      clear(inspector);
      var p = document.createElement("p");
      p.className = "prompt";
      p.textContent = ui.select_prompt || "";
      inspector.appendChild(p);
      if ((data.warnings || []).length) {
        var sect = section(ui.warnings);
        data.warnings.forEach(function (w) {
          var line = document.createElement("div");
          line.className = "ev";
          line.textContent = w;
          sect.appendChild(line);
        });
        inspector.appendChild(sect);
      }
    }

    svg.on("click", function () {
      // an orbit drag that ends over the background still dispatches a click;
      // don't let it also deselect whatever was picked before the drag
      if (mode3d && orbitMoved) { orbitMoved = false; return; }
      clearSelection(); selected = null; showPrompt();
    });

    // ---------- legend ----------
    buildLegend();
    function buildLegend() {
      var host = document.getElementById("legend-swatches");
      clear(host);
      host.appendChild(anatomyGlyph());
      [[ui.axo_dendritic, "var(--axo-dendritic)", "line"],
       [ui.axo_axonic, "var(--axo-axonic)", "dash"]].forEach(function (row) {
        host.appendChild(swatch(row[0], row[1], row[2]));
      });
      unique(nodes.map(function (n) { return n.map_role; })).forEach(function (role) {
        host.appendChild(swatch(role, roleColor(role), "dot"));
      });
    }

    function anatomyGlyph() {
      var wrap = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      wrap.setAttribute("width", "150");
      wrap.setAttribute("height", "56");
      wrap.setAttribute("viewBox", "-46 -28 150 56");
      wrap.setAttribute("aria-hidden", "true");
      function add(tag, attrs) {
        var el = document.createElementNS("http://www.w3.org/2000/svg", tag);
        Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); });
        wrap.appendChild(el);
        return el;
      }
      [-0.8, 0, 0.8].forEach(function (off) {
        add("path", {
          "class": "dendrite-branch",
          d: "M-9,0C-20," + (off * 14) + " -30," + (off * 20) + " -40," + (off * 22)
        });
      });
      add("path", { "class": "axon-trunk", d: "M9,0Q34,-6 56,0" });
      add("circle", { "class": "bouton", cx: 64, cy: -5, r: 3.4, fill: "#3563d6" });
      add("circle", { "class": "bouton", cx: 64, cy: 5, r: 3.4, fill: "#3563d6" });
      add("path", { "class": "branchlet", d: "M56,0L64,-5M56,0L64,5" });
      add("circle", { "class": "soma", r: 9, fill: "#3563d6" });
      return wrap;
    }

    function swatch(label, color, shape) {
      var el = document.createElement("span");
      el.className = "sw";
      el.style.color = color;
      var mark = document.createElement("i");
      if (shape === "dot") { mark.style.background = color; } else { mark.className = shape; }
      el.appendChild(mark);
      var text = document.createElement("span");
      text.style.color = "var(--muted)";
      text.textContent = label;
      el.appendChild(text);
      return el;
    }

    // ---------- controls ----------
    document.getElementById("fit").addEventListener("click", fitGraph);
    document.getElementById("reset").addEventListener("click", function () {
      if (mode3d) {
        nodes.forEach(function (n) { n.fx = null; n.fy = null; n.fz = null; });
        ensureSimulation3d().alpha(0.8).restart();
        fitGraph3d(); // reset orbit angles and refit now; the "end" handler
                      // refits again once the reheated sim resettles
        return;
      }
      nodes.forEach(function (n) { n.fx = null; n.fy = null; });
      svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity);
      simulation.alpha(0.8).restart();
    });

    // fitGraph/centerNode are called from both the controls above and the
    // 2D force simulation's "end" handler / search-jump below; keep those call
    // sites unchanged and dispatch on mode3d here instead.
    function fitGraph() { if (mode3d) { fitGraph3d(); } else { fitGraph2d(); } }
    function centerNode(n) { if (mode3d) { centerNode3d(n); } else { centerNode2d(n); } }

    function fitGraph2d() {
      if (!nodes.length) { return; }
      var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      nodes.forEach(function (n) {
        minX = Math.min(minX, n.x - n.extent);
        maxX = Math.max(maxX, n.x + n.extent);
        minY = Math.min(minY, n.y - n.extent);
        maxY = Math.max(maxY, n.y + n.extent);
      });
      var w = Math.max(1, maxX - minX);
      var h = Math.max(1, maxY - minY);
      var scale = Math.min(6, 0.92 / Math.max(w / width, h / height));
      var tx = width / 2 - scale * (minX + w / 2);
      var ty = height / 2 - scale * (minY + h / 2);
      svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    }

    function centerNode2d(n) {
      svg.transition().duration(450).call(
        zoom.transform,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(1.7).translate(-n.x, -n.y)
      );
    }

    window.addEventListener("resize", function () {
      width = canvas.clientWidth || width;
      height = canvas.clientHeight || height;
      svg.attr("viewBox", "0 0 " + width + " " + height);
    });

    // ---------- boot ----------
    showPrompt();
    if (!synapses.length) {
      overlay.textContent = ui.no_synapses || "";
      window.setTimeout(function () { overlay.textContent = ""; }, 6000);
    }
    window.setTimeout(fitGraph, 700);

    // ---------- helpers ----------
    function roleColor(role) {
      var key = String(role || "unknown").toLowerCase();
      if (ROLE_COLORS[key]) { return ROLE_COLORS[key]; }
      var names = Object.keys(ROLE_COLORS);
      for (var i = 0; i < names.length; i += 1) {
        if (key.indexOf(names[i]) >= 0) { return ROLE_COLORS[names[i]]; }
      }
      return ROLE_COLORS.unknown;
    }
    function unique(values) {
      var seen = {};
      var out = [];
      values.forEach(function (v) {
        if (!v || seen[v]) { return; }
        seen[v] = true;
        out.push(v);
      });
      return out.sort();
    }
    function truncate(value, max) {
      return value.length > max ? value.slice(0, max - 1) + "…" : value;
    }
    function isEnter(event) { return event.key === "Enter" || event.key === " "; }
    function addStat(host, value, label) {
      if (value === undefined || value === null) { return; }
      var el = document.createElement("span");
      var b = document.createElement("b");
      b.textContent = String(value);
      el.appendChild(b);
      el.appendChild(document.createTextNode(" " + (label || "")));
      host.appendChild(el);
    }
    function badge(cls, label) {
      var el = document.createElement("span");
      el.className = "badge " + cls;
      el.textContent = label || cls;
      return el;
    }
    function bar(label, value, max) {
      var row = document.createElement("div");
      row.className = "bar";
      var name = document.createElement("span");
      name.textContent = label;
      var track = document.createElement("span");
      track.className = "track";
      var fill = document.createElement("span");
      fill.className = "fill";
      fill.style.width = Math.round(100 * Math.min(1, value / max)) + "%";
      track.appendChild(fill);
      var num = document.createElement("span");
      num.textContent = String(value);
      row.appendChild(name);
      row.appendChild(track);
      row.appendChild(num);
      return row;
    }
    function section(heading) {
      var el = document.createElement("div");
      el.className = "sect";
      var h = document.createElement("h4");
      h.textContent = heading;
      el.appendChild(h);
      return el;
    }
    function connFilterButton(n, signalId, direction, label) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.direction = direction;
      btn.className = "conn-filter-btn" + (connectionFilter === direction ? " on" : "");
      btn.textContent = label;
      btn.setAttribute("aria-pressed", connectionFilter === direction ? "true" : "false");
      btn.addEventListener("click", function () {
        connectionFilter = connectionFilter === direction ? null : direction;
        applyFilters();
        // toggle both buttons' on/off state in place -- calling selectNode()
        // again here would rebuild the inspector via clearSelection(), which
        // resets connectionFilter to null and immediately undoes this click
        Array.from(btn.parentElement.querySelectorAll("button")).forEach(function (b) {
          var active = connectionFilter === b.dataset.direction;
          b.classList.toggle("on", active);
          b.setAttribute("aria-pressed", active ? "true" : "false");
        });
      });
      return btn;
    }
    function addField(host, label, value) {
      if (!value) { return; }
      var row = document.createElement("div");
      row.className = "field";
      var l = document.createElement("span");
      l.textContent = label;
      var v = document.createElement("span");
      v.textContent = value;
      row.appendChild(l);
      row.appendChild(v);
      host.appendChild(row);
    }
    function addBlock(host, heading, value) {
      var sect = section(heading);
      var p = document.createElement("p");
      p.style.margin = "0";
      p.textContent = value;
      sect.appendChild(p);
      host.appendChild(sect);
    }
    function addChips(host, heading, values) {
      var sect = section(heading);
      var wrap = document.createElement("div");
      wrap.className = "chips";
      values.forEach(function (v) {
        var chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = v;
        wrap.appendChild(chip);
      });
      sect.appendChild(wrap);
      host.appendChild(sect);
    }
    function setText(id, value) {
      var el = document.getElementById(id);
      if (el) { el.textContent = value || ""; }
    }
    function clear(el) {
      while (el.firstChild) { el.removeChild(el.firstChild); }
    }
  }

  function clear(el) {
    while (el.firstChild) { el.removeChild(el.firstChild); }
  }
})();
"""


_SKELETON = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>ClawShelf Neural Map</title>
  <style>__APP_STYLE__</style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="masthead">
        <h1 id="ui-title"></h1>
        <p id="ui-subtitle"></p>
      </div>
      <div class="stats" id="stats"></div>
    </header>
    <div class="controls">
      <input id="search" type="search" autocomplete="off" spellcheck="false">
      <select id="filter-type"></select>
      <select id="filter-confidence"></select>
      <select id="filter-role"></select>
      <select id="filter-kind"></select>
      <select id="filter-idea"></select>
      <button id="fit" type="button"></button>
      <button id="reset" type="button"></button>
      <button id="mode-3d" type="button" aria-pressed="false"></button>
    </div>
    <div class="workspace">
      <div class="canvas">
        <svg id="graph" role="img"></svg>
        <div class="overlay" id="overlay" role="status"></div>
        <div class="tip" id="tip" role="tooltip" hidden></div>
      </div>
      <aside id="inspector" aria-live="polite">
        <h2 id="inspector-title"></h2>
        <div id="inspector-body"></div>
      </aside>
    </div>
    <section class="legend">
      <h2 id="legend-title"></h2>
      <div class="swatches" id="legend-swatches"></div>
    </section>
  </div>
  <script id="overview-data" type="application/json">__OVERVIEW_DATA__</script>
  <script>__D3_SOURCE__</script>
  <script>__D3_FORCE3D_SOURCE__</script>
  <script>__APP_SCRIPT__</script>
</body>
</html>
"""


_HTML_TEMPLATE = _SKELETON.replace("__APP_STYLE__", _APP_STYLE).replace(
    "__APP_SCRIPT__", _APP_SCRIPT
)
