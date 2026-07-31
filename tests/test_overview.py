from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.config import ShelfConfig
from clawshelf.overview import (
    OVERVIEW_NAME,
    OverviewError,
    _resolve_language,
    _ui_strings,
    build_overview_data,
    generate_overview,
    main as overview_main,
    render_overview_html,
)
from clawshelf.overview_synapses import (
    SYNAPSE_GLOBAL_CAP,
    SYNAPSE_PER_NODE,
    SYNAPSE_PER_PAIR,
    SYNAPSE_PER_SIGNAL,
)
from clawshelf.overview_template import (
    BINARYTREE_VERSION,
    CDN_SCRIPTS,
    D3_VERSION,
    FORCE3D_VERSION,
    OCTREE_VERSION,
    _APP_SCRIPT,
    cdn_script_tags,
)


AXON = [
    ("Strong Application Method", "Publish monitoring data with a documented decision path for local groups."),
    ("Strong Contribution", "Centralized monitoring lowers reporting cost while restoration outcomes fall."),
]
DENDRITE = [
    ("Extension Hint", "Compare restoration outcomes across data-sharing practices."),
    ("Data / Domain Boundary", "The claim is limited to community-led river restoration."),
]


class OverviewTests(unittest.TestCase):
    def test_all_normalized_sources_become_stable_nodes_and_semantic_neighbors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(
                root,
                "paper",
                "paper.pdf",
                "Paper",
                "pdf",
                ["market microstructure", "liquidity"],
            )
            self._write_record(
                root,
                "report",
                "report.xlsx",
                "Report",
                "xlsx",
                ["market microstructure", "execution"],
            )
            self._write_record(
                root,
                "url",
                "https://example.test/article",
                "Web article",
                "url",
                ["river restoration"],
            )

            first, _ = build_overview_data(root, ShelfConfig(), language="en")
            second, _ = build_overview_data(root, ShelfConfig(), language="en")

            self.assertEqual(len(first["nodes"]), 3)
            self.assertEqual(
                {item["type"] for item in first["nodes"]},
                {"pdf", "xlsx", "url"},
            )
            self.assertEqual(
                [item["id"] for item in first["nodes"]],
                [item["id"] for item in second["nodes"]],
            )
            by_title = {item["title"]: item["id"] for item in first["nodes"]}
            semantic_pairs = {
                frozenset((item["source"], item["target"]))
                for item in first["similarity_links"]
            }
            self.assertIn(
                frozenset((by_title["Paper"], by_title["Report"])),
                semantic_pairs,
            )
            degrees = {node["id"]: 0 for node in first["nodes"]}
            for link in first["similarity_links"]:
                degrees[link["source"]] += 1
                degrees[link["target"]] += 1
            self.assertTrue(all(value <= 3 for value in degrees.values()))

    def test_only_validated_p1_links_render_and_repeated_links_collapse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(
                root, "a", "a.pdf", "A", "pdf", ["market microstructure"]
            )
            self._write_record(
                root, "b", "b.pdf", "B", "pdf", ["market microstructure"]
            )
            self._write_record(root, "c", "c.pdf", "C", "pdf", ["other topic"])
            events = root / "clawshelf" / "events"
            events.mkdir(parents=True)
            (events / "one-p1.json").write_text(
                json.dumps(
                    self._event(
                        root,
                        "a.pdf",
                        "b.pdf",
                        score=15,
                        idea_type="innovation",
                        signal="first spark",
                    )
                ),
                encoding="utf-8",
            )
            (events / "two-p1.json").write_text(
                json.dumps(
                    self._event(
                        root,
                        "b.pdf",
                        "a.pdf",
                        score=17,
                        idea_type="consolidation",
                        signal="second spark",
                        created_at="2026-07-26T06:00:00+00:00",
                    )
                ),
                encoding="utf-8",
            )
            invalid = self._event(root, "a.pdf", "c.pdf", score=20)
            invalid["linked_sources"][0]["verdict"] = "p2_intake"
            (events / "invalid-p1.json").write_text(
                json.dumps(invalid), encoding="utf-8"
            )
            p2 = self._event(root, "a.pdf", "c.pdf", score=20)
            p2["priority"] = p2["classification"] = "P2"
            (events / "intake-p2.json").write_text(
                json.dumps(p2), encoding="utf-8"
            )

            payload, warnings = build_overview_data(
                root, ShelfConfig(), language="en"
            )

            self.assertEqual(warnings, [])
            self.assertEqual(len(payload["edges"]), 1)
            edge = payload["edges"][0]
            self.assertEqual(edge["creativity_score"], 17)
            self.assertEqual(edge["created_at"], "2026-07-26T06:00:00+00:00")
            self.assertEqual(edge["idea_type"], "innovation")
            self.assertEqual(len(edge["sparks"]), 2)
            self.assertEqual(len(edge["evidence"]), 2)

    def test_missing_bidirectional_evidence_and_malformed_events_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(root, "a", "a.md", "A", "md", ["shared topic"])
            self._write_record(root, "b", "b.md", "B", "md", ["shared topic"])
            events = root / "clawshelf" / "events"
            events.mkdir(parents=True)
            event = self._event(root, "a.md", "b.md", score=18)
            event["linked_sources"][0]["matched_evidence"][0][
                "linked_evidence"
            ] = ""
            (events / "missing-evidence-p1.json").write_text(
                json.dumps(event), encoding="utf-8"
            )
            (events / "broken.json").write_text("{", encoding="utf-8")

            payload, warnings = build_overview_data(
                root, ShelfConfig(), language="en"
            )

            self.assertEqual(payload["edges"], [])
            self.assertTrue(
                any("Skipped invalid event broken.json" in item for item in warnings)
            )

    def test_invalid_normalized_record_is_skipped_without_losing_valid_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(root, "valid", "valid.md", "Valid", "md", ["topic"])
            (root / "clawshelf" / "normalized" / "broken.md").write_text(
                "# Missing frontmatter\n", encoding="utf-8"
            )

            payload, warnings = build_overview_data(
                root, ShelfConfig(), language="en"
            )

            self.assertEqual([item["title"] for item in payload["nodes"]], ["Valid"])
            self.assertTrue(
                any(
                    "Skipped invalid normalized record broken.md" in item
                    for item in warnings
                )
            )

    def test_generated_html_is_safe_and_contains_interactive_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malicious_title = 'Bad </script><img src=x onerror="alert(1)">'
            self._write_record(
                root,
                "bad",
                "bad.md",
                malicious_title,
                "md",
                ["safe topic"],
            )

            result = generate_overview(root, language="zh")
            html = Path(result.path).read_text(encoding="utf-8")

            self.assertEqual(result.node_count, 1)
            self.assertEqual(result.edge_count, 0)
            self.assertEqual(
                result.file_url,
                (root / "clawshelf" / OVERVIEW_NAME).resolve().as_uri(),
            )
            self.assertEqual(
                result.markdown_link,
                f"[打开概览]({result.file_url})",
            )
            self.assertIn('id="search"', html)
            self.assertIn('id="inspector"', html)
            self.assertIn('id="graph"', html)
            self.assertIn("clawshelf.overview-data/v2", html)
            self.assertIn("\\u003c/script\\u003e", html)
            # 3D is the only mode: no toggle, no 2D pan/zoom path, no residual
            # branching on a mode flag (see docs/overview-3d-feasibility.md)
            self.assertNotIn('id="mode-3d"', html)
            self.assertNotIn("mode3d", _APP_SCRIPT)
            self.assertNotIn("d3.zoom", _APP_SCRIPT)
            self.assertIn("forceSimulation(nodes, 3)", _APP_SCRIPT)
            # synapsePath must draw (and pulse-animate) from the firing side to
            # the receiving side -- preNode/postNode, which respect s.direction
            # -- not source/target, which are just a canonical id ordering with
            # no relation to firing direction.
            self.assertIn("anchor(byId[s.preNode], s.preSignal)", _APP_SCRIPT)
            self.assertIn("anchor(byId[s.postNode], s.postSignal)", _APP_SCRIPT)
            self.assertNotIn("anchor(byId[s.source]", _APP_SCRIPT)
            self.assertNotIn("anchor(byId[s.target]", _APP_SCRIPT)
            # billboards are aimed at where their partner *appears*, so the
            # orientation must read projected coordinates, not world ones
            self.assertIn("other.__proj.sy - n.__proj.sy", _APP_SCRIPT)
            # a dragged neuron has to be pinned on all three axes or it springs
            # back along z the moment the simulation resumes
            self.assertIn("n.fz", _APP_SCRIPT)
            # per-node source/target connection filter in the inspector
            self.assertIn("n.incoming = n.incoming || []", _APP_SCRIPT)
            self.assertIn("connectionFilter", _APP_SCRIPT)
            self.assertIn("connFilterButton", _APP_SCRIPT)
            # confirmed vs. computed no longer gets its own line color/glow in
            # the graph or the legend -- only axo_dendritic/axo_axonic do, with
            # score driving stroke strength instead
            self.assertIn("scoreStrength", _APP_SCRIPT)
            self.assertNotIn(".synapse.confirmed", html)
            self.assertNotIn('"synapse confirmed ', _APP_SCRIPT)
            self.assertNotIn("<img src=x", html)
            # d3-selection implements selection.html() with innerHTML, so this
            # invariant is asserted against our own script, not the bundle.
            self.assertNotIn(".innerHTML", _APP_SCRIPT)
            # light theme only
            self.assertNotIn("prefers-color-scheme", html)
            self.assertIn('"language":"zh"', html)

    def test_zero_nodes_does_not_overwrite_an_existing_overview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clawshelf = root / "clawshelf"
            clawshelf.mkdir()
            overview = clawshelf / OVERVIEW_NAME
            overview.write_text("keep me", encoding="utf-8")

            with self.assertRaises(OverviewError):
                generate_overview(root, language="en")

            self.assertEqual(overview.read_text(encoding="utf-8"), "keep me")

    def test_cli_prints_json_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(root, "note", "note.md", "Note", "md", ["topic"])
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                status = overview_main([str(root), "--lang", "en"])

            result = json.loads(stdout.getvalue())
            self.assertEqual(status, 0)
            self.assertEqual(result["status"], "generated")
            self.assertEqual(result["node_count"], 1)
            self.assertEqual(result["edge_count"], 0)
            self.assertTrue(result["file_url"].startswith("file:///"))
            self.assertEqual(
                result["markdown_link"],
                f"[打开概览]({result['file_url']})",
            )
            self.assertTrue(Path(result["path"]).is_file())

    # ---- neuron / synapse model ----

    def test_axo_dendritic_and_axo_axonic_synapses_are_computed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(
                root, "a", "a.md", "Alpha", "md", ["community monitoring"],
                axon=[
                    ("Strong Application Method", "Publish monitoring data with a decision path for local groups in river restoration."),
                    ("Strong Contribution", "Centralized monitoring lowers cost while restoration outcomes fall for community observers."),
                ],
                dendrite=[("Metric Choice", "Restoration success needs an explicit outcome measure.")],
            )
            self._write_record(
                root, "b", "b.md", "Beta", "md", ["community monitoring"],
                axon=[("Strong Limitation", "The note reports no restoration outcomes for community observers.")],
                dendrite=[
                    ("Extension Hint", "Compare restoration outcomes across data-sharing practices for local groups."),
                    ("Data / Domain Boundary", "The claim is limited to community-led river restoration."),
                ],
            )

            payload, warnings = build_overview_data(root, ShelfConfig(), language="en")
            synapses = payload["synapses"]
            signals = {
                signal["id"]: (node["id"], signal["polarity"])
                for node in payload["nodes"]
                for signal in (*node["axon"], *node["dendrite"])
            }

            self.assertEqual(warnings, [])
            kinds = {item["kind"] for item in synapses}
            self.assertIn("axo_dendritic", kinds)
            self.assertIn("axo_axonic", kinds)

            for synapse in synapses:
                self.assertLess(synapse["source"], synapse["target"])
                source_node, source_polarity = signals[synapse["source_signal"]]
                target_node, target_polarity = signals[synapse["target_signal"]]
                self.assertEqual(source_node, synapse["source"])
                self.assertEqual(target_node, synapse["target"])
                polarities = {source_polarity, target_polarity}
                if synapse["kind"] == "axo_axonic":
                    self.assertEqual(polarities, {"axon"})
                else:
                    self.assertEqual(polarities, {"axon", "dendrite"})
                self.assertTrue(synapse["source_evidence"])
                self.assertTrue(synapse["target_evidence"])

    def test_signal_and_synapse_ids_are_stable_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(root, "a", "a.md", "Alpha", "md", ["monitoring"], axon=AXON)
            self._write_record(root, "b", "b.md", "Beta", "md", ["monitoring"], dendrite=DENDRITE)

            first, _ = build_overview_data(root, ShelfConfig(), language="en")
            second, _ = build_overview_data(root, ShelfConfig(), language="en")

            def signal_ids(payload: dict) -> list[str]:
                return [
                    signal["id"]
                    for node in payload["nodes"]
                    for signal in (*node["axon"], *node["dendrite"])
                ]

            self.assertTrue(signal_ids(first))
            self.assertEqual(signal_ids(first), signal_ids(second))
            self.assertEqual(
                [item["id"] for item in first["synapses"]],
                [item["id"] for item in second["synapses"]],
            )

    def test_incompatible_signal_types_never_synapse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Assumption x Metric Choice is in neither pair table.
            self._write_record(
                root, "a", "a.md", "Alpha", "md", ["monitoring"],
                dendrite=[("Assumption", "Shared monitoring data changes restoration outcomes.")],
            )
            self._write_record(
                root, "b", "b.md", "Beta", "md", ["monitoring"],
                dendrite=[("Metric Choice", "Shared monitoring data needs an outcome measure.")],
            )

            payload, _ = build_overview_data(root, ShelfConfig(), language="en")

            self.assertEqual(payload["synapses"], [])

    def test_signals_without_evidence_are_not_synapsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(
                root, "a", "a.md", "Alpha", "md", ["monitoring"],
                axon=[("Strong Method", "Community monitoring compares restoration outcomes across sites.")],
                evidence="",
            )
            self._write_record(
                root, "b", "b.md", "Beta", "md", ["monitoring"],
                dendrite=[("Extension Hint", "Community monitoring compares restoration outcomes across sites.")],
            )

            payload, _ = build_overview_data(root, ShelfConfig(), language="en")
            alpha = next(node for node in payload["nodes"] if node["title"] == "Alpha")

            self.assertEqual(payload["synapses"], [])
            self.assertEqual(len(alpha["axon"]), 1)
            self.assertFalse(alpha["axon"][0]["has_evidence"])
            self.assertEqual(alpha["synapse_count"], 0)

    def test_synapse_caps_hold_on_a_dense_shelf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(8):
                self._write_record(
                    root, f"n{index}", f"n{index}.md", f"Node {index}", "md",
                    ["community monitoring"],
                    axon=[
                        ("Strong Application Method", "Publish monitoring data with a decision path for local groups."),
                        ("Strong Method", "Community monitoring compares restoration outcomes across sites."),
                    ],
                    dendrite=[
                        ("Extension Hint", "Compare restoration outcomes across data-sharing practices."),
                        ("Data / Domain Boundary", "Monitoring data claims are limited to community-led restoration."),
                    ],
                )

            payload, _ = build_overview_data(root, ShelfConfig(), language="en")
            synapses = payload["synapses"]
            self.assertTrue(synapses)
            self.assertLessEqual(len(synapses), SYNAPSE_GLOBAL_CAP)

            per_signal: dict[str, int] = {}
            per_pair: dict[tuple[str, str, str], int] = {}
            per_node: dict[str, int] = {}
            for synapse in synapses:
                for key in ("source_signal", "target_signal"):
                    per_signal[synapse[key]] = per_signal.get(synapse[key], 0) + 1
                pair = (synapse["source"], synapse["target"], synapse["kind"])
                per_pair[pair] = per_pair.get(pair, 0) + 1
                for key in ("source", "target"):
                    per_node[synapse[key]] = per_node.get(synapse[key], 0) + 1

            self.assertLessEqual(max(per_signal.values()), SYNAPSE_PER_SIGNAL)
            self.assertLessEqual(max(per_pair.values()), SYNAPSE_PER_PAIR)
            self.assertLessEqual(max(per_node.values()), SYNAPSE_PER_NODE)

    def test_confirmed_synapse_supersedes_the_computed_duplicate(self) -> None:
        signal = "Publish monitoring data with a decision path for local groups."
        target = "Compare restoration outcomes across data-sharing practices."
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(
                root, "a", "a.md", "Alpha", "md", ["community monitoring"],
                axon=[("Strong Application Method", signal)],
            )
            self._write_record(
                root, "b", "b.md", "Beta", "md", ["community monitoring"],
                dendrite=[("Extension Hint", target)],
            )
            events = root / "clawshelf" / "events"
            events.mkdir(parents=True, exist_ok=True)
            event = self._event(root, "a.md", "b.md", score=17)
            candidate = event["linked_sources"][0]["idea_candidates"][0]
            candidate["new_signal"] = signal
            candidate["linked_signal"] = target
            candidate["new_signal_type"] = "Strong Application Method"
            candidate["linked_signal_type"] = "Extension Hint"
            (events / "spark.json").write_text(json.dumps(event), encoding="utf-8")

            payload, _ = build_overview_data(root, ShelfConfig(), language="en")
            nodes = {node["title"]: node for node in payload["nodes"]}
            source_signal = nodes["Alpha"]["axon"][0]["id"]
            target_signal = nodes["Beta"]["dendrite"][0]["id"]
            matching = [
                item
                for item in payload["synapses"]
                if {item["source_signal"], item["target_signal"]}
                == {source_signal, target_signal}
            ]

            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["class"], "confirmed")
            self.assertTrue(matching[0]["also_computed"])
            self.assertTrue(matching[0]["components"])
            self.assertEqual(matching[0]["edge"], payload["edges"][0]["id"])

    def test_confirmed_synapse_falls_back_to_a_soma_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(
                root, "a", "a.md", "Alpha", "md", ["monitoring"],
                axon=[("Strong Method", "Community monitoring compares restoration outcomes.")],
            )
            self._write_record(
                root, "b", "b.md", "Beta", "md", ["monitoring"],
                dendrite=[("Extension Hint", "Extend the comparison to other catchments.")],
            )
            events = root / "clawshelf" / "events"
            events.mkdir(parents=True, exist_ok=True)
            event = self._event(root, "a.md", "b.md", score=17)
            candidate = event["linked_sources"][0]["idea_candidates"][0]
            candidate["new_signal"] = "an entirely paraphrased spark about budgets"
            candidate["linked_signal"] = "another paraphrase about procurement"
            (events / "spark.json").write_text(json.dumps(event), encoding="utf-8")

            payload, _ = build_overview_data(root, ShelfConfig(), language="en")
            confirmed = [
                item for item in payload["synapses"] if item["class"] == "confirmed"
            ]

            self.assertEqual(len(confirmed), 1)
            self.assertIsNone(confirmed[0]["source_signal"])
            self.assertIsNone(confirmed[0]["target_signal"])
            self.assertEqual(payload["stats"]["unanchored_confirmed"], 2)

    def test_isolate_record_renders_without_signals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(root, "budget", "budget.xlsx", "Budget", "xlsx", ["budget"])

            payload, warnings = build_overview_data(root, ShelfConfig(), language="en")
            node = payload["nodes"][0]

            self.assertEqual(warnings, [])
            self.assertEqual(node["axon"], [])
            self.assertEqual(node["dendrite"], [])
            self.assertEqual(node["signal_count"], 0)
            self.assertTrue(node["isolate"])
            self.assertEqual(payload["synapses"], [])
            self.assertEqual(payload["stats"]["isolates"], 1)

    # ---- CDN subresources ----

    def test_cdn_scripts_are_version_pinned_and_sri_protected(self) -> None:
        tags = cdn_script_tags()

        expected = [
            f"https://cdn.jsdelivr.net/npm/d3@{D3_VERSION}/dist/d3.min.js",
            f"https://cdn.jsdelivr.net/npm/d3-octree@{OCTREE_VERSION}/dist/d3-octree.min.js",
            f"https://cdn.jsdelivr.net/npm/d3-binarytree@{BINARYTREE_VERSION}"
            "/dist/d3-binarytree.min.js",
            f"https://cdn.jsdelivr.net/npm/d3-force-3d@{FORCE3D_VERSION}/dist/d3-force-3d.min.js",
        ]
        self.assertEqual([url for url, _ in CDN_SCRIPTS], expected)
        # load order matters: d3-force-3d's browser build expects d3.octree /
        # d3.binaryTree to already exist on the shared d3 global, and classic
        # script tags execute in document order
        positions = [tags.index(url) for url in expected]
        self.assertEqual(positions, sorted(positions))
        for url, integrity in CDN_SCRIPTS:
            with self.subTest(url=url):
                self.assertTrue(integrity.startswith("sha384-"))
                self.assertIn(f'src="{url}" integrity="{integrity}"', tags)
        self.assertEqual(tags.count('crossorigin="anonymous"'), len(CDN_SCRIPTS))

    def test_only_pinned_cdn_subresources_are_referenced(self) -> None:
        import re as _re

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(root, "a", "a.md", "Alpha", "md", ["monitoring"], axon=AXON)

            result = generate_overview(root, language="en")
            html = Path(result.path).read_text(encoding="utf-8")

            # the four pinned bundles are the only things the page may fetch
            self.assertEqual(
                sorted(_re.findall(r'\ssrc="([^"]+)"', html)),
                sorted(url for url, _ in CDN_SCRIPTS),
            )
            for pattern in (r'href="http', r"@import", r"url\(\s*http", r"XMLHttpRequest"):
                with self.subTest(pattern=pattern):
                    self.assertIsNone(_re.search(pattern, html))

    def test_ui_strings_cover_both_languages(self) -> None:
        english = _ui_strings("en")
        chinese = _ui_strings("zh")

        self.assertEqual(set(english), set(chinese))
        self.assertTrue(all(value.strip() for value in english.values()))
        self.assertTrue(all(value.strip() for value in chinese.values()))

    def test_page_declares_the_resolved_interface_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_record(
                root, "a", "a.md", "River Restoration", "md", ["restoration"],
                axon=AXON, dendrite=DENDRITE,
            )

            chinese = render_overview_html(
                build_overview_data(root, ShelfConfig(), language="zh")[0]
            )
            english = render_overview_html(
                build_overview_data(root, ShelfConfig(), language="en")[0]
            )

        self.assertIn('<html lang="zh-CN">', chinese)
        self.assertIn("<title>" + _ui_strings("zh")["title"] + "</title>", chinese)
        self.assertIn('<html lang="en">', english)
        self.assertIn("<title>" + _ui_strings("en")["title"] + "</title>", english)

    def test_auto_language_falls_back_to_chinese_without_a_usable_locale(self) -> None:
        cases = {
            "zh": [{}, {"LANG": "C"}, {"LC_ALL": "POSIX", "LANG": ""}, {"LANG": "zh_CN.UTF-8"}],
            "en": [{"LANG": "en_US.UTF-8"}, {"LC_ALL": "de_DE.UTF-8", "LANG": "C"}],
        }
        for expected, environments in cases.items():
            for environment in environments:
                with self.subTest(env=environment):
                    patched = {name: "" for name in ("LC_ALL", "LC_MESSAGES", "LANG")}
                    patched.update(environment)
                    with mock.patch.dict(os.environ, patched, clear=False):
                        self.assertEqual(_resolve_language("auto"), expected)
                        # an explicit choice is never second-guessed
                        self.assertEqual(_resolve_language("en"), "en")
                        self.assertEqual(_resolve_language("zh"), "zh")

    def test_synapse_computation_stays_within_budget(self) -> None:
        import time

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(60):
                self._write_record(
                    root, f"n{index}", f"n{index}.md", f"Node {index}", "md",
                    [f"topic {index % 7}"],
                    axon=[
                        ("Strong Application Method", f"Publish monitoring data for cohort {index % 5}."),
                        ("Strong Method", "Community monitoring compares restoration outcomes across sites."),
                        ("Strong Contribution", f"Centralized reporting lowers cost in region {index % 4}."),
                        ("Strong Limitation", "The record reports no restoration outcomes."),
                    ],
                    dendrite=[
                        ("Extension Hint", "Compare restoration outcomes across data-sharing practices."),
                        ("Data / Domain Boundary", "Claims are limited to community-led restoration."),
                        ("Failure Mode", "Data sharing may fail without decision authority."),
                        ("Metric Choice", "Restoration success requires an explicit outcome measure."),
                        ("Assumption", "Access to monitoring data changes restoration outcomes."),
                    ],
                )

            started = time.monotonic()
            payload, _ = build_overview_data(root, ShelfConfig(), language="en")
            elapsed = time.monotonic() - started

            self.assertEqual(len(payload["nodes"]), 60)
            self.assertLessEqual(len(payload["synapses"]), SYNAPSE_GLOBAL_CAP)
            self.assertLess(elapsed, 15.0)

    def _write_record(
        self,
        root: Path,
        name: str,
        source: str,
        title: str,
        source_type: str,
        topics: list[str],
        axon: list[tuple[str, str]] | None = None,
        dendrite: list[tuple[str, str]] | None = None,
        evidence: str = "section: Summary",
    ) -> None:
        normalized = root / "clawshelf" / "normalized"
        normalized.mkdir(parents=True, exist_ok=True)
        topic_lines = "\n".join(f"- {topic}" for topic in topics)
        primary = topics[0]
        signals = ""
        for heading, entries in (("Axon Signals", axon), ("Dendrite Signals", dendrite)):
            if not entries:
                continue
            body = "\n".join(
                f"- type: {signal_type}\n  signal: {text}\n  evidence: {evidence}"
                for signal_type, text in entries
            )
            signals += f"\n## {heading}\n\n{body}\n"
        record = f"""---
source: {source}
source_type: {source_type}
source_sha256: fixture
extraction_method: text
confidence: High
---

# {title}

## Summary

This source studies {primary} with evidence-backed methods and findings (source: `{source}`, section: Summary). It records limitations for comparison (source: `{source}`, section: Limitations).

## Topics

{topic_lines}

## Keywords

- `{primary}` — central concept; evidence: section: Summary
- `shared benchmark` — comparison concept; evidence: section: Methods

## RAG Terms

- term: {primary}
  weight: 5
  aliases: none
  evidence: section: Summary
  role: topic

## Knowledge Map Tags

- Domain: research
- Problem fit: test
- Map role: evidence
{signals}"""
        (normalized / f"{name}.md").write_text(record, encoding="utf-8")

    def _event(
        self,
        root: Path,
        new_source: str,
        linked_source: str,
        *,
        score: int,
        idea_type: str = "innovation",
        signal: str = "idea spark",
        created_at: str = "2026-07-26T05:00:00+00:00",
    ) -> dict:
        return {
            "schema": "clawshelf.watch-event",
            "created_at": created_at,
            "priority": "P1",
            "classification": "P1",
            "linked_sources": [
                {
                    "new_source_path": str((root / new_source).resolve()),
                    "linked_source_path": str((root / linked_source).resolve()),
                    "creativity_score": score,
                    "confidence": 0.8,
                    "verdict": "p1_candidate",
                    "matched_evidence": [
                        {
                            "signal": signal,
                            "why_it_matters": "useful relation",
                            "new_evidence": f"source: {new_source}",
                            "linked_evidence": f"source: {linked_source}",
                        }
                    ],
                    "idea_candidates": [
                        {
                            "idea_type": idea_type,
                            "new_signal_type": "Strong Method",
                            "linked_signal_type": "Extension Hint",
                            "new_signal": signal,
                            "linked_signal": f"{signal} target",
                            "new_evidence": f"source: {new_source}",
                            "linked_evidence": f"source: {linked_source}",
                            "total_score": score,
                        }
                    ],
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
