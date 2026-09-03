#!/usr/bin/env python3
"""Write-helper tests. Identity required. Dangling aggregates fail. Unowned types fail."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ots_common.py"


def run(args, env=None, bundle=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    cmd = [sys.executable, str(SCRIPT), *args]
    if bundle is not None and "--bundle" not in args:
        cmd += ["--bundle", bundle]
    return subprocess.run(cmd, capture_output=True, text=True, env=e)


class TestOts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_without_identity_fails(self):
        env = os.environ.copy()
        env.pop("SECOND_BRAIN_IDENTITY", None)
        r = run(
            ["write-aggregate", "--kind", "year", "--period", "2026", "--bundle", self.bundle],
            env=env,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("identity", r.stdout.lower())

    def test_path_for_week_nests_under_start_month(self):
        r = run(["path-for", "--kind", "week", "--period", "2026-W34"])
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["path"], "okf/temporal/2026/08/W34/2026-W34.md")

    def test_path_for_session_double_underscore(self):
        r = run(
            [
                "path-for",
                "--kind",
                "session",
                "--period",
                "2026-08-21T14",
                "--slug",
                "software_engineer__atlas__001",
            ]
        )
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertTrue(data["path"].endswith("sessions/software_engineer__atlas__001.md"))

    def test_invalid_session_slug_rejected(self):
        r = run(
            [
                "write-session",
                "--id",
                "software_engineer_atlas_001",
                "--period",
                "2026-08-21T14",
                "--agent-name",
                "atlas",
                "--agent-role",
                "software_engineer",
                "--bundle",
                self.bundle,
                "--author",
                "claude-code/lumenfield-detector",
            ]
        )
        self.assertNotEqual(r.returncode, 0)

    def test_dangling_aggregate_fails(self):
        r = run(
            [
                "write-aggregate",
                "--kind",
                "week",
                "--period",
                "2026-W34",
                "--aggregates",
                "../21/2026-08-21.md",
                "--bundle",
                self.bundle,
                "--author",
                "claude-code/lumenfield-detector",
            ]
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dangling", r.stdout)

    def test_children_then_parent_validates(self):
        author = ["--author", "grok-bot/northstar-console"]
        b = ["--bundle", self.bundle]
        self.assertEqual(run(["init", *b], env={"SECOND_BRAIN_IDENTITY": "x"}).returncode, 0)
        self.assertEqual(
            run(["write-aggregate", "--kind", "day", "--period", "2026-08-21", "--status", "finalized", *b, *author]).returncode,
            0,
        )
        self.assertEqual(
            run(
                [
                    "write-aggregate",
                    "--kind",
                    "week",
                    "--period",
                    "2026-W34",
                    "--status",
                    "finalized",
                    "--aggregates",
                    "../21/2026-08-21.md",
                    *b,
                    *author,
                ]
            ).returncode,
            0,
        )
        r = run(["validate", *b])
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_unowned_type_fails_validate(self):
        p = Path(self.bundle) / "okf" / "temporal" / "bogus.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntype: Concept\ntitle: No\n---\n\n# No\n", encoding="utf-8")
        r = run(["validate", "--bundle", self.bundle])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unowned", r.stdout)

    def test_sample_validates(self):
        sample = ROOT / "sample-knowledge"
        if not sample.exists():
            self.skipTest("sample-knowledge not packed yet")
        r = run(["validate", "--bundle", str(sample)])
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_walk_sample_is_index_free_and_finds_sessions(self):
        sample = ROOT / "sample-knowledge"
        r = run(["walk", "--flat", "--bundle", str(sample)])
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertEqual(data["engine"], "filesystem")
        sessions = [n for n in data["nodes"] if n.get("kind") == "session"]
        ids = {n["id"] for n in sessions}
        self.assertEqual(
            ids,
            {
                "software_engineer__atlas__001",
                "software_engineer__atlas__002",
                "research__lumen__001",
            },
        )

    def test_write_session_ensure_spine_creates_parents(self):
        author = ["--author", "grok-bot/northstar-console"]
        r = run(
            [
                "write-session",
                "--id",
                "software_engineer__atlas__003",
                "--period",
                "2026-08-21T16",
                "--agent-name",
                "atlas",
                "--agent-role",
                "software_engineer",
                "--title",
                "Ensure spine",
                "--bundle",
                self.bundle,
                "--ensure-spine",
                *author,
            ]
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertTrue(data["ok"])
        self.assertTrue(any("2026.md" in p for p in data["spine"]))
        hour = Path(self.bundle) / "okf/temporal/2026/08/21/16/2026-08-21T16.md"
        self.assertTrue(hour.exists())
        session = Path(self.bundle) / "okf/temporal/2026/08/21/16/sessions/software_engineer__atlas__003.md"
        self.assertTrue(session.exists())
        hour_meta = hour.read_text(encoding="utf-8")
        self.assertIn("software_engineer__atlas__003.md", hour_meta)
        v = run(["validate", "--bundle", self.bundle])
        self.assertEqual(v.returncode, 0, v.stdout)

    def test_rollup_hour_links_sessions_without_rewriting_prose(self):
        author = ["--author", "grok-bot/northstar-console"]
        b = self.bundle
        run(
            [
                "write-session",
                "--id",
                "research__lumen__002",
                "--period",
                "2026-08-22T09",
                "--agent-name",
                "lumen",
                "--agent-role",
                "research",
                "--bundle",
                b,
                "--ensure-spine",
                *author,
            ]
        )
        hour = Path(b) / "okf/temporal/2026/08/22/09/2026-08-22T09.md"
        original = hour.read_text(encoding="utf-8")
        r = run(["rollup", "--kind", "hour", "--period", "2026-08-22T09", "--bundle", b, *author])
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertEqual(data["prose"], "unchanged")
        self.assertIn("(proposed)", hour.read_text(encoding="utf-8"))
        self.assertIn("## Summary", original)

    def test_write_session_does_not_create_hour_by_default(self):
        author = ["--author", "grok-bot/northstar-console"]
        r = run(
            [
                "write-session",
                "--id",
                "software_engineer__atlas__004",
                "--period",
                "2026-08-21T17",
                "--agent-name",
                "atlas",
                "--agent-role",
                "software_engineer",
                "--bundle",
                self.bundle,
                *author,
            ]
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertEqual(data["spine"], [])
        hour = Path(self.bundle) / "okf/temporal/2026/08/21/17/2026-08-21T17.md"
        self.assertFalse(hour.exists())
        session = Path(self.bundle) / "okf/temporal/2026/08/21/17/sessions/software_engineer__atlas__004.md"
        self.assertTrue(session.exists())

    def test_tick_hour_skips_empty(self):
        r = run(
            [
                "tick-hour",
                "--period",
                "2026-08-21T18",
                "--bundle",
                self.bundle,
                "--author",
                "grok-bot/northstar-console",
            ]
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertEqual(data["skipped"], "empty")
        self.assertFalse(data["wrote"])
        hour = Path(self.bundle) / "okf/temporal/2026/08/21/18/2026-08-21T18.md"
        self.assertFalse(hour.exists())

    def test_tick_hour_skips_open_session(self):
        author = ["--author", "grok-bot/northstar-console"]
        self.assertEqual(
            run(
                [
                    "write-session",
                    "--id",
                    "software_engineer__atlas__005",
                    "--period",
                    "2026-08-21T19",
                    "--agent-name",
                    "atlas",
                    "--agent-role",
                    "software_engineer",
                    "--status",
                    "open",
                    "--bundle",
                    self.bundle,
                    *author,
                ]
            ).returncode,
            0,
        )
        r = run(
            [
                "tick-hour",
                "--period",
                "2026-08-21T19",
                "--bundle",
                self.bundle,
                *author,
            ]
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertEqual(data["skipped"], "open_session")
        self.assertIn("software_engineer__atlas__005", data["open"])
        hour = Path(self.bundle) / "okf/temporal/2026/08/21/19/2026-08-21T19.md"
        self.assertFalse(hour.exists())

    def test_tick_hour_writes_when_sessions_closed(self):
        author = ["--author", "grok-bot/northstar-console"]
        self.assertEqual(
            run(
                [
                    "write-session",
                    "--id",
                    "software_engineer__atlas__006",
                    "--period",
                    "2026-08-21T20",
                    "--agent-name",
                    "atlas",
                    "--agent-role",
                    "software_engineer",
                    "--status",
                    "finalized",
                    "--bundle",
                    self.bundle,
                    *author,
                ]
            ).returncode,
            0,
        )
        r = run(
            [
                "tick-hour",
                "--period",
                "2026-08-21T20",
                "--bundle",
                self.bundle,
                "--ensure-parents",
                *author,
            ]
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertTrue(data["wrote"])
        hour = Path(self.bundle) / "okf/temporal/2026/08/21/20/2026-08-21T20.md"
        self.assertTrue(hour.exists())
        self.assertIn("software_engineer__atlas__006.md", hour.read_text(encoding="utf-8"))
        self.assertIn("(proposed)", hour.read_text(encoding="utf-8"))

    def test_hour_aligned_segments_on_crossing_session(self):
        author = ["--author", "grok-bot/northstar-console"]
        r = run(
            [
                "write-session",
                "--id",
                "software_engineer__atlas__007",
                "--period",
                "2026-08-21T21",
                "--agent-name",
                "atlas",
                "--agent-role",
                "software_engineer",
                "--started-at",
                "2026-08-21T21:10:00Z",
                "--ended-at",
                "2026-08-21T22:15:00Z",
                "--title",
                "Crossing hour boundary",
                "--bundle",
                self.bundle,
                *author,
            ]
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        session = Path(self.bundle) / "okf/temporal/2026/08/21/21/sessions/software_engineer__atlas__007.md"
        text = session.read_text(encoding="utf-8")
        self.assertIn("period: 2026-08-21T21", text)
        self.assertIn("period: 2026-08-21T22", text)
        v = run(["validate", "--bundle", self.bundle])
        self.assertEqual(v.returncode, 0, v.stdout)

    def test_close_segment_marks_hour(self):
        author = ["--author", "grok-bot/northstar-console"]
        run(
            [
                "write-session",
                "--id",
                "software_engineer__atlas__008",
                "--period",
                "2026-08-21T23",
                "--agent-name",
                "atlas",
                "--agent-role",
                "software_engineer",
                "--status",
                "open",
                "--started-at",
                "2026-08-21T23:05:00Z",
                "--bundle",
                self.bundle,
                *author,
            ]
        )
        r = run(
            [
                "close-segment",
                "--id",
                "software_engineer__atlas__008",
                "--period",
                "2026-08-21T23",
                "--bundle",
                self.bundle,
                *author,
            ]
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        text = (
            Path(self.bundle)
            / "okf/temporal/2026/08/21/23/sessions/software_engineer__atlas__008.md"
        ).read_text(encoding="utf-8")
        self.assertIn("period: 2026-08-21T23", text)
        self.assertIn("status: segmented", text)

    def test_prune_telemetry_drops_old_files(self):
        author = ["--author", "grok-bot/northstar-console"]
        run(
            [
                "write-session",
                "--id",
                "research__lumen__003",
                "--period",
                "2026-08-22T10",
                "--agent-name",
                "lumen",
                "--agent-role",
                "research",
                "--bundle",
                self.bundle,
                *author,
            ]
        )
        tel = Path(self.bundle) / "okf/temporal/2026/08/22/10/sessions/research__lumen__003.telemetry.md"
        tel.parent.mkdir(parents=True, exist_ok=True)
        tel.write_text(
            "---\ntype: temporal.telemetry\ntitle: old\ntimestamp: 2020-01-01T00:00:00Z\n---\n\n```jsonl\n{}\n```\n",
            encoding="utf-8",
        )
        r = run(["prune-telemetry", "--days", "90", "--bundle", self.bundle])
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertEqual(data["days"], 90)
        self.assertTrue(any("telemetry" in p for p in data["removed"]))
        self.assertFalse(tel.exists())

    def test_watchdog_is_global_and_rejects_role(self):
        r = run(
            [
                "watchdog",
                "--role",
                "software_engineer",
                "--bundle",
                self.bundle,
                "--author",
                "grok-bot/northstar-console",
            ]
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("phase two", r.stdout)
        author = ["--author", "grok-bot/northstar-console"]
        run(
            [
                "write-session",
                "--id",
                "software_engineer__atlas__009",
                "--period",
                "2026-08-21T13",
                "--agent-name",
                "atlas",
                "--agent-role",
                "software_engineer",
                "--status",
                "open",
                "--started-at",
                "2020-01-01T00:00:00Z",
                "--bundle",
                self.bundle,
                *author,
            ]
        )
        w = run(["watchdog", "--bundle", self.bundle, *author])
        self.assertEqual(w.returncode, 0, w.stdout)
        data = json.loads(w.stdout)
        self.assertEqual(data["scope"], "global")
        self.assertEqual(data["watchdog_seconds"], 3600)
        self.assertIn("software_engineer__atlas__009", data["closed"])
        text = (
            Path(self.bundle)
            / "okf/temporal/2026/08/21/13/sessions/software_engineer__atlas__009.md"
        ).read_text(encoding="utf-8")
        self.assertIn("close_reason: watchdog", text)
        self.assertIn("status: finalized", text)


if __name__ == "__main__":
    unittest.main()
