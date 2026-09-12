#!/usr/bin/env python3
"""Snapshot-first host JSONL tailer for okf-time-series.

Copies the vendor transcript byte-for-byte into
`sessions/<slug>.source.jsonl`. That file is the immutable capture.
No vendor-neutral emit JSONL is stored. No LLM. No host hooks.

Commands: once | follow | start | stop | status | check | setup

Cursor (path, pos or size/mtime, session_id, updated_at) makes re-tail
idempotent. Replace the snapshot only if the host size/mtime grew; never
shrink. Idle flush default 300s. Hour rollover keeps the same session slug.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
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
import ots_editions as editions  # noqa: E402
import ots_filter as flt  # noqa: E402

HOSTS = flt.HOSTS
DEFAULT_IDLE = 300.0
DEFAULT_POLL = 0.25
TAILER_CONFIG_REL = Path("okf/temporal/tailer.json")
CURSOR_REL = Path("okf/temporal/.ots-cursor.json")
PID_REL = Path("okf/temporal/.ots-tail.pid")
REMOTE_PREFIXES = ("http://", "https://", "git@", "ssh://")


def fail(error: str, **extra) -> int:
    payload = {"error": error, **extra}
    print(json.dumps(payload))
    return 1


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def looks_like_remote(value: str) -> bool:
    text = (value or "").strip()
    return text.startswith(REMOTE_PREFIXES)


def require_identity(explicit: str | None) -> tuple[str, str]:
    """Return (process_author, actor). Identity must be claimed."""
    identity = (os.environ.get("SECOND_BRAIN_IDENTITY") or "").strip()
    author = (explicit or "").strip()
    if not identity and not author:
        raise SystemExit(fail("unset identity", hint="pass --author or set SECOND_BRAIN_IDENTITY"))
    process_author = author or "local/tailer"
    actor = identity or process_author
    return process_author, actor


def require_bundle(raw: str | None, *, must_exist: bool = True) -> Path:
    value = (raw or os.environ.get("SECOND_BRAIN_ROOT") or "").strip()
    if not value:
        raise SystemExit(fail("missing bundle", hint="pass --bundle or set SECOND_BRAIN_ROOT"))
    if looks_like_remote(value):
        raise SystemExit(fail("do not hard-code a remote", hint="use SECOND_BRAIN_ROOT as a local path"))
    p = Path(value)
    if must_exist and not p.exists():
        raise SystemExit(fail("missing bundle", path=str(p)))
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def require_jsonl(raw: str | None) -> Path:
    if not raw:
        raise SystemExit(fail("missing source", hint="pass --jsonl or run setup"))
    if looks_like_remote(raw):
        raise SystemExit(fail("do not hard-code a remote", hint="use a local host JSONL path"))
    p = Path(raw)
    if not p.exists() or not p.is_file():
        raise SystemExit(fail("missing source", path=str(p)))
    return p.resolve()


def session_slug(role: str, agent: str, n: int) -> str:
    role_s = role.strip().lower().replace("-", "_")
    agent_s = agent.strip().lower().replace("-", "_")
    slug = f"{role_s}__{agent_s}__{n:03d}"
    if not ots.SESSION_SLUG.match(slug):
        raise SystemExit(fail("invalid session slug", id=slug))
    return slug


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


def source_path_for(session_path: Path, slug: str) -> Path:
    return session_path.parent / f"{slug}.source.jsonl"


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


def load_tailer_config(bundle: Path) -> dict:
    path = bundle / TAILER_CONFIG_REL
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_tailer_config(bundle: Path, data: dict) -> Path:
    dest = bundle / TAILER_CONFIG_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return dest


@dataclass
class Cursor:
    path: str = ""
    pos: int = 0
    size: int = 0
    mtime: float = 0.0
    session_id: str = ""
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "path": self.path,
            "pos": self.pos,
            "size": self.size,
            "mtime": self.mtime,
            "session_id": self.session_id,
            "updated_at": self.updated_at,
        }

    def stale_reason(self, host: Path) -> str:
        """Documented stale: pos/size ahead of host, or path mismatch."""
        if self.path and Path(self.path).resolve() != host.resolve():
            return "path does not match host jsonl"
        try:
            st = host.stat()
        except OSError:
            return "missing source"
        if self.pos > st.st_size or self.size > st.st_size:
            return "pos/size ahead of host size"
        return ""


def load_cursor(path: Path) -> Cursor:
    if not path.exists():
        return Cursor()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Cursor()
    return Cursor(
        path=str(data.get("path") or ""),
        pos=int(data.get("pos") or 0),
        size=int(data.get("size") or 0),
        mtime=float(data.get("mtime") or 0.0),
        session_id=str(data.get("session_id") or ""),
        updated_at=str(data.get("updated_at") or ""),
    )


def save_cursor(path: Path, cursor: Cursor) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cursor.to_json(), indent=2) + "\n", encoding="utf-8")


def snapshot_if_grew(host: Path, dest: Path) -> dict:
    """Copy host → dest only if size/mtime grew. Never shrink dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    hstat = host.stat()
    if not dest.exists():
        dest.write_bytes(host.read_bytes())
        try:
            os.utime(dest, (hstat.st_atime, hstat.st_mtime))
        except OSError:
            pass
        return {"copied": True, "reason": "create", "size": hstat.st_size}
    dstat = dest.stat()
    if hstat.st_size < dstat.st_size:
        return {"copied": False, "reason": "never_shrink", "size": dstat.st_size}
    grew = hstat.st_size > dstat.st_size or hstat.st_mtime > dstat.st_mtime
    if not grew:
        return {"copied": False, "reason": "unchanged", "size": dstat.st_size}
    dest.write_bytes(host.read_bytes())
    try:
        os.utime(dest, (hstat.st_atime, hstat.st_mtime))
    except OSError:
        pass
    return {"copied": True, "reason": "grew", "size": hstat.st_size}


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


def rollover_to_hour(bundle: Path, slug: str, author: str, target_hour: str) -> None:
    """Close/open hour-aligned segments on the same slug. Never mint __002."""
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
            ],
            bundle,
            author,
        )
        if not data.get("ok"):
            return
        session = find_session(bundle, slug) or session


def pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid(bundle: Path) -> int | None:
    path = bundle / PID_REL
    if not path.exists():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip() or "0")
    except ValueError:
        return None
    return pid if pid_running(pid) else None


def write_pid(bundle: Path, pid: int) -> None:
    path = bundle / PID_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid) + "\n", encoding="utf-8")


def clear_pid(bundle: Path) -> None:
    path = bundle / PID_REL
    if path.exists():
        path.unlink()


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
    session_path: Path | None = None
    source_path: Path | None = None
    last_growth: float = 0.0
    copied: int = 0

    def setup(self) -> None:
        self.cursor = load_cursor(self.cursor_path)
        self.session_path = find_session(self.bundle, self.slug)
        if self.session_path:
            self.source_path = source_path_for(self.session_path, self.slug)

    def _period_from_host(self) -> tuple[str, str, str]:
        first, last = flt.peek_host_bounds(self.jsonl)
        started = first or now_iso()
        ended = last or started
        period = ots.hour_period_from_iso(started)
        return period, started, ended

    def _ensure_hub(self) -> None:
        period, started, last = self._period_from_host()
        self.session_path = ensure_session(
            self.bundle, self.slug, period, self.agent, self.role, self.author, started
        )
        self.source_path = source_path_for(self.session_path, self.slug)
        last_hour = ots.hour_period_from_iso(last)
        rollover_to_hour(self.bundle, self.slug, self.author, last_hour)

    def flush(self) -> dict:
        self._ensure_hub()
        assert self.source_path is not None
        snap = snapshot_if_grew(self.jsonl, self.source_path)
        if snap["copied"]:
            self.copied += 1
            self.last_growth = time.monotonic()
        st = self.jsonl.stat()
        self.cursor = Cursor(
            path=self.jsonl.as_posix(),
            pos=st.st_size,
            size=st.st_size,
            mtime=st.st_mtime,
            session_id=self.slug,
            updated_at=now_iso(),
        )
        save_cursor(self.cursor_path, self.cursor)
        return snap

    def run(self) -> dict:
        self.setup()
        self.last_growth = time.monotonic()
        while True:
            if self.once:
                snap = self.flush()
                break
            # Architect lock: refresh on idle + size/mtime growth. Not every-second mirror.
            hstat = self.jsonl.stat()
            dest = self.source_path
            grew = True
            if dest is not None and dest.exists():
                dstat = dest.stat()
                if hstat.st_size < dstat.st_size:
                    grew = False
                else:
                    grew = hstat.st_size > dstat.st_size or hstat.st_mtime > dstat.st_mtime
            if grew:
                self.last_growth = time.monotonic()
                self._pending_growth = True
            pending = getattr(self, "_pending_growth", False)
            if pending and (time.monotonic() - self.last_growth) >= self.idle:
                snap = self.flush()
                self._pending_growth = False
            else:
                snap = {"copied": False, "reason": "waiting_idle" if pending else "unchanged"}
            time.sleep(DEFAULT_POLL)
        return {
            "ok": True,
            "session": self.slug,
            "source": str(self.source_path) if self.source_path else "",
            "cursor": str(self.cursor_path),
            "copied": self.copied,
            "snapshot": snap,
            "pos": self.cursor.pos,
            "size": self.cursor.size,
        }


def merge_runtime_args(args, bundle: Path | None) -> None:
    """Fill missing CLI fields from okf/temporal/tailer.json. No remotes."""
    cfg = load_tailer_config(bundle) if bundle is not None else {}
    if not getattr(args, "jsonl", "") and (cfg.get("jsonl") or cfg.get("source")):
        args.jsonl = str(cfg.get("jsonl") or cfg.get("source"))
    if not getattr(args, "author", "") and cfg.get("identity"):
        args.author = str(cfg["identity"])
    if not getattr(args, "host", None) or args.host == "claude-code":
        if cfg.get("host"):
            args.host = str(cfg["host"])
    if not getattr(args, "role", "") and cfg.get("role"):
        args.role = str(cfg["role"])
    if not getattr(args, "agent", "") and cfg.get("agent"):
        args.agent = str(cfg["agent"])
    if getattr(args, "n", 1) == 1 and cfg.get("n"):
        try:
            args.n = int(cfg["n"])
        except (TypeError, ValueError):
            pass
    if getattr(args, "idle", DEFAULT_IDLE) == DEFAULT_IDLE and cfg.get("idle_seconds") is not None:
        try:
            args.idle = float(cfg["idle_seconds"])
        except (TypeError, ValueError):
            pass
    if not getattr(args, "cursor", "") and cfg.get("cursor"):
        args.cursor = str(cfg["cursor"])


def resolve_cursor_path(raw: str, bundle: Path, jsonl: Path | None) -> Path:
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else (bundle / p)
    return bundle / CURSOR_REL


def build_tailer(args) -> Tailer:
    bundle = require_bundle(args.bundle)
    merge_runtime_args(args, bundle)
    jsonl = require_jsonl(getattr(args, "jsonl", ""))
    author, actor = require_identity(getattr(args, "author", ""))
    role = (getattr(args, "role", "") or "").strip()
    agent = (getattr(args, "agent", "") or "").strip()
    if not role or not agent:
        raise SystemExit(fail("missing agent", hint="pass --role and --agent or run setup"))
    slug = session_slug(role, agent, int(getattr(args, "n", 1) or 1))
    cursor_path = resolve_cursor_path(getattr(args, "cursor", "") or "", bundle, jsonl)
    return Tailer(
        jsonl=jsonl,
        bundle=bundle,
        cursor_path=cursor_path,
        host=getattr(args, "host", "claude-code") or "claude-code",
        slug=slug,
        agent=agent.strip().lower().replace("-", "_"),
        role=role.strip().lower().replace("-", "_"),
        author=author,
        actor=actor,
        idle=float(getattr(args, "idle", DEFAULT_IDLE) or DEFAULT_IDLE),
        once=True,
    )


def cmd_once(args) -> int:
    tailer = build_tailer(args)
    tailer.once = True
    print(json.dumps(tailer.run()))
    return 0


def cmd_follow(args) -> int:
    tailer = build_tailer(args)
    tailer.once = False
    print(json.dumps(tailer.run()))
    return 0


def cmd_start(args) -> int:
    bundle = require_bundle(args.bundle)
    merge_runtime_args(args, bundle)
    jsonl = require_jsonl(getattr(args, "jsonl", ""))
    require_identity(getattr(args, "author", ""))
    running = read_pid(bundle)
    if running:
        return fail("already running", pid=running)
    child = [
        sys.executable,
        str(Path(__file__).resolve()),
        "follow",
        "--jsonl",
        str(jsonl),
        "--bundle",
        str(bundle),
        "--host",
        getattr(args, "host", "claude-code") or "claude-code",
        "--role",
        args.role,
        "--agent",
        args.agent,
        "--n",
        str(getattr(args, "n", 1) or 1),
        "--idle",
        str(getattr(args, "idle", DEFAULT_IDLE) or DEFAULT_IDLE),
    ]
    if getattr(args, "author", ""):
        child += ["--author", args.author]
    if getattr(args, "cursor", ""):
        child += ["--cursor", args.cursor]
    log = bundle / "okf" / "temporal" / ".ots-tail.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = log.open("ab")
    proc = subprocess.Popen(
        child,
        stdout=fh,
        stderr=fh,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=os.environ.copy(),
    )
    write_pid(bundle, proc.pid)
    print(json.dumps({"ok": True, "pid": proc.pid, "log": str(log)}))
    return 0


def cmd_stop(args) -> int:
    bundle = require_bundle(args.bundle, must_exist=True)
    pid = read_pid(bundle)
    stored = bundle / PID_REL
    if stored.exists() and pid is None:
        try:
            stale = int(stored.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            stale = 0
        clear_pid(bundle)
        print(json.dumps({"ok": True, "stopped": False, "stale_pid": stale}))
        return 0
    if pid is None:
        return fail("not running")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        clear_pid(bundle)
        return fail("stop failed", detail=str(exc))
    clear_pid(bundle)
    print(json.dumps({"ok": True, "stopped": True, "pid": pid}))
    return 0


def cmd_status(args) -> int:
    try:
        bundle = require_bundle(args.bundle)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    merge_runtime_args(args, bundle)
    pid = read_pid(bundle)
    cfg = load_tailer_config(bundle)
    jsonl_raw = getattr(args, "jsonl", "") or cfg.get("jsonl") or ""
    cursor_path = resolve_cursor_path(getattr(args, "cursor", "") or "", bundle, None)
    cursor = load_cursor(cursor_path)
    session = None
    source = ""
    slug = cursor.session_id
    if not slug and getattr(args, "role", "") and getattr(args, "agent", ""):
        slug = session_slug(args.role, args.agent, int(getattr(args, "n", 1) or 1))
    if slug:
        session_path = find_session(bundle, slug)
        if session_path:
            session = str(session_path)
            src = source_path_for(session_path, slug)
            if src.exists():
                source = str(src)
    print(
        json.dumps(
            {
                "ok": True,
                "running": pid is not None,
                "pid": pid,
                "jsonl": jsonl_raw,
                "source": source,
                "session": slug or "",
                "session_path": session or "",
                "cursor": cursor.to_json(),
                "cursor_path": str(cursor_path),
            }
        )
    )
    return 0


def cmd_check(args) -> int:
    try:
        _author, _actor = require_identity(getattr(args, "author", ""))
        bundle = require_bundle(args.bundle)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    merge_runtime_args(args, bundle)
    try:
        jsonl = require_jsonl(getattr(args, "jsonl", ""))
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    cursor_path = resolve_cursor_path(getattr(args, "cursor", "") or "", bundle, jsonl)
    cursor = load_cursor(cursor_path)
    if cursor.path or cursor.pos or cursor.size:
        reason = cursor.stale_reason(jsonl)
        if reason:
            return fail("cursor stale", reason=reason, cursor=cursor.to_json())
    print(json.dumps({"ok": True, "source": str(jsonl), "cursor": cursor.to_json()}))
    return 0


def cmd_setup(args) -> int:
    bundle = require_bundle(args.bundle, must_exist=False)
    jsonl_raw = (getattr(args, "jsonl", "") or "").strip()
    if jsonl_raw and looks_like_remote(jsonl_raw):
        return fail("do not hard-code a remote", hint="use a local host JSONL path")
    if jsonl_raw:
        p = Path(jsonl_raw)
        if not p.exists():
            return fail("missing source", path=jsonl_raw)
        jsonl_raw = str(p.resolve())
    role = (getattr(args, "role", "") or "software_engineer").strip()
    agent = (getattr(args, "agent", "") or "local").strip()
    host = getattr(args, "host", "claude-code") or "claude-code"
    n = int(getattr(args, "n", 1) or 1)
    idle = float(getattr(args, "idle", DEFAULT_IDLE) or DEFAULT_IDLE)
    cursor = getattr(args, "cursor", "") or CURSOR_REL.as_posix()
    identity = (getattr(args, "identity", "") or getattr(args, "author", "") or "local/tailer").strip()
    edition = (getattr(args, "edition", "") or "").strip().lower()
    model = (getattr(args, "model", "") or "").strip()
    data = {
        "v": 1,
        "identity": identity,
        "host": host,
        "source": jsonl_raw,
        "jsonl": jsonl_raw,
        "role": role,
        "agent": agent,
        "n": n,
        "idle": idle,
        "idle_seconds": idle,
        "cursor": cursor,
    }
    if edition:
        if edition not in {"a", "b"}:
            return fail("edition must be a or b")
        try:
            extra = editions.edition_config_fields(host, edition, identity=identity)
        except ValueError as exc:
            return fail(str(exc))
        if edition == "a":
            check = editions.verify_edition_a(host, model or extra["model"])
        else:
            check = editions.verify_edition_b(
                host,
                model=model or extra["model"],
                provider=getattr(args, "provider", "") or extra.get("provider") or "",
                api_key_env=getattr(args, "api_key_env", "") or extra.get("api_key_env") or "",
            )
        if not check.get("ok"):
            print(json.dumps(check))
            return 1
        data.update(extra)
        if model:
            data["model"] = extra["model"]
    dest = write_tailer_config(bundle, data)
    print(json.dumps({"ok": True, "path": str(dest), "config": data}))
    return 0


def add_common_flags(p: argparse.ArgumentParser, *, require_agent: bool = False) -> None:
    p.add_argument("--jsonl", default="", help="host session JSONL (read-only)")
    p.add_argument("--bundle", default="", help="OKF bundle; default SECOND_BRAIN_ROOT")
    p.add_argument("--author", default="", help="process author (default local/tailer once identity is claimed)")
    p.add_argument("--host", default="claude-code", choices=HOSTS)
    p.add_argument("--role", default="", required=require_agent, help="session agent role (slug)")
    p.add_argument("--agent", default="", required=require_agent, help="session agent name (slug)")
    p.add_argument("--n", type=int, default=1, help="session ordinal, default 1 → __001")
    p.add_argument("--idle", type=float, default=DEFAULT_IDLE, help="idle flush seconds (default 300)")
    p.add_argument("--cursor", default="", help="cursor file; default okf/temporal/.ots-cursor.json")
    p.add_argument("--identity", default="", help="process identity written to tailer.json (default local/tailer)")
    p.add_argument("--edition", default="", choices=["a", "b"], help="summarize edition (setup)")
    p.add_argument("--model", default="", help="must match the pinned cheapest model for --host")
    p.add_argument("--provider", default="", help="edition b provider (anthropic|openai|xai)")
    p.add_argument("--api-key-env", dest="api_key_env", default="", help="edition b key env name")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ots_tail_jsonl.py",
        description="Copy host JSONL → sessions/<slug>.source.jsonl (no LLM, no stored emit schema).",
    )
    p.add_argument("--once", action="store_true", help="compat: drain once (same as subcommand once)")
    p.add_argument("--follow", action="store_true", help="compat: long-running foreground")
    add_common_flags(p)
    sub = p.add_subparsers(dest="cmd")
    for name in ("once", "follow", "start", "stop", "status", "check", "setup"):
        sp = sub.add_parser(name)
        add_common_flags(sp)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cmd = args.cmd
    if args.follow and args.once:
        return fail("use --once or --follow, not both")
    if not cmd:
        if args.once:
            cmd = "once"
        elif args.follow:
            cmd = "follow"
        else:
            return fail("missing command", hint="once|follow|start|stop|status|check|setup")
    handlers = {
        "once": cmd_once,
        "follow": cmd_follow,
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "check": cmd_check,
        "setup": cmd_setup,
    }
    try:
        return handlers[cmd](args)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1


if __name__ == "__main__":
    sys.exit(main())
