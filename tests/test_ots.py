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


if __name__ == "__main__":
    unittest.main()
