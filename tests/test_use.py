from __future__ import annotations

import sys
import tempfile
import unittest
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from openclaw_use import (
    DeliveryRoute,
    build_watcher_command,
    check_readiness,
    ensure_watcher,
    infer_shelf_plan,
    reset_folder_watcher,
    resolve_shelf_root,
    resolve_delivery_route,
    start_watcher,
    main as use_main,
    use_folder,
    watcher_processes,
)
from clawshelf.config import ConfigError, load_or_create_config


SESSION_KEY = "agent:agent-test:feishu:agent-test:direct:ou_test"
ROUTE_KWARGS = {
    "agent_id": "agent-test",
    "channel": "feishu",
    "session_key": SESSION_KEY,
    "reply_target": "user:ou_test",
    "reply_account": "agent-test",
}


class UseCommandTests(unittest.TestCase):
    def test_resolves_recent_session_from_openclaw_command_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "commands.log"
            log_path.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "timestamp": "2026-07-25T21:00:00Z",
                            "sessionKey": "agent:agent-test:feishu:agent-test:direct:old",
                            "source": "feishu",
                            "senderId": "ou_old",
                        }),
                        json.dumps({
                            "timestamp": "2026-07-25T21:04:00Z",
                            "sessionKey": "agent:agent-test:feishu:agent-test:direct:current",
                            "source": "feishu",
                            "senderId": "ou_current",
                        }),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(
                resolve_delivery_route(
                    agent_id="agent-test",
                    channel="last",
                    commands_log=log_path,
                    now=datetime(2026, 7, 25, 21, 5, tzinfo=timezone.utc),
                ),
                DeliveryRoute(
                    agent_id="agent-test",
                    channel="feishu",
                    session_key="agent:agent-test:feishu:agent-test:direct:current",
                    reply_target="user:ou_current",
                    reply_account="agent-test",
                ),
            )

    def test_session_discovery_does_not_cross_agent_or_use_stale_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "commands.log"
            log_path.write_text(
                json.dumps({
                    "timestamp": "2026-07-25T20:00:00Z",
                    "sessionKey": "agent:other:feishu:other:direct:user",
                    "source": "feishu",
                })
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                resolve_delivery_route(
                    agent_id="agent-test",
                    channel="feishu",
                    commands_log=log_path,
                    now=datetime(2026, 7, 25, 21, 0, tzinfo=timezone.utc),
                )

    def test_explicit_session_key_wins_over_discovery(self) -> None:
        self.assertEqual(
            resolve_delivery_route(
                "agent:agent-test:feishu:agent-test:direct:explicit",
                agent_id="agent-test",
                channel="feishu",
            ),
            DeliveryRoute(
                agent_id="agent-test",
                channel="feishu",
                session_key="agent:agent-test:feishu:agent-test:direct:explicit",
                reply_account="agent-test",
            ),
        )

    def test_explicit_agent_must_match_canonical_session(self) -> None:
        with self.assertRaisesRegex(ConfigError, "does not match session agent"):
            resolve_delivery_route(
                SESSION_KEY,
                agent_id="other-agent",
                channel="feishu",
            )

    def test_ready_folder_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (root / "clawshelf" / "clawshelf-metadata.md").write_text("# Metadata\n", encoding="utf-8")
            (normalized / "source.md").write_text("---\nsource: note.md\n---\n", encoding="utf-8")
            (root / "note.md").write_text("source text", encoding="utf-8")

            readiness = check_readiness(root)

            self.assertEqual(readiness["status"], "ready")
            self.assertEqual(readiness["normalized_records"], 1)
            self.assertEqual(readiness["missing"], [])

    def test_watcher_process_detection_is_folder_specific(self) -> None:
        root = Path("/tmp/clawshelf-a").resolve()
        other = Path("/tmp/clawshelf-b").resolve()
        lines = [
            f"123 uv run python scripts/openclaw-watch-adapter.py {root} --poll-seconds 5",
            f"456 uv run python scripts/openclaw-watch-adapter.py {other} --poll-seconds 5",
        ]

        matches = watcher_processes(root, lines)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["pid"], 123)

    def test_build_watcher_command_binds_provider_and_session(self) -> None:
        command = build_watcher_command(
            Path("/tmp/shelf"),
            ROOT,
            agent_id="agent-test",
            channel="feishu",
            session_key="agent:agent-test:feishu:agent-test:direct:user",
            reply_target="user:ou_test",
            reply_account="agent-test",
            poll_seconds=5.0,
        )
        rendered = " ".join(command)

        self.assertIn("openclaw-watch-adapter.py", rendered)
        self.assertIn("--channel feishu", rendered)
        self.assertIn("--agent-id agent-test", rendered)
        self.assertIn("--session-key agent:agent-test:feishu:agent-test:direct:user", rendered)
        self.assertIn("--reply-to user:ou_test", rendered)
        self.assertIn("--reply-account agent-test", rendered)
        self.assertNotIn("owner-id", rendered)
        self.assertNotIn("open_id", rendered)
        self.assertNotIn("chat_id", rendered)

    def test_start_watcher_persists_complete_initial_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("openclaw_use.subprocess.Popen") as popen:
                popen.return_value.pid = 4321
                state = start_watcher(root, ROOT, **ROUTE_KWARGS)

            self.assertEqual(state["agent_id"], "agent-test")
            self.assertEqual(state["channel"], "feishu")
            self.assertEqual(state["session_key"], SESSION_KEY)
            self.assertEqual(state["reply_target"], "user:ou_test")
            self.assertEqual(state["reply_account"], "agent-test")
            persisted = json.loads(
                (root / "clawshelf" / "watch-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(persisted, state)

    def test_use_folder_resets_existing_watcher_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (root / "clawshelf" / "clawshelf-metadata.md").write_text("# Metadata\n", encoding="utf-8")
            (normalized / "source.md").write_text("---\nsource: note.md\n---\n", encoding="utf-8")
            lines = [f"123 uv run python scripts/openclaw-watch-adapter.py {root.resolve()} --poll-seconds 5"]

            with patch("openclaw_use.start_watcher") as start:
                start.return_value = {"pid": 789, "log_path": str(root / "clawshelf" / "watch.log")}
                result = use_folder(root, ROOT, process_lines=lines, **ROUTE_KWARGS)

            start.assert_called_once()
            self.assertTrue(result["watcher"]["exists"])
            self.assertTrue(result["watcher"]["auto_started"])
            self.assertTrue(result["watcher"]["reset"])
            self.assertEqual(result["watcher"]["status"], "restarted")
            self.assertEqual([item["pid"] for item in result["watcher"]["stopped_processes"]], [123])

    def test_use_folder_can_keep_existing_watcher_with_no_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (root / "clawshelf" / "clawshelf-metadata.md").write_text("# Metadata\n", encoding="utf-8")
            (normalized / "source.md").write_text("---\nsource: note.md\n---\n", encoding="utf-8")
            lines = [f"123 uv run python scripts/openclaw-watch-adapter.py {root.resolve()} --poll-seconds 5"]

            with patch("openclaw_use.start_watcher") as start:
                result = use_folder(
                    root,
                    ROOT,
                    reset_watcher=False,
                    process_lines=lines,
                    **ROUTE_KWARGS,
                )

            start.assert_not_called()
            self.assertTrue(result["watcher"]["exists"])
            self.assertFalse(result["watcher"]["auto_started"])
            self.assertFalse(result["watcher"]["reset"])
            self.assertEqual(result["watcher"]["status"], "running")

    def test_use_folder_resets_multiple_existing_watchers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (root / "clawshelf" / "clawshelf-metadata.md").write_text("# Metadata\n", encoding="utf-8")
            (normalized / "source.md").write_text("---\nsource: note.md\n---\n", encoding="utf-8")
            lines = [
                f"123 uv run python scripts/openclaw-watch-adapter.py {root.resolve()} --poll-seconds 5",
                f"456 uv run python scripts/openclaw-watch-adapter.py {root.resolve()} --poll-seconds 5",
            ]

            with patch("openclaw_use.start_watcher") as start:
                start.return_value = {"pid": 789, "log_path": str(root / "clawshelf" / "watch.log")}
                result = use_folder(root, ROOT, process_lines=lines, **ROUTE_KWARGS)

            start.assert_called_once()
            self.assertEqual([item["pid"] for item in result["watcher"]["stopped_processes"]], [123, 456])
            self.assertEqual(result["watcher"]["processes"][0]["pid"], 789)

    def test_reset_folder_watcher_only_resets_ready_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (root / "clawshelf" / "clawshelf-metadata.md").write_text("# Metadata\n", encoding="utf-8")
            (normalized / "source.md").write_text("---\nsource: note.md\n---\n", encoding="utf-8")
            lines = [f"123 uv run python scripts/openclaw-watch-adapter.py {root.resolve()} --poll-seconds 5"]

            with patch("openclaw_use.start_watcher") as start:
                start.return_value = {"pid": 789, "log_path": str(root / "clawshelf" / "watch.log")}
                result = reset_folder_watcher(
                    root, ROOT, process_lines=lines, **ROUTE_KWARGS
                )

            start.assert_called_once()
            self.assertEqual(result["readiness"]["status"], "ready")
            self.assertEqual(result["watcher"]["status"], "restarted")
            self.assertFalse(result["quick_onboard"]["performed"])

    def test_reset_folder_watcher_does_not_start_partial_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "clawshelf").mkdir()
            (root / "note.md").write_text("source text", encoding="utf-8")

            with patch("openclaw_use.start_watcher") as start:
                result = reset_folder_watcher(root, ROOT, process_lines=[])

            start.assert_not_called()
            self.assertEqual(result["readiness"]["status"], "partial")
            self.assertEqual(result["next_action"], "repair")
            self.assertFalse(result["watcher"]["exists"])

    def test_use_folder_auto_starts_missing_watcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "clawshelf" / "normalized"
            normalized.mkdir(parents=True)
            (root / "clawshelf" / "clawshelf-metadata.md").write_text("# Metadata\n", encoding="utf-8")
            (normalized / "source.md").write_text("---\nsource: note.md\n---\n", encoding="utf-8")

            with patch("openclaw_use.start_watcher") as start:
                start.return_value = {
                    "pid": 789,
                    "log_path": str(root / "clawshelf" / "watch.log"),
                    "delivery_mode": "session_key",
                    "session_key": "agent:agent-test:feishu:agent-test:direct:user",
                }
                result = use_folder(
                    root,
                    ROOT,
                    process_lines=[],
                    **ROUTE_KWARGS,
                )

            start.assert_called_once_with(
                root.resolve(),
                ROOT,
                agent_id="agent-test",
                channel="feishu",
                session_key=SESSION_KEY,
                reply_target="user:ou_test",
                reply_account="agent-test",
                poll_seconds=5.0,
            )
            self.assertTrue(result["watcher"]["exists"])
            self.assertTrue(result["watcher"]["auto_started"])
            self.assertEqual(result["watcher"]["state"]["pid"], 789)
            self.assertEqual(result["watcher"]["state"]["delivery_mode"], "session_key")
            self.assertEqual(result["watcher"]["status"], "reset_started")
            self.assertTrue(result["watcher"]["reset"])
            self.assertEqual(result["watcher"]["watched_root"], str(root.resolve()))
            self.assertTrue(result["watcher"]["event_dir"].endswith("clawshelf/events"))
            persisted_config = json.loads(
                (root / "clawshelf" / "clawshelf-config.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                persisted_config["delivery_binding"],
                {
                    "agent": "agent-test",
                    "session": SESSION_KEY,
                    "channel": "feishu",
                    "target": "user:ou_test",
                    "account": "agent-test",
                },
            )

    def test_reset_uses_user_edited_delivery_binding_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_or_create_config(root)
            payload = config.to_dict()
            payload["delivery_binding"] = {
                "agent": "agent-9",
                "session": "agent:agent-9:feishu:agent-9:direct:ou_nine",
                "channel": "feishu",
                "target": "user:ou_nine",
                "account": "agent-9",
            }
            config_path = root / "clawshelf" / "clawshelf-config.json"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            result = {
                "readiness": {"status": "ready"},
                "watcher": {"status": "restarted"},
            }

            with patch("openclaw_use.reset_folder_watcher", return_value=result) as reset, patch(
                "builtins.print"
            ):
                exit_code = use_main([str(root), "--reset-only"])

            self.assertEqual(exit_code, 0)
            kwargs = reset.call_args.kwargs
            self.assertEqual(kwargs["agent_id"], "agent-9")
            self.assertEqual(
                kwargs["session_key"],
                "agent:agent-9:feishu:agent-9:direct:ou_nine",
            )
            self.assertEqual(kwargs["reply_target"], "user:ou_nine")
            self.assertEqual(kwargs["reply_account"], "agent-9")

    def test_use_folder_runs_quick_onboard_for_new_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "note.md").write_text("source text", encoding="utf-8")

            with patch("openclaw_use.start_watcher") as start:
                start.return_value = {
                    "pid": 789,
                    "log_path": str(root / "clawshelf" / "watch.log"),
                    "delivery_mode": "session_key",
                }
                result = use_folder(root, ROOT, process_lines=[], **ROUTE_KWARGS)

            start.assert_called_once()
            self.assertEqual(result["readiness"]["status"], "ready")
            self.assertEqual(result["next_action"], "ask_or_refresh")
            self.assertTrue(result["quick_onboard"]["needed"])
            self.assertTrue(result["quick_onboard"]["performed"])
            self.assertEqual(result["quick_onboard"]["ask_policy"], "persisted_auto_accept")
            self.assertTrue((root / "clawshelf" / "clawshelf-config.json").is_file())
            prefill = result["quick_onboard"]["shelf_plan_prefill"]
            self.assertFalse(prefill["requires_confirmation"])
            self.assertEqual(
                set(prefill["fields"]),
                {
                    "domain_background",
                    "work_direction",
                    "concrete_problem",
                    "collection_pattern",
                    "companion_mode",
                },
            )
            self.assertTrue(prefill["fields"]["domain_background"]["confirmed"])
            self.assertEqual(result["quick_onboard"]["processed"], 0)
            self.assertEqual(result["quick_onboard"]["skipped"], 1)
            self.assertTrue((root / "clawshelf" / "clawshelf-metadata.md").is_file())
            self.assertEqual(len(list((root / "clawshelf" / "normalized").glob("*.md"))), 0)
            self.assertEqual(result["readiness"]["pending_sources"], 1)
            self.assertTrue(result["watcher"]["exists"])

    def test_use_folder_resolves_generated_clawshelf_dir_to_parent_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "clawshelf"
            normalized = generated / "normalized"
            normalized.mkdir(parents=True)
            (generated / "clawshelf-metadata.md").write_text("# Metadata\n", encoding="utf-8")
            (normalized / "source.md").write_text("---\nsource: note.md\n---\n", encoding="utf-8")
            (root / "note.md").write_text("source text", encoding="utf-8")

            with patch("openclaw_use.start_watcher") as start:
                start.return_value = {"pid": 789, "log_path": str(generated / "watch.log")}
                result = use_folder(
                    generated, ROOT, process_lines=[], **ROUTE_KWARGS
                )

            self.assertEqual(resolve_shelf_root(generated), root.resolve())
            self.assertEqual(result["folder"], str(root.resolve()))
            self.assertEqual(result["requested_folder"], str(generated.resolve()))
            start.assert_called_once()
            self.assertFalse((generated / "clawshelf").exists())

    def test_ensure_watcher_restarts_stale_watch_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "clawshelf"
            normalized = generated / "normalized"
            normalized.mkdir(parents=True)
            (generated / "clawshelf-metadata.md").write_text("# Metadata\n", encoding="utf-8")
            (normalized / "source.md").write_text("---\nsource: note.md\n---\n", encoding="utf-8")
            (generated / "watch-state.json").write_text(
                '{"schema":"clawshelf.watch-state","folder":"' + str(root.resolve()) + '","pid":999999}',
                encoding="utf-8",
            )

            with patch("openclaw_use.start_watcher") as start:
                start.return_value = {"pid": 789, "log_path": str(generated / "watch.log")}
                watcher = ensure_watcher(
                    root, ROOT, process_lines=[], **ROUTE_KWARGS
                )

            start.assert_called_once()
            self.assertEqual(watcher["status"], "restarted")
            self.assertTrue(watcher["stale_state"])
            self.assertTrue(watcher["auto_started"])

    def test_ensure_watcher_reports_stale_when_no_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "clawshelf"
            normalized = generated / "normalized"
            normalized.mkdir(parents=True)
            (generated / "clawshelf-metadata.md").write_text("# Metadata\n", encoding="utf-8")
            (normalized / "source.md").write_text("---\nsource: note.md\n---\n", encoding="utf-8")
            (generated / "watch-state.json").write_text(
                '{"schema":"clawshelf.watch-state","folder":"' + str(root.resolve()) + '","pid":999999}',
                encoding="utf-8",
            )

            with patch("openclaw_use.start_watcher") as start:
                watcher = ensure_watcher(root, ROOT, auto_start=False, process_lines=[])

            start.assert_not_called()
            self.assertEqual(watcher["status"], "stale")
            self.assertTrue(watcher["stale_state"])
            self.assertFalse(watcher["exists"])

    def test_infer_shelf_plan_prefills_quant_trading_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "quant-trading"
            root.mkdir()
            (root / "Systematic Edges in Prediction Markets _ QuantPedia.pdf").write_text("pdf", encoding="utf-8")
            (root / "2025_institutional_liquidity_costs.pdf").write_text("pdf", encoding="utf-8")

            prefill = infer_shelf_plan(root)

            self.assertTrue(prefill["requires_confirmation"])
            fields = prefill["fields"]
            self.assertEqual(fields["domain_background"]["value"], "financial/investment research")
            self.assertEqual(fields["work_direction"]["value"], "idea discovery")
            self.assertEqual(fields["concrete_problem"]["value"], "identify gaps/risks")
            self.assertEqual(fields["collection_pattern"]["value"], "project-by-project archive")
            self.assertEqual(fields["companion_mode"]["value"], "investment research assistant")

    def test_use_folder_reports_repair_for_partial_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "clawshelf").mkdir()
            (root / "note.md").write_text("source text", encoding="utf-8")

            with patch("openclaw_use.start_watcher") as start:
                result = use_folder(root, ROOT, process_lines=[], **ROUTE_KWARGS)

            start.assert_called_once()
            self.assertEqual(result["readiness"]["status"], "ready")
            self.assertEqual(result["next_action"], "ask_or_refresh")
            self.assertTrue(result["quick_onboard"]["needed"])
            self.assertTrue(result["quick_onboard"]["performed"])
            self.assertEqual(result["readiness"]["pending_sources"], 1)


if __name__ == "__main__":
    unittest.main()
