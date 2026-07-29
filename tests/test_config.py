from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clawshelf.config import ConfigError, effective_config, load_or_create_config, parse_config
from openclaw_watch_adapter import build_notification


class ConfigTests(unittest.TestCase):
    def test_creates_inferred_config_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "quant-trading"
            root.mkdir()
            (root / "retail-flow.md").write_text("source", encoding="utf-8")

            config = load_or_create_config(root)

            self.assertTrue((root / "clawshelf" / "clawshelf-config.json").is_file())
            self.assertEqual(config.notification_policy, "p1_p2")
            self.assertEqual(config.creativity_scoring.semantic_retrieval, "auto")
            self.assertEqual(config.creativity_scoring.semantic_candidate_target, 3)
            self.assertIsNone(config.delivery_binding)
            self.assertEqual(config.shelf_plan["domain_background"], "financial/investment research")
            self.assertEqual(len(config.fingerprint), 64)

    def test_rejects_invalid_persisted_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "clawshelf").mkdir()
            (root / "clawshelf" / "clawshelf-config.json").write_text('{"schema":"wrong"}', encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_or_create_config(root)

    def test_one_run_overrides_do_not_change_persisted_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_or_create_config(root)
            effective = effective_config(
                config,
                Namespace(
                    notification_policy="p1_only",
                    creativity_scorer=None,
                    creativity_model=None,
                    novelty_preference=1.0,
                    candidate_limit=None,
                    creativity_threshold=15,
                    creativity_min_confidence=0.8,
                ),
            )

            self.assertEqual(effective.notification_policy, "p1_only")
            self.assertEqual(effective.creativity_scoring.novelty_preference, 1.0)
            self.assertEqual(effective.creativity_scoring.advanced.threshold, 15)
            self.assertEqual(load_or_create_config(root).notification_policy, "p1_p2")

    def test_notification_policy_controls_p2_delivery(self) -> None:
        event = {"priority": "P2", "new_files": [], "linked_sources": []}
        self.assertTrue(build_notification(Path("event.json"), event)["enabled"])
        self.assertFalse(build_notification(Path("event.json"), event, "p1_only")["enabled"])
        self.assertTrue(build_notification(Path("event.json"), event, "p1_p2")["enabled"])

    def test_config_requires_valid_novelty_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_or_create_config(Path(directory))
            payload = config.to_dict()
            payload["creativity_scoring"]["novelty_preference"] = 1.1
            with self.assertRaises(ConfigError):
                parse_config(json.dumps(payload))

    def test_config_does_not_accept_the_removed_semantic_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_or_create_config(Path(directory))
            payload = config.to_dict()
            payload["semantic_scoring"] = payload.pop("creativity_scoring")

            with self.assertRaisesRegex(ConfigError, "creativity_scoring"):
                parse_config(json.dumps(payload))

    def test_semantic_retrieval_settings_are_validated_inside_creativity_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_or_create_config(Path(directory))
            payload = config.to_dict()
            payload["creativity_scoring"]["semantic_retrieval"] = "sometimes"

            with self.assertRaisesRegex(ConfigError, "semantic_retrieval"):
                parse_config(json.dumps(payload))

    def test_delivery_binding_is_plaintext_and_validated_against_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_or_create_config(Path(directory))
            payload = config.to_dict()
            payload["delivery_binding"] = {
                "agent": "agent-test",
                "session": "agent:agent-test:feishu:agent-test:direct:ou_test",
                "channel": "feishu",
                "target": "user:ou_test",
                "account": "agent-test",
            }

            parsed = parse_config(json.dumps(payload))

            self.assertEqual(parsed.delivery_binding.agent, "agent-test")
            self.assertEqual(parsed.delivery_binding.target, "user:ou_test")
            payload["delivery_binding"]["agent"] = "other-agent"
            with self.assertRaisesRegex(ConfigError, "must match the agent"):
                parse_config(json.dumps(payload))
