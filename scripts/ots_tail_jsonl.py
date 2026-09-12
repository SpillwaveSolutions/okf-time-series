#!/usr/bin/env python3
"""Thin official JSONL tailer for okf-time-series.

Read-only on the host JSONL. No LLM. Inference stays on hour-close Haiku
summary and overnight pointer batch (out of process).

Writes only through ots_common paths: write-session once (--ensure-spine),
close-segment on hour rollover (same session id), and a single
`.telemetry.md` that is created once then append-only inside the jsonl fence.

Cursor file (byte pos + last session_id/turn/role or source_offset) is
required for restart-without-duplicate. Default: `<jsonl>.ots-cursor.json`
next to the host file — not a temporal noun.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ots_common as ots  # noqa: E402

EMIT_VERSION = 1
REQUIRED_EMIT_KEYS = ("v", "ts", "host", "session_id", "actor", "turn", "role", "text")
HOSTS = ("claude-code", "grok-build", "codex", "deep-agents")
ROLES = ("user", "assistant")
DEFAULT_IDLE = 2.0
DEFAULT_POLL = 0.25


def fail(error: str, **extra) -> int:
    payload = {"error": error, **extra}
    print(json.dumps(payload))
    return 1


def require_identity(explicit: str | None) -> tuple[str, str]:
    """Return (process_author, actor). Identity must be claimed."""
    identity = (os.environ.get("SECOND_BRAIN_IDENTITY") or "").strip()
    author = (explicit or "").strip()
    if not identity and not author:
        raise SystemExit(fail("missing identity", hint="pass --author or set SECOND_BRAIN_IDENTITY"))
    process_author = author or "local/tailer"
    actor = identity or process_author
    return process_author, actor


def require_bundle(raw: str | None) -> Path:
    value = (raw or os.environ.get("SECOND_BRAIN_ROOT") or "").strip()
    if not value:
        raise SystemExit(fail("missing bundle", hint="pass --bundle or set SECOND_BRAIN_ROOT"))
    p = Path(value)
    if not p.exists():
        raise SystemExit(fail("missing bundle", path=str(p)))
    return p.resolve()


def require_jsonl(raw: str | None) -> Path:
    if not raw:
        raise SystemExit(fail("missing jsonl", hint="pass --jsonl"))
    p = Path(raw)
    if not p.exists() or not p.is_file():
        raise SystemExit(fail("missing jsonl", path=str(p)))
    return p.resolve()


def normalize_ts(raw) -> str:
    if raw is None or raw == "":
        return ots.now_iso()
    text = str(raw).strip()
    try:
        dt = ots.parse_iso(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return ots.now_iso()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _message(record: dict) -> dict:
    msg = record.get("message")
    return msg if isinstance(msg, dict) else {}


def is_tool_result_user(record: dict) -> bool:
    """Skip host user lines that are tool_result payloads, not prompts."""
    role = record.get("type") or record.get("role") or _message(record).get("role")
    if role not in {"user", "tool_result"}:
        return False
    if record.get("type") == "tool_result":
        return True
    content = _message(record).get("content", record.get("content"))
    if isinstance(content, list):
        has_tool = False
        has_text = False
        for block in content:
            if isinstance(block, str) and block.strip():
                has_text = True
            elif isinstance(block, dict):
                if block.get("type") == "tool_result":
                    has_tool = True
                elif block.get("type") == "text" and str(block.get("text") or "").strip():
                    has_text = True
        return has_tool and not has_text
    return False


def extract_text(record: dict) -> str:
    if isinstance(record.get("text"), str) and record.get("text").strip():
        if not is_tool_result_user(record):
            return record["text"].strip()
    content = _message(record).get("content", record.get("content"))
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str) and block.strip():
                parts.append(block.strip())
            elif isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def host_role(record: dict) -> str | None:
    role = record.get("type") or record.get("role") or _message(record).get("role")
    if role in ROLES:
        return role
    return None


def host_model(record: dict) -> str:
    msg = _message(record)
    for key in ("model",):
        val = record.get(key) or msg.get(key)
        if val:
            return str(val)
    return ""


@dataclass
class HostEvent:
    role: str
    text: str
    ts: str
    offset: int
    model: str = ""
    tool_result: bool = False


def parse_host_record(line: str, offset: int) -> HostEvent | None:
    """Parse one host JSONL line. Claude Code shape, plus a plain role/text object."""
    text = line.strip()
    if not text:
        return None
    try:
        record = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    tool_result = is_tool_result_user(record)
    role = host_role(record)
    if tool_result:
        return HostEvent(role="user", text="", ts=normalize_ts(record.get("timestamp") or record.get("ts")), offset=offset, tool_result=True)
    if role not in ROLES:
        return None
    body = extract_text(record)
    if role == "assistant" and not body:
        # tool_use-only assistant: keep last text elsewhere, do not emit
        return HostEvent(role="assistant", text="", ts=normalize_ts(record.get("timestamp") or record.get("ts")), offset=offset, model=host_model(record))
    if role == "user" and not body:
        return None
    return HostEvent(
        role=role,
        text=body,
        ts=normalize_ts(record.get("timestamp") or record.get("ts")),
        offset=offset,
        model=host_model(record),
    )


def validate_emit(obj: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return ["not an object"]
    for key in REQUIRED_EMIT_KEYS:
        if key not in obj or obj[key] in ("", None):
            errors.append(f"missing {key}")
    if "v" in obj and obj["v"] != EMIT_VERSION:
        errors.append(f"v must be {EMIT_VERSION}")
    if obj.get("host") not in HOSTS:
        errors.append("invalid host")
    if obj.get("role") not in ROLES:
        errors.append("invalid role")
    turn = obj.get("turn")
    if turn is not None and not (isinstance(turn, int) and not isinstance(turn, bool) and turn >= 1):
        errors.append("turn must be a monotonic int >= 1")
    return errors


def build_emit(
    *,
    ts: str,
    host: str,
    session_id: str,
    actor: str,
    turn: int,
    role: str,
    text: str,
    model: str = "",
    source_path: str = "",
    source_offset: int | None = None,
) -> dict:
    obj: dict = {
        "v": EMIT_VERSION,
        "ts": ts,
        "host": host,
        "session_id": session_id,
        "actor": actor,
        "turn": turn,
        "role": role,
        "text": text,
    }
    if model:
        obj["model"] = model
    if source_path:
        obj["source_path"] = source_path
    if source_offset is not None:
        obj["source_offset"] = source_offset
    return obj


@dataclass
class Cursor:
    pos: int = 0
    source_path: str = ""
    source_offset: int = -1
    last_session_id: str = ""
    last_turn: int = 0
    last_role: str = ""

    def to_json(self) -> dict:
        out = {
            "v": EMIT_VERSION,
            "pos": self.pos,
            "source_path": self.source_path,
            "source_offset": self.source_offset,
        }
        if self.last_session_id and self.last_role:
            out["last"] = {
                "session_id": self.last_session_id,
                "turn": self.last_turn,
                "role": self.last_role,
            }
        return out

    def already_emitted(self, session_id: str, turn: int, role: str, source_offset: int | None) -> bool:
        if source_offset is not None and self.source_offset >= 0 and source_offset <= self.source_offset:
            if self.last_session_id == session_id and self.last_turn == turn and self.last_role == role:
                return True
            if source_offset < self.source_offset:
                return True
        if (
            self.last_session_id
            and self.last_session_id == session_id
            and self.last_turn == turn
            and self.last_role == role
        ):
            return True
        return False


def load_cursor(path: Path) -> Cursor:
    if not path.exists():
        return Cursor()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Cursor()
    last = data.get("last") or {}
    return Cursor(
        pos=int(data.get("pos") or 0),
        source_path=str(data.get("source_path") or ""),
        source_offset=int(data.get("source_offset") if data.get("source_offset") is not None else -1),
        last_session_id=str(last.get("session_id") or ""),
        last_turn=int(last.get("turn") or 0),
        last_role=str(last.get("role") or ""),
    )


def save_cursor(path: Path, cursor: Cursor) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cursor.to_json(), indent=2) + "\n", encoding="utf-8")


def jsonl_fence_lines(text: str) -> list[str]:
    marker = "```jsonl"
    idx = text.find(marker)
    if idx < 0:
        return []
    after = idx + len(marker)
    close = text.find("```", after)
    inner = text[after:] if close < 0 else text[after:close]
    return [ln for ln in inner.splitlines() if ln.strip()]


def existing_emit_keys(path: Path) -> set[tuple]:
    keys: set[tuple] = set()
    if not path.exists():
        return keys
    for line in jsonl_fence_lines(path.read_text(encoding="utf-8")):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("session_id") and obj.get("role"):
            keys.add((obj.get("session_id"), obj.get("turn"), obj.get("role")))
    return keys


def append_emit_line(path: Path, obj: dict) -> None:
    """Append one JSONL object inside the fence. Does not rewrite earlier records."""
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    marker = "```jsonl"
    idx = text.find(marker)
    if idx < 0:
        if not text.endswith("\n"):
            text += "\n"
        path.write_text(text + f"```jsonl\n{payload}\n```\n", encoding="utf-8")
        return
    after = idx + len(marker)
    close = text.find("```", after)
    if close < 0:
        if not text.endswith("\n"):
            text += "\n"
        path.write_text(text + payload + "\n```\n", encoding="utf-8")
        return
    inner = text[after:close]
    if inner.startswith("\r\n"):
        inner = inner[2:]
    elif inner.startswith("\n"):
        inner = inner[1:]
    if inner and not inner.endswith("\n"):
        inner += "\n"
    inner += payload + "\n"
    path.write_text(text[:idx] + "```jsonl\n" + inner + text[close:], encoding="utf-8")


def find_session(bundle: Path, slug: str) -> Path | None:
    root = bundle / "okf" / "temporal"
    if not root.exists():
        return None
    matches = [
        p
        for p in root.rglob(f"{slug}.md")
        if p.parent.name == "sessions" and not ots._is_session_artifact(p.name)
    ]
    return matches[0] if matches else None


def _ots_cli(argv: list[str], bundle: Path, author: str) -> dict:
    env = os.environ.copy()
    env.setdefault("SECOND_BRAIN_IDENTITY", author)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "ots_common.py"), *argv, "--bundle", str(bundle), "--author", author],
        capture_output=True,
        text=True,
        env=env,
    )
    raw = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    try:
        data = json.loads(raw.splitlines()[-1]) if raw else {}
    except json.JSONDecodeError:
        data = {"error": raw or "ots_common failed", "returncode": proc.returncode}
    if proc.returncode != 0:
        data.setdefault("error", "ots_common failed")
        data["returncode"] = proc.returncode
    return data


def session_slug(role: str, agent: str, n: int) -> str:
    role_s = role.strip().lower().replace("-", "_")
    agent_s = agent.strip().lower().replace("-", "_")
    slug = f"{role_s}__{agent_s}__{n:03d}"
    if not ots.SESSION_SLUG.match(slug):
        raise SystemExit(fail("invalid session slug", id=slug))
    return slug


def open_segment_hour(session_path: Path) -> str:
    meta, _ = ots.parse_frontmatter(session_path.read_text(encoding="utf-8"))
    for seg in reversed(meta.get("segments") or []):
        if isinstance(seg, dict) and ots.seg_status(seg) == "open":
            return ots.seg_hour(seg)
    segs = meta.get("segments") or []
    if segs and isinstance(segs[-1], dict):
        return ots.seg_hour(segs[-1])
    return ""


def ensure_session(
    bundle: Path,
    slug: str,
    period: str,
    agent: str,
    role: str,
    author: str,
    started_at: str,
    telemetry_name: str,
) -> Path:
    existing = find_session(bundle, slug)
    if existing:
        return existing
    data = _ots_cli(
        [
            "write-session",
            "--id",
            slug,
            "--period",
            period,
            "--agent-name",
            agent,
            "--agent-role",
            role,
            "--status",
            "open",
            "--started-at",
            started_at,
            "--telemetry",
            telemetry_name,
            "--ensure-spine",
            "--title",
            slug,
        ],
        bundle,
        author,
    )
    if not data.get("ok"):
        raise SystemExit(fail("write-session failed", detail=data))
    found = find_session(bundle, slug)
    if not found:
        raise SystemExit(fail("write-session did not create session", id=slug))
    return found


def ensure_telemetry(bundle: Path, session_path: Path, slug: str, author: str) -> Path:
    dest = session_path.parent / f"{slug}.telemetry.md"
    if dest.exists():
        return dest
    rel_session = session_path.relative_to(bundle).as_posix()
    data = _ots_cli(
        [
            "write-artifact",
            "--session",
            rel_session,
            "--kind",
            "telemetry",
            "--body",
            "```jsonl\n```\n",
        ],
        bundle,
        author,
    )
    if not data.get("ok") and not dest.exists():
        ots.write_md(
            dest,
            {
                "type": "temporal.telemetry",
                "title": f"{slug} telemetry",
                "session": session_path.name,
                "timestamp": ots.now_iso(),
                "author": author,
            },
            "```jsonl\n```\n",
        )
    return dest


def rollover_to_hour(bundle: Path, slug: str, author: str, target_hour: str, telemetry_name: str) -> None:
    """Close/open hour-aligned segments on the same slug. Never mint __002.

    Uses ots_common close-segment. That helper closes the current hour, writes
    proposed summary/saliency stubs (Haiku fill-in is a separate process), and
    opens the next hour. Loop until the open segment hour catches the emit.
    """
    session = find_session(bundle, slug)
    if not session or not target_hour:
        return
    guard = 0
    while guard < 48:
        guard += 1
        current = open_segment_hour(session)
        if not current or current >= target_hour:
            return
        data = _ots_cli(
            [
                "close-segment",
                "--id",
                slug,
                "--period",
                current,
                "--telemetry",
                telemetry_name,
            ],
            bundle,
            author,
        )
        if not data.get("ok"):
            # Minimal safe behavior: keep appending to the same session/telemetry.
            return
        session = find_session(bundle, slug) or session


def iter_host_lines(path: Path, start_pos: int):
    """Yield (offset, line, nbytes) for complete lines starting at start_pos."""
    with path.open("rb") as fh:
        fh.seek(start_pos)
        while True:
            offset = fh.tell()
            raw = fh.readline()
            if not raw:
                return
            if not raw.endswith(b"\n"):
                # Incomplete line in a growing file — wait for the rest.
                return
            yield offset, raw.decode("utf-8", errors="replace"), len(raw)


@dataclass
class PendingTurn:
    user: dict | None = None
    assistant: dict | None = None
    start_pos: int = 0
    end_pos: int = 0


@dataclass
class Tailer:
    jsonl: Path
    bundle: Path
    cursor_path: Path
    host: str
    slug: str
    agent: str
    role: str
    author: str
    actor: str
    idle: float
    once: bool
    cursor: Cursor = field(default_factory=Cursor)
    turn: int = 0
    pending: PendingTurn = field(default_factory=PendingTurn)
    session_path: Path | None = None
    telemetry_path: Path | None = None
    seen: set[tuple] = field(default_factory=set)
    last_activity: float = 0.0
    committed_pos: int = 0
    read_pos: int = 0

    def setup(self) -> None:
        self.cursor = load_cursor(self.cursor_path)
        self.committed_pos = self.cursor.pos
        self.read_pos = self.cursor.pos
        if self.cursor.last_turn:
            self.turn = self.cursor.last_turn
        self.session_path = find_session(self.bundle, self.slug)
        if self.session_path:
            self.telemetry_path = self.session_path.parent / f"{self.slug}.telemetry.md"
            if self.telemetry_path.exists():
                self.seen = existing_emit_keys(self.telemetry_path)

    def _ensure_files(self, ts: str) -> None:
        period = ots.hour_period_from_iso(ts)
        tel_name = f"{self.slug}.telemetry.md"
        self.session_path = ensure_session(
            self.bundle, self.slug, period, self.agent, self.role, self.author, ts, tel_name
        )
        self.telemetry_path = ensure_telemetry(self.bundle, self.session_path, self.slug, self.author)
        self.seen |= existing_emit_keys(self.telemetry_path)

    def _should_skip_emit(self, obj: dict) -> bool:
        key = (obj.get("session_id"), obj.get("turn"), obj.get("role"))
        if key in self.seen:
            return True
        offset = obj.get("source_offset")
        if self.cursor.already_emitted(obj["session_id"], obj["turn"], obj["role"], offset if isinstance(offset, int) else None):
            return True
        return False

    def _write_emit(self, obj: dict) -> bool:
        errors = validate_emit(obj)
        if errors:
            return False
        if self._should_skip_emit(obj):
            return False
        assert self.telemetry_path is not None
        hour = ots.hour_period_from_iso(obj["ts"])
        rollover_to_hour(self.bundle, self.slug, self.author, hour, f"{self.slug}.telemetry.md")
        append_emit_line(self.telemetry_path, obj)
        self.seen.add((obj["session_id"], obj["turn"], obj["role"]))
        self.cursor.last_session_id = obj["session_id"]
        self.cursor.last_turn = obj["turn"]
        self.cursor.last_role = obj["role"]
        if isinstance(obj.get("source_offset"), int):
            self.cursor.source_offset = obj["source_offset"]
        return True

    def flush(self, commit_pos: int | None = None) -> int:
        """Idle/EOF flush: prompt then final assistant response."""
        wrote = 0
        if self.pending.user:
            self._ensure_files(self.pending.user["ts"])
            if self._write_emit(self.pending.user):
                wrote += 1
        if self.pending.assistant:
            self._ensure_files(self.pending.assistant["ts"])
            if self._write_emit(self.pending.assistant):
                wrote += 1
        self.pending = PendingTurn()
        self.committed_pos = self.read_pos if commit_pos is None else commit_pos
        self.cursor.pos = self.committed_pos
        self.cursor.source_path = self.jsonl.as_posix()
        save_cursor(self.cursor_path, self.cursor)
        return wrote

    def _flush_if_complete_pair(self) -> None:
        if self.pending.user and self.pending.assistant:
            self.flush()

    def ingest_event(self, event: HostEvent, next_pos: int) -> None:
        if event.tool_result:
            self.read_pos = next_pos
            if not self.pending.user:
                self.committed_pos = next_pos
                self.cursor.pos = next_pos
                self.cursor.source_path = self.jsonl.as_posix()
                save_cursor(self.cursor_path, self.cursor)
            return
        if event.role == "user" and event.text:
            if self.pending.user:
                self.flush()
            self.turn += 1
            self.pending = PendingTurn(start_pos=event.offset, end_pos=next_pos)
            self.pending.user = build_emit(
                ts=event.ts,
                host=self.host,
                session_id=self.slug,
                actor=self.actor,
                turn=self.turn,
                role="user",
                text=event.text,
                source_path=self.jsonl.as_posix(),
                source_offset=event.offset,
            )
            self.read_pos = next_pos
            self.last_activity = time.monotonic()
            return
        if event.role == "assistant":
            if event.text and self.pending.user:
                self.pending.assistant = build_emit(
                    ts=event.ts,
                    host=self.host,
                    session_id=self.slug,
                    actor=self.actor,
                    turn=self.turn,
                    role="assistant",
                    text=event.text,
                    model=event.model,
                    source_path=self.jsonl.as_posix(),
                    source_offset=event.offset,
                )
            self.read_pos = next_pos
            self.last_activity = time.monotonic()

    def drain(self) -> int:
        n = 0
        for offset, line, nbytes in iter_host_lines(self.jsonl, self.read_pos):
            next_pos = offset + nbytes
            event = parse_host_record(line, offset)
            if event is None:
                self.read_pos = next_pos
                if not self.pending.user:
                    self.committed_pos = next_pos
                    self.cursor.pos = next_pos
                    self.cursor.source_path = self.jsonl.as_posix()
                    save_cursor(self.cursor_path, self.cursor)
                continue
            self.ingest_event(event, next_pos)
            n += 1
        return n

    def run(self) -> dict:
        self.setup()
        self.last_activity = time.monotonic()
        emitted = 0
        while True:
            self.drain()
            if self.once:
                emitted += self.flush()
                break
            if self.pending.user and self.pending.assistant and (time.monotonic() - self.last_activity) >= self.idle:
                emitted += self.flush()
            time.sleep(DEFAULT_POLL)
        return {
            "ok": True,
            "session": self.slug,
            "telemetry": str(self.telemetry_path) if self.telemetry_path else "",
            "cursor": str(self.cursor_path),
            "emitted": emitted,
            "pos": self.cursor.pos,
        }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ots_tail_jsonl.py",
        description="Official host-JSONL → temporal.telemetry tailer (no LLM).",
    )
    p.add_argument("--jsonl", required=True, help="host session JSONL (read-only)")
    p.add_argument("--bundle", default="", help="OKF bundle; default SECOND_BRAIN_ROOT")
    p.add_argument("--author", default="", help="process author (default local/tailer once identity is claimed)")
    p.add_argument("--host", default="claude-code", choices=HOSTS)
    p.add_argument("--role", required=True, help="session agent role (slug)")
    p.add_argument("--agent", required=True, help="session agent name (slug)")
    p.add_argument("--n", type=int, default=1, help="session ordinal, default 1 → __001")
    p.add_argument("--idle", type=float, default=DEFAULT_IDLE, help="seconds of quiet before flushing a pair (--follow)")
    p.add_argument("--cursor", default="", help="cursor file; default <jsonl>.ots-cursor.json")
    p.add_argument("--once", action="store_true", help="drain to EOF then exit")
    p.add_argument("--follow", action="store_true", help="long-running (default unless --once)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.follow and args.once:
        return fail("use --once or --follow, not both")
    once = bool(args.once)
    try:
        bundle = require_bundle(args.bundle)
        jsonl = require_jsonl(args.jsonl)
        author, actor = require_identity(args.author)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    slug = session_slug(args.role, args.agent, args.n)
    cursor_path = Path(args.cursor) if args.cursor else Path(str(jsonl) + ".ots-cursor.json")
    tailer = Tailer(
        jsonl=jsonl,
        bundle=bundle,
        cursor_path=cursor_path,
        host=args.host,
        slug=slug,
        agent=args.agent.strip().lower().replace("-", "_"),
        role=args.role.strip().lower().replace("-", "_"),
        author=author,
        actor=actor,
        idle=args.idle,
        once=once,
    )
    result = tailer.run()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
