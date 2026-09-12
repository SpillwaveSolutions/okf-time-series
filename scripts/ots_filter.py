#!/usr/bin/env python3
"""Read-time host-switch filter for hour-close summarization.

NOT a stored write format. The bundle source of truth is
`sessions/<slug>.source.jsonl` (byte-for-byte vendor JSONL). This module
projects that snapshot into the in-memory view described by
docs/TELEMETRY_EMIT.md: user prompt + final assistant; skip tool_result.

No LLM. Adapters choose which file to copy and session boundaries only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import ots_common as ots

HOSTS = ("claude-code", "grok-build", "codex", "deep-agents")
ROLES = ("user", "assistant")
FILTER_VERSION = 1
REQUIRED_VIEW_KEYS = ("v", "ts", "host", "session_id", "actor", "turn", "role", "text")


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
    val = record.get("model") or msg.get("model")
    return str(val) if val else ""


def host_timestamp(record: dict) -> str:
    return normalize_ts(record.get("timestamp") or record.get("ts"))


@dataclass
class HostEvent:
    role: str
    text: str
    ts: str
    offset: int
    model: str = ""
    tool_result: bool = False


def parse_host_record(line: str, offset: int) -> HostEvent | None:
    """Parse one vendor JSONL line. Claude Code shape, plus a plain role/text object."""
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
    ts = host_timestamp(record)
    if tool_result:
        return HostEvent(role="user", text="", ts=ts, offset=offset, tool_result=True)
    if role not in ROLES:
        return None
    body = extract_text(record)
    if role == "assistant" and not body:
        return HostEvent(role="assistant", text="", ts=ts, offset=offset, model=host_model(record))
    if role == "user" and not body:
        return None
    return HostEvent(role=role, text=body, ts=ts, offset=offset, model=host_model(record))


def iter_host_events(path: Path) -> list[HostEvent]:
    events: list[HostEvent] = []
    offset = 0
    with path.open("rb") as fh:
        for raw in fh:
            ev = parse_host_record(raw.decode("utf-8", errors="replace"), offset)
            if ev is not None:
                events.append(ev)
            offset += len(raw)
    return events


def peek_host_bounds(path: Path) -> tuple[str, str]:
    """First and last parseable timestamps. Session-boundary adapter only."""
    first = ""
    last = ""
    if not path.exists():
        return first, last
    for ev in iter_host_events(path):
        if not first:
            first = ev.ts
        last = ev.ts
    return first, last


def pair_prompt_and_final(events: list[HostEvent]) -> list[tuple[HostEvent, HostEvent | None]]:
    """user prompt + last assistant text in the turn. Skip tool_result."""
    turns: list[tuple[HostEvent, HostEvent | None]] = []
    pending_user: HostEvent | None = None
    last_assistant: HostEvent | None = None
    for ev in events:
        if ev.tool_result:
            continue
        if ev.role == "user" and ev.text:
            if pending_user:
                turns.append((pending_user, last_assistant))
            pending_user = ev
            last_assistant = None
            continue
        if ev.role == "assistant" and ev.text:
            last_assistant = ev
    if pending_user:
        turns.append((pending_user, last_assistant))
    return turns


def turns_for_hour(
    turns: list[tuple[HostEvent, HostEvent | None]], period: str | None
) -> list[tuple[HostEvent, HostEvent | None]]:
    if not period:
        return turns
    return [t for t in turns if ots.hour_period_from_iso(t[0].ts) == period]


def view_object(
    *,
    ts: str,
    host: str,
    session_id: str,
    actor: str,
    turn: int,
    role: str,
    text: str,
    model: str = "",
) -> dict:
    """In-memory filter view. Do not persist this object as the capture."""
    obj: dict = {
        "v": FILTER_VERSION,
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
    return obj


def validate_view(obj: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return ["not an object"]
    for key in REQUIRED_VIEW_KEYS:
        if key not in obj or obj[key] in ("", None):
            errors.append(f"missing {key}")
    if "v" in obj and obj["v"] != FILTER_VERSION:
        errors.append(f"v must be {FILTER_VERSION}")
    if obj.get("host") not in HOSTS:
        errors.append("invalid host")
    if obj.get("role") not in ROLES:
        errors.append("invalid role")
    turn = obj.get("turn")
    if turn is not None and not (isinstance(turn, int) and not isinstance(turn, bool) and turn >= 1):
        errors.append("turn must be a monotonic int >= 1")
    return errors


def filter_source_jsonl(
    path: Path,
    *,
    host: str,
    session_id: str,
    actor: str,
    period: str | None = None,
) -> list[dict]:
    """Project `.source.jsonl` into the read-time filter view. Does not write."""
    events = iter_host_events(path)
    turns = turns_for_hour(pair_prompt_and_final(events), period)
    rows: list[dict] = []
    for i, (user, assistant) in enumerate(turns, start=1):
        rows.append(
            view_object(
                ts=user.ts,
                host=host,
                session_id=session_id,
                actor=actor,
                turn=i,
                role="user",
                text=user.text,
            )
        )
        if assistant:
            rows.append(
                view_object(
                    ts=assistant.ts,
                    host=host,
                    session_id=session_id,
                    actor=actor,
                    turn=i,
                    role="assistant",
                    text=assistant.text,
                    model=assistant.model,
                )
            )
    return rows
