#!/usr/bin/env python3
"""Snapshot-first tailer: copy, cursor, check, never-shrink, no stored emit."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAILER = ROOT / "scripts" / "ots_tail_jsonl.py"
COMMON = ROOT / "scripts" / "ots_common.py"
FIXTURE = ROOT / "tests" / "fixtures" / "host-session.jsonl"

sys.path.insert(0, str(ROOT / "scripts"))
import ots_filter as flt  # noqa: E402
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


def run_common(args, env=None, bundle=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    cmd = [sys.executable, str(COMMON), *args]
    if bundle is not None and "--bundle" not in args:
        cmd += ["--bundle", bundle]
    return subprocess.run(cmd, capture_output=True, text=True, env=e)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestParseAndFilter(unittest.TestCase):
    def test_parse_fixture_skips_tool_result_keeps_last_assistant(self):
        events = []
        offset = 0
        for line in FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True):
            ev = flt.parse_host_record(line, offset)
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
        self.assertTrue(any("dangling aggregate" in e.text for e in assistants_with_text))

    def test_filter_view_is_not_a_write_schema(self):
        rows = flt.filter_source_jsonl(
            FIXTURE,
            host="claude-code",
            session_id="software_engineer__atlas__001",
            actor="grok-bot/northstar-console",
        )
        self.assertEqual([row["role"] for row in rows], ["user", "assistant", "user", "assistant"])
        self.assertEqual([row["turn"] for row in rows], [1, 1, 2, 2])
        self.assertEqual(rows[0]["text"], "scaffold the ingest write helper")
        self.assertIn("dangling aggregate", rows[1]["text"])
        self.assertEqual(rows[2]["text"], "green the aggregates validator")
        self.assertIn("Lumenfield", rows[3]["text"])
        for row in rows:
            self.assertEqual(flt.validate_view(row), [], row)
        # Filter view is in-memory only — fixture itself is still vendor JSONL.
        self.assertNotIn('"v":1', FIXTURE.read_text(encoding="utf-8"))
        self.assertNotIn("session_id", FIXTURE.read_text(encoding="utf-8"))


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
            "once",
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

    def _source(self) -> Path:
        matches = list(self.bundle.rglob("software_engineer__atlas__001.source.jsonl"))
        self.assertTrue(matches, "source snapshot was not written")
        return matches[0]

    def test_once_writes_source_snapshot_and_session(self):
        r = run_tail(self._base_args(), env=self.env, bundle=str(self.bundle))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads(r.stdout)
        self.assertTrue(data["ok"])
        source = self._source()
        self.assertEqual(source.read_bytes(), FIXTURE.read_bytes())
        session = list(self.bundle.rglob("software_engineer__atlas__001.md"))
        self.assertTrue(session)
        text = session[0].read_text(encoding="utf-8")
        self.assertIn("ulid:", text)
        self.assertIn("software_engineer__atlas__001", text)
        self.assertTrue(self.cursor.exists())
        cursor = json.loads(self.cursor.read_text(encoding="utf-8"))
        self.assertEqual(cursor["session_id"], "software_engineer__atlas__001")
        self.assertEqual(cursor["path"], str(FIXTURE.resolve()))
        self.assertEqual(cursor["size"], FIXTURE.stat().st_size)
        self.assertEqual(cursor["pos"], FIXTURE.stat().st_size)
        self.assertIn("updated_at", cursor)
        emit = list(self.bundle.rglob("*.telemetry.md"))
        self.assertFalse(emit, "phase 1 must not write a normalized emit fence")

    def test_restart_does_not_grow_or_duplicate_source(self):
        first = run_tail(self._base_args(), env=self.env, bundle=str(self.bundle))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self._source()
        before = source.read_bytes()
        digest = sha256(source)
        size_before = source.stat().st_size
        ulid_line = [
            ln
            for ln in list(self.bundle.rglob("software_engineer__atlas__001.md"))[0].read_text().splitlines()
            if ln.startswith("ulid:")
        ][0]
        second = run_tail(self._base_args(), env=self.env, bundle=str(self.bundle))
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        after = source.read_bytes()
        self.assertEqual(after, before)
        self.assertEqual(sha256(source), digest)
        self.assertEqual(source.stat().st_size, size_before)
        ulid_after = [
            ln
            for ln in list(self.bundle.rglob("software_engineer__atlas__001.md"))[0].read_text().splitlines()
            if ln.startswith("ulid:")
        ][0]
        self.assertEqual(ulid_line, ulid_after)

    def test_never_shrinks_source(self):
        host = Path(self.tmp.name) / "host.jsonl"
        host.write_bytes(FIXTURE.read_bytes())
        args = self._base_args()
        args[args.index("--jsonl") + 1] = str(host)
        first = run_tail(args, env=self.env, bundle=str(self.bundle))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = self._source()
        full = source.read_bytes()
        host.write_text('{"type":"user","timestamp":"2026-08-21T14:03:11.000Z","message":{"role":"user","content":"tiny"}}\n')
        second = run_tail(args, env=self.env, bundle=str(self.bundle))
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(source.read_bytes(), full)
        self.assertGreater(source.stat().st_size, host.stat().st_size)

    def test_hour_rollover_keeps_same_slug(self):
        host = Path(self.tmp.name) / "span.jsonl"
        host.write_text(
            FIXTURE.read_text(encoding="utf-8")
            + '{"type":"user","timestamp":"2026-08-21T15:01:00.000Z","sessionId":"host-sess-1","message":{"role":"user","content":"continue after the hour"}}\n'
            + '{"type":"assistant","timestamp":"2026-08-21T15:01:20.000Z","sessionId":"host-sess-1","message":{"role":"assistant","content":[{"type":"text","text":"same Atlas slug on the next hour"}]}}\n'
        )
        args = self._base_args()
        args[args.index("--jsonl") + 1] = str(host)
        r = run_tail(args, env=self.env, bundle=str(self.bundle))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        hubs = list(self.bundle.rglob("software_engineer__atlas__001.md"))
        self.assertEqual(len(hubs), 1)
        self.assertFalse(list(self.bundle.rglob("software_engineer__atlas__002.md")))
        meta_text = hubs[0].read_text(encoding="utf-8")
        self.assertIn("2026-08-21T14", meta_text)
        self.assertIn("2026-08-21T15", meta_text)

    def test_missing_source_fails(self):
        args = self._base_args()
        args[args.index("--jsonl") + 1] = str(Path(self.tmp.name) / "nope.jsonl")
        r = run_tail(args, env=self.env, bundle=str(self.bundle))
        self.assertEqual(r.returncode, 1)
        self.assertIn("source", r.stdout.lower())

    def test_missing_identity_fails(self):
        env = os.environ.copy()
        env.pop("SECOND_BRAIN_IDENTITY", None)
        drop = self._base_args()
        i = drop.index("--author")
        args = drop[:i] + drop[i + 2 :]
        r = run_tail(args, env=env, bundle=str(self.bundle))
        self.assertEqual(r.returncode, 1)
        self.assertIn("identity", r.stdout.lower())

    def test_missing_bundle_fails(self):
        r = run_tail(self._base_args(), env=self.env, bundle=str(Path(self.tmp.name) / "missing-bundle"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("bundle", r.stdout.lower())

    def test_check_exit_codes(self):
        missing = run_tail(
            ["check", "--jsonl", str(Path(self.tmp.name) / "nope.jsonl"), "--author", "local/tailer"],
            env=self.env,
            bundle=str(self.bundle),
        )
        self.assertEqual(missing.returncode, 1)
        self.assertIn("source", missing.stdout.lower())

        env = os.environ.copy()
        env.pop("SECOND_BRAIN_IDENTITY", None)
        ident = run_tail(
            ["check", "--jsonl", str(FIXTURE)],
            env=env,
            bundle=str(self.bundle),
        )
        self.assertEqual(ident.returncode, 1)
        self.assertIn("identity", ident.stdout.lower())

        ok = run_tail(
            ["check", "--jsonl", str(FIXTURE), "--author", "local/tailer", "--cursor", str(self.cursor)],
            env=self.env,
            bundle=str(self.bundle),
        )
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)

        self.cursor.write_text(
            json.dumps(
                {
                    "path": str(FIXTURE.resolve()),
                    "pos": 10**12,
                    "size": 10**12,
                    "mtime": 0,
                    "session_id": "software_engineer__atlas__001",
                    "updated_at": "2026-08-21T14:00:00Z",
                }
            )
        )
        stale = run_tail(
            ["check", "--jsonl", str(FIXTURE), "--author", "local/tailer", "--cursor", str(self.cursor)],
            env=self.env,
            bundle=str(self.bundle),
        )
        self.assertEqual(stale.returncode, 1)
        self.assertIn("cursor stale", stale.stdout.lower())

    def test_setup_writes_tailer_json(self):
        r = run_tail(
            [
                "setup",
                "--jsonl",
                str(FIXTURE),
                "--host",
                "claude-code",
                "--role",
                "software_engineer",
                "--agent",
                "atlas",
                "--idle",
                "300",
            ],
            env=self.env,
            bundle=str(self.bundle),
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cfg_path = self.bundle / "okf" / "temporal" / "tailer.json"
        self.assertTrue(cfg_path.exists())
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(cfg["host"], "claude-code")
        self.assertEqual(cfg["jsonl"], str(FIXTURE.resolve()))
        self.assertEqual(cfg["idle_seconds"], 300.0)
        self.assertFalse(any(str(v).startswith(("http://", "https://", "git@")) for v in cfg.values()))

    def test_setup_rejects_remote(self):
        r = run_tail(
            ["setup", "--jsonl", "https://example.invalid/private.git", "--role", "software_engineer", "--agent", "atlas"],
            env=self.env,
            bundle=str(self.bundle),
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("remote", r.stdout.lower())

    def test_status_after_once(self):
        run_tail(self._base_args(), env=self.env, bundle=str(self.bundle))
        r = run_tail(
            ["status", "--cursor", str(self.cursor), "--role", "software_engineer", "--agent", "atlas"],
            env=self.env,
            bundle=str(self.bundle),
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads(r.stdout)
        self.assertTrue(data["ok"])
        self.assertFalse(data["running"])
        self.assertEqual(data["session"], "software_engineer__atlas__001")
        self.assertTrue(data["source"])

    def test_compat_once_flag(self):
        args = ["--once"] + self._base_args()[1:]
        r = run_tail(args, env=self.env, bundle=str(self.bundle))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self._source().exists())


class TestSummarizeLeavesSourceUntouched(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = Path(self.tmp.name) / "bundle"
        self.bundle.mkdir()
        self.cursor = Path(self.tmp.name) / "cursor.json"
        self.env = {"SECOND_BRAIN_IDENTITY": "grok-bot/northstar-console"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_hash_stable_across_summarize(self):
        r = run_tail(
            [
                "once",
                "--jsonl",
                str(FIXTURE),
                "--host",
                "claude-code",
                "--role",
                "software_engineer",
                "--agent",
                "atlas",
                "--cursor",
                str(self.cursor),
                "--author",
                "local/tailer",
            ],
            env=self.env,
            bundle=str(self.bundle),
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        source = list(self.bundle.rglob("software_engineer__atlas__001.source.jsonl"))[0]
        digest = sha256(source)
        mock = (
            "python3 -c \"import sys,json; json.load(sys.stdin); "
            "print(json.dumps({'summary':'Northstar write helper','saliency':'- dangling aggregate'}))\""
        )
        s = run_common(
            [
                "summarize-hour",
                "--period",
                "2026-08-21T14",
                "--host",
                "claude-code",
                "--author",
                "local/tailer",
                "--model-cmd",
                mock,
            ],
            env=self.env,
            bundle=str(self.bundle),
        )
        self.assertEqual(s.returncode, 0, s.stdout + s.stderr)
        out = json.loads(s.stdout)
        self.assertTrue(out["ok"])
        self.assertIn("software_engineer__atlas__001", out["updated"])
        self.assertEqual(sha256(source), digest)
        self.assertEqual(source.read_bytes(), FIXTURE.read_bytes())
        summary = list(self.bundle.rglob("software_engineer__atlas__001.summary.md"))
        saliency = list(self.bundle.rglob("software_engineer__atlas__001.saliency.md"))
        self.assertTrue(summary)
        self.assertTrue(saliency)
        self.assertIn("Northstar write helper", summary[0].read_text(encoding="utf-8"))
        self.assertIn("dangling aggregate", saliency[0].read_text(encoding="utf-8"))

    def test_summarize_stub_needs_no_api_key(self):
        r = run_tail(
            [
                "once",
                "--jsonl",
                str(FIXTURE),
                "--role",
                "software_engineer",
                "--agent",
                "atlas",
                "--cursor",
                str(self.cursor),
                "--author",
                "local/tailer",
            ],
            env=self.env,
            bundle=str(self.bundle),
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        env = dict(self.env)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
        s = run_common(
            ["summarize-hour", "--period", "2026-08-21T14", "--author", "local/tailer"],
            env=env,
            bundle=str(self.bundle),
        )
        self.assertEqual(s.returncode, 0, s.stdout + s.stderr)
        self.assertTrue(json.loads(s.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
