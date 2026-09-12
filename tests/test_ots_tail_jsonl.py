#!/usr/bin/env python3
"""Official JSONL tailer: parse, emit contract, append, cursor restart."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAILER = ROOT / "scripts" / "ots_tail_jsonl.py"
FIXTURE = ROOT / "tests" / "fixtures" / "host-session.jsonl"

sys.path.insert(0, str(ROOT / "scripts"))
import ots_tail_jsonl as tail  # noqa: E402


def run_tail(args, env=None, bundle=None):
    e = os.environ.copy()
    e.pop("SECOND_BRAIN_ROOT", None)
    e.pop("SECOND_BRAIN_IDENTITY", None)
    if env:
        e.update(env)
    cmd = [sys.executable, str(TAILER), *args]
    if bundle is not None and "--bundle" not in args:
        cmd += ["--bundle", bundle]
    return subprocess.run(cmd, capture_output=True, text=True, env=e)


class TestParseAndContract(unittest.TestCase):
    def test_parse_fixture_skips_tool_result_keeps_last_assistant(self):
        events = []
        offset = 0
        for line in FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True):
            ev = tail.parse_host_record(line, offset)
            offset += len(line.encode("utf-8"))
            if ev is not None:
                events.append(ev)
        users = [e for e in events if e.role == "user" and not e.tool_result]
        tool_results = [e for e in events if e.tool_result]
        assistants_with_text = [e for e in events if e.role == "assistant" and e.text]
        self.assertEqual(len(users), 2)
        self.assertEqual(users[0].text, "scaffold the ingest write helper")
        self.assertEqual(users[1].text, "green the aggregates validator")
        self.assertGreaterEqual(len(tool_results), 1)
        self.assertEqual(assistants_with_text[-1].text, "aggregates validator is green for the Lumenfield day node")
        # Intermediate assistant text is kept; last text in turn 1 is the dangling-aggregate line.
        self.assertTrue(any("dangling aggregate" in e.text for e in assistants_with_text))

    def test_emit_required_keys(self):
        obj = tail.build_emit(
            ts="2026-08-21T14:03:11Z",
            host="claude-code",
            session_id="software_engineer__atlas__001",
            actor="grok-bot/northstar-console",
            turn=1,
            role="user",
            text="scaffold the ingest write helper",
            source_path="/tmp/host-session.jsonl",
            source_offset=0,
        )
        self.assertEqual(tail.validate_emit(obj), [])
        for key in tail.REQUIRED_EMIT_KEYS:
            self.assertIn(key, obj)
        missing = dict(obj)
        del missing["session_id"]
        self.assertIn("missing session_id", tail.validate_emit(missing))
        bad_host = dict(obj)
        bad_host["host"] = "mystery"
        self.assertIn("invalid host", tail.validate_emit(bad_host))


class TestTailerOnceAndCursor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = Path(self.tmp.name) / "bundle"
        self.bundle.mkdir()
        self.cursor = Path(self.tmp.name) / "cursor.json"
        self.env = {"SECOND_BRAIN_IDENTITY": "grok-bot/northstar-console"}

    def tearDown(self):
        self.tmp.cleanup()

    def _base_args(self):
        return [
            "--once",
            "--jsonl",
            str(FIXTURE),
            "--host",
            "claude-code",
            "--role",
            "software_engineer",
            "--agent",
            "atlas",
            "--n",
            "1",
            "--cursor",
            str(self.cursor),
            "--author",
            "local/tailer",
        ]

    def _telemetry(self) -> Path:
        matches = list(self.bundle.rglob("software_engineer__atlas__001.telemetry.md"))
        self.assertTrue(matches, "telemetry file was not written")
        return matches[0]

    def _emit_rows(self) -> list[dict]:
        text = self._telemetry().read_text(encoding="utf-8")
        rows = []
        for line in tail.jsonl_fence_lines(text):
            rows.append(json.loads(line))
        return rows

    def test_once_appends_two_turns(self):
        r = run_tail(self._base_args(), env=self.env, bundle=str(self.bundle))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads(r.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["emitted"], 4)
        rows = self._emit_rows()
        self.assertEqual(len(rows), 4)
        self.assertEqual([row["role"] for row in rows], ["user", "assistant", "user", "assistant"])
        self.assertEqual([row["turn"] for row in rows], [1, 1, 2, 2])
        self.assertEqual(rows[0]["text"], "scaffold the ingest write helper")
        self.assertIn("dangling aggregate", rows[1]["text"])
        self.assertEqual(rows[2]["text"], "green the aggregates validator")
        self.assertIn("Lumenfield", rows[3]["text"])
        for row in rows:
            self.assertEqual(tail.validate_emit(row), [], row)
            self.assertEqual(row["session_id"], "software_engineer__atlas__001")
            self.assertEqual(row["actor"], "grok-bot/northstar-console")
            self.assertEqual(row["host"], "claude-code")
            self.assertEqual(row["v"], 1)
        session = list(self.bundle.rglob("software_engineer__atlas__001.md"))
        self.assertTrue(session)
        self.assertIn("ulid:", session[0].read_text(encoding="utf-8"))
        self.assertTrue(self.cursor.exists())

    def test_restart_cursor_does_not_duplicate(self):
        first = run_tail(self._base_args(), env=self.env, bundle=str(self.bundle))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        before = self._telemetry().read_text(encoding="utf-8")
        rows_before = self._emit_rows()
        ulid_line = [ln for ln in list(self.bundle.rglob("software_engineer__atlas__001.md"))[0].read_text().splitlines() if ln.startswith("ulid:")][0]
        second = run_tail(self._base_args(), env=self.env, bundle=str(self.bundle))
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        after = self._telemetry().read_text(encoding="utf-8")
        rows_after = self._emit_rows()
        self.assertEqual(len(rows_after), len(rows_before))
        self.assertEqual(rows_after, rows_before)
        # Earlier records are byte-identical inside the fence.
        self.assertEqual(tail.jsonl_fence_lines(before), tail.jsonl_fence_lines(after))
        ulid_after = [ln for ln in list(self.bundle.rglob("software_engineer__atlas__001.md"))[0].read_text().splitlines() if ln.startswith("ulid:")][0]
        self.assertEqual(ulid_line, ulid_after)

    def test_missing_jsonl_fails(self):
        args = self._base_args()
        args[args.index("--jsonl") + 1] = str(Path(self.tmp.name) / "nope.jsonl")
        r = run_tail(args, env=self.env, bundle=str(self.bundle))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("jsonl", r.stdout.lower())

    def test_missing_identity_fails(self):
        env = os.environ.copy()
        env.pop("SECOND_BRAIN_IDENTITY", None)
        args = [a for a in self._base_args() if a != "local/tailer"]
        # drop --author pair
        drop = self._base_args()
        i = drop.index("--author")
        args = drop[:i] + drop[i + 2 :]
        r = run_tail(args, env=env, bundle=str(self.bundle))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("identity", r.stdout.lower())

    def test_missing_bundle_fails(self):
        r = run_tail(self._base_args(), env=self.env, bundle=str(Path(self.tmp.name) / "missing-bundle"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("bundle", r.stdout.lower())


if __name__ == "__main__":
    unittest.main()
