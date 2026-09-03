#!/usr/bin/env python3
"""Deterministic write helper for okf-time-series.

The model proposes summary and saliency prose. This script commits frontmatter.
It never trusts the model with type, period, aggregates, or identity.

Identity: session `agent` resolves to an existing AgentIdentity (second-brain-core).
This plugin does not define a new identity type.

Bundle root: SECOND_BRAIN_ROOT. Never hard-code a private remote.

Walk and rollup are index-free: they read the filesystem, not BM25/vector/graph.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import secrets
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OWNED_TYPES = {
    "temporal.year": "year",
    "temporal.month": "month",
    "temporal.week": "week",
    "temporal.day": "day",
    "temporal.hour": "hour",
    "temporal.session": "session",
    "temporal.telemetry": "telemetry",
    "temporal.summary": "summary",
    "temporal.saliency": "saliency",
}

CLOSE_REASONS = {"clear", "compact", "user", "watchdog"}
STATUSES = {"open", "segmented", "finalized"}
SESSION_SLUG = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*__[a-z0-9]+(?:_[a-z0-9]+)*__\d{3}$")
PERIOD_YEAR = re.compile(r"^\d{4}$")
PERIOD_MONTH = re.compile(r"^\d{4}-\d{2}$")
PERIOD_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")
PERIOD_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERIOD_HOUR = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})$")
ARTIFACT_SUFFIXES = (".telemetry.md", ".summary.md", ".saliency.md")

# Crockford base32, no I L O U. 26 chars = 10-byte timestamp + 16-byte entropy, ULID-shaped.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ulid() -> str:
    """wiki_ticket_sdd-compatible ULID (Crockford, 26 chars). Not a new scheme."""
    ms = int(time.time() * 1000)
    time_chars = []
    for _ in range(10):
        time_chars.append(_CROCKFORD[ms & 31])
        ms >>= 5
    rand = secrets.randbits(80)
    rand_chars = []
    for _ in range(16):
        rand_chars.append(_CROCKFORD[rand & 31])
        rand >>= 5
    return "".join(reversed(time_chars)) + "".join(reversed(rand_chars))


def resolve_bundle(raw: str | None) -> Path:
    value = (raw or os.environ.get("SECOND_BRAIN_ROOT") or "knowledge").strip()
    p = Path(value)
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_author(explicit: str | None) -> str:
    author = (explicit or os.environ.get("SECOND_BRAIN_IDENTITY") or "").strip()
    if not author:
        print(json.dumps({"error": "claim an identity first", "hint": "pass --author or set SECOND_BRAIN_IDENTITY"}))
        raise SystemExit(1)
    return author


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    return _parse_yaml_lite(parts[1]), parts[2].lstrip("\n")


def _parse_yaml_lite(block: str) -> dict:
    meta: dict = {}
    key: str | None = None
    acc: list | None = None
    current: dict | None = None
    agent: dict | None = None
    for raw in block.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if re.match(r"^agent:\s*$", raw):
            agent = {}
            meta["agent"] = agent
            key = None
            acc = None
            current = None
            continue
        if agent is not None and raw.startswith("  ") and not raw.startswith("    ") and ":" in raw and not raw.strip().startswith("-"):
            k, v = raw.strip().split(":", 1)
            agent[k.strip()] = v.strip().strip("'\"")
            continue
        if re.match(r"^[A-Za-z0-9_]+:\s*$", raw):
            key = raw.split(":", 1)[0].strip()
            acc = []
            current = None
            agent = None
            meta[key] = acc
            continue
        if key is not None and acc is not None and raw.strip().startswith("- "):
            rest = raw.strip()[2:]
            if ":" in rest:
                current = {}
                k, v = rest.split(":", 1)
                current[k.strip()] = v.strip().strip("'\"")
                acc.append(current)
            else:
                current = None
                acc.append(rest.strip().strip("'\""))
            continue
        if key is not None and current is not None and raw.startswith("    ") and ":" in raw:
            k, v = raw.strip().split(":", 1)
            current[k.strip()] = v.strip().strip("'\"")
            continue
        if ":" in raw and not raw.startswith(" "):
            key = None
            acc = None
            current = None
            agent = None
            k, v = raw.split(":", 1)
            val = v.strip().strip("'\"")
            meta[k.strip()] = val
    return meta


def dump_frontmatter(meta: dict) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, dict):
            lines.append(f"{k}:")
            for ik, iv in v.items():
                lines.append(f"  {ik}: {iv}")
        elif isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                if isinstance(item, dict):
                    items = list(item.items())
                    first_k, first_v = items[0]
                    lines.append(f"  - {first_k}: {first_v}")
                    for ik, iv in items[1:]:
                        lines.append(f"    {ik}: {iv}")
                else:
                    lines.append(f"  - {item}")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def write_md(path: Path, meta: dict, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_frontmatter(meta) + "\n" + body.rstrip() + "\n", encoding="utf-8")
    return path


def iso_week_range(period: str) -> tuple[str, str]:
    m = PERIOD_WEEK.match(period)
    if not m:
        raise ValueError(f"invalid week period: {period}")
    year, week = int(m.group(1)), int(m.group(2))
    start = date.fromisocalendar(year, week, 1)
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


def path_for(period: str, kind: str, slug: str | None = None) -> Path:
    """Directory layout from the PRD. Week folder is nested under the month of start_date.

    Open question on #72: ISO weeks that span two months nest under start_date's month only.
    That is illustrated, not decided.
    """
    if kind == "year":
        if not PERIOD_YEAR.match(period):
            raise ValueError(f"invalid year period: {period}")
        return Path(f"okf/temporal/{period}/{period}.md")
    if kind == "month":
        if not PERIOD_MONTH.match(period):
            raise ValueError(f"invalid month period: {period}")
        year, month = period.split("-")
        return Path(f"okf/temporal/{year}/{month}/{period}.md")
    if kind == "week":
        start, _ = iso_week_range(period)
        year, month, _ = start.split("-")
        return Path(f"okf/temporal/{year}/{month}/{period[5:]}/{period}.md")
    if kind == "day":
        if not PERIOD_DAY.match(period):
            raise ValueError(f"invalid day period: {period}")
        year, month, day = period.split("-")
        return Path(f"okf/temporal/{year}/{month}/{day}/{period}.md")
    if kind == "hour":
        m = PERIOD_HOUR.match(period)
        if not m:
            raise ValueError(f"invalid hour period: {period}")
        day, hour = m.group(1), m.group(2)
        year, month, d = day.split("-")
        return Path(f"okf/temporal/{year}/{month}/{d}/{hour}/{period}.md")
    if kind == "session":
        if not slug or not SESSION_SLUG.match(slug):
            raise ValueError(f"invalid session slug: {slug}")
        hour_path = path_for(period, "hour")
        return hour_path.parent / "sessions" / f"{slug}.md"
    raise ValueError(f"unknown kind: {kind}")


def validate_aggregates(bundle: Path, node_path: Path, aggregates: list) -> list[str]:
    errors = []
    for rel in aggregates:
        if not isinstance(rel, str) or not rel:
            errors.append(f"{node_path}: empty aggregate entry")
            continue
        target = (node_path.parent / rel).resolve()
        try:
            target.relative_to(bundle.resolve())
        except ValueError:
            errors.append(f"{node_path}: aggregate escapes bundle: {rel}")
            continue
        if not target.exists():
            errors.append(f"{node_path}: dangling aggregate {rel}")
    return errors


def cmd_init(args) -> int:
    bundle = resolve_bundle(args.bundle)
    (bundle / "okf" / "temporal").mkdir(parents=True, exist_ok=True)
    idx = bundle / "okf" / "temporal" / "index.md"
    if not idx.exists():
        write_md(
            idx,
            {"type": "Index", "title": "Temporal", "timestamp": now_iso()},
            "# Temporal\n\nChronological spine. Walk Year → Month → Week → Day → Hour → Session.\n",
        )
    print(json.dumps({"ok": True, "bundle": str(bundle)}))
    return 0


def cmd_path_for(args) -> int:
    p = path_for(args.period, args.kind, args.slug)
    print(json.dumps({"ok": True, "path": p.as_posix()}))
    return 0


def _rel_between(parent: Path, child: Path) -> str:
    return Path(os.path.relpath(child, start=parent.parent)).as_posix()


def _append_aggregate(parent_file: Path, child_file: Path) -> bool:
    """Add child to parent aggregates if missing. Does not invent summary prose."""
    if not parent_file.exists():
        return False
    meta, body = parse_frontmatter(parent_file.read_text(encoding="utf-8"))
    rel = _rel_between(parent_file, child_file)
    aggs = list(meta.get("aggregates") or [])
    if rel in aggs:
        return False
    aggs.append(rel)
    meta["aggregates"] = aggs
    write_md(parent_file, meta, body)
    return True


def _blank_aggregate_body(title: str) -> str:
    return f"# {title}\n\n## Summary\n\n(proposed)\n\n## Saliency\n\n- (proposed)\n"


def ensure_spine(bundle: Path, hour_period: str, author: str) -> list[str]:
    """Create missing Year→Month→Week→Day→Hour files and wire aggregates.

    Eager Hour nodes, as illustrated on #72 — not a vote on the threshold question.
    Does not write summary or saliency prose.
    """
    m = PERIOD_HOUR.match(hour_period)
    if not m:
        raise ValueError(f"invalid hour period: {hour_period}")
    day = m.group(1)
    year_s, month_s, _ = day.split("-")
    d = date.fromisoformat(day)
    iso = d.isocalendar()
    week_period = f"{iso.year}-W{iso.week:02d}"
    last = calendar.monthrange(int(year_s), int(month_s))[1]
    specs = [
        ("year", year_s, f"{year_s}-01-01", f"{year_s}-12-31", year_s),
        ("month", f"{year_s}-{month_s}", f"{year_s}-{month_s}-01", f"{year_s}-{month_s}-{last:02d}", f"{year_s}-{month_s}"),
        ("week", week_period, *iso_week_range(week_period), week_period),
        ("day", day, day, day, day),
        ("hour", hour_period, day, day, hour_period),
    ]
    created: list[str] = []
    files: dict[str, Path] = {}
    for kind, period, start, end, title in specs:
        rel = path_for(period, kind)
        dest = bundle / rel
        files[kind] = dest
        if dest.exists():
            continue
        write_md(
            dest,
            {
                "type": f"temporal.{kind}",
                "title": title,
                "period": period,
                "start_date": start,
                "end_date": end,
                "status": "open",
                "timestamp": now_iso(),
                "author": author,
                "aggregates": [],
            },
            _blank_aggregate_body(title),
        )
        created.append(rel.as_posix())
    _append_aggregate(files["year"], files["month"])
    _append_aggregate(files["month"], files["week"])
    _append_aggregate(files["week"], files["day"])
    _append_aggregate(files["day"], files["hour"])
    return created


def cmd_write_aggregate(args) -> int:
    author = resolve_author(args.author)
    kind = args.kind
    typ = f"temporal.{kind}"
    if typ not in OWNED_TYPES:
        print(json.dumps({"error": f"unowned type: {typ}"}))
        return 1
    rel = path_for(args.period, kind)
    bundle = resolve_bundle(args.bundle)
    dest = bundle / rel
    aggregates = [a for a in (args.aggregates or "").split(",") if a.strip()]
    status = args.status or "open"
    if status not in STATUSES:
        print(json.dumps({"error": f"invalid status: {status}", "allowed": sorted(STATUSES)}))
        return 1
    start = args.start_date
    end = args.end_date
    if kind == "week" and (not start or not end):
        start, end = iso_week_range(args.period)
    meta = {
        "type": typ,
        "title": args.title or args.period,
        "period": args.period,
        "start_date": start,
        "end_date": end,
        "status": status,
        "timestamp": now_iso(),
        "author": author,
        "aggregates": aggregates,
    }
    errors = validate_aggregates(bundle, dest, aggregates) if aggregates else []
    if errors and not args.allow_dangling:
        print(json.dumps({"error": "dangling aggregates", "errors": errors}))
        return 1
    body = args.body or _blank_aggregate_body(meta["title"])
    write_md(dest, meta, body)
    print(json.dumps({"ok": True, "path": str(dest), "author": author}))
    return 0


def cmd_write_session(args) -> int:
    author = resolve_author(args.author)
    slug = args.id
    if not SESSION_SLUG.match(slug):
        print(json.dumps({"error": "id must match role_name__agent_name__NNN", "id": slug}))
        return 1
    close = args.close_reason or "clear"
    status = args.status or "finalized"
    if close not in CLOSE_REASONS:
        print(json.dumps({"error": f"invalid close_reason: {close}", "allowed": sorted(CLOSE_REASONS)}))
        return 1
    if status not in STATUSES:
        print(json.dumps({"error": f"invalid status: {status}", "allowed": sorted(STATUSES)}))
        return 1
    if not args.agent_name or not args.agent_role:
        print(json.dumps({"error": "agent name and role required — they resolve to AgentIdentity, they do not define one"}))
        return 1
    bundle = resolve_bundle(args.bundle)
    created: list[str] = []
    if args.ensure_spine:
        created = ensure_spine(bundle, args.period, author)
    rel = path_for(args.period, "session", slug)
    dest = bundle / rel
    parent = f"../{path_for(args.period, 'hour').name}"
    sid = ulid()
    meta = {
        "type": "temporal.session",
        "id": slug,
        "ulid": sid,
        "agent": {
            "name": args.agent_name,
            "role": args.agent_role,
            "machine": args.machine or "unknown",
        },
        "started_at": args.started_at,
        "ended_at": args.ended_at,
        "close_reason": close,
        "status": status,
        "parent": parent,
        "timestamp": now_iso(),
        "author": author,
    }
    segs = []
    if args.telemetry:
        segs.append(
            {
                "telemetry": args.telemetry,
                "summary": args.summary or "",
                "saliency": args.saliency or "",
            }
        )
    if segs:
        meta["segments"] = segs
    body = args.body or f"# {args.title or slug}\n"
    if args.title:
        meta["title"] = args.title
    write_md(dest, meta, body)
    hour_file = bundle / path_for(args.period, "hour")
    linked = _append_aggregate(hour_file, dest) if hour_file.exists() else False
    print(json.dumps({"ok": True, "path": str(dest), "ulid": sid, "author": author, "spine": created, "hour_linked": linked}))
    return 0


def cmd_write_artifact(args) -> int:
    author = resolve_author(args.author)
    kind = args.kind
    typ = f"temporal.{kind}"
    if kind not in {"telemetry", "summary", "saliency"}:
        print(json.dumps({"error": f"unowned artifact: {kind}"}))
        return 1
    bundle = resolve_bundle(args.bundle)
    session = Path(args.session)
    dest = session.parent / f"{session.stem}.{kind}{args.n and '_' + args.n or ''}.md"
    dest = bundle / dest if not dest.is_absolute() else dest
    meta = {
        "type": typ,
        "title": f"{session.stem} {kind}",
        "session": session.name,
        "timestamp": now_iso(),
        "author": author,
    }
    body = args.body or ""
    if kind == "telemetry" and args.body and not args.body.strip().startswith("```"):
        body = "```jsonl\n" + args.body.rstrip() + "\n```\n"
    write_md(dest, meta, body)
    print(json.dumps({"ok": True, "path": str(dest)}))
    return 0


def iter_nodes(bundle: Path):
    root = bundle / "okf" / "temporal"
    if not root.exists():
        return
    for p in root.rglob("*.md"):
        if p.name == "index.md":
            continue
        text = p.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        rel = "/" + str(p.relative_to(bundle)).replace("\\", "/")
        yield {"path": rel, "file": p, "meta": meta, "body": body}


def _is_session_artifact(name: str) -> bool:
    return name.endswith(ARTIFACT_SUFFIXES)


def _record(path: Path, bundle: Path) -> dict | None:
    if not path.exists() or not path.is_file():
        return None
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    typ = meta.get("type", "")
    rec = {
        "kind": OWNED_TYPES.get(typ, typ),
        "type": typ,
        "title": meta.get("title", path.stem),
        "period": meta.get("period", ""),
        "status": meta.get("status", ""),
        "path": "/" + str(path.relative_to(bundle)).replace("\\", "/"),
        "aggregates": meta.get("aggregates") or [],
        "author": meta.get("author", ""),
    }
    if typ == "temporal.session":
        rec["id"] = meta.get("id")
        rec["ulid"] = meta.get("ulid")
        rec["agent"] = meta.get("agent") or {}
        rec["close_reason"] = meta.get("close_reason")
        rec["started_at"] = meta.get("started_at")
        rec["ended_at"] = meta.get("ended_at")
        rec["parent"] = meta.get("parent")
    rec["excerpt"] = " ".join(body.split())[:240]
    return rec


def walk_tree(bundle: Path) -> list[dict]:
    """Index-free chronological walk. Directories are the index."""
    root = bundle / "okf" / "temporal"
    years: list[dict] = []
    if not root.exists():
        return years
    for ydir in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
        year = _record(ydir / f"{ydir.name}.md", bundle) or {
            "kind": "year",
            "period": ydir.name,
            "path": f"/okf/temporal/{ydir.name}/{ydir.name}.md",
            "missing": True,
        }
        year["children"] = []
        for mdir in sorted((p for p in ydir.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: p.name):
            month_md = mdir / f"{ydir.name}-{mdir.name}.md"
            month = _record(month_md, bundle) or {
                "kind": "month",
                "period": f"{ydir.name}-{mdir.name}",
                "path": f"/okf/temporal/{ydir.name}/{mdir.name}/{ydir.name}-{mdir.name}.md",
                "missing": True,
            }
            month["weeks"] = []
            month["days"] = []
            for sub in sorted((p for p in mdir.iterdir() if p.is_dir()), key=lambda p: p.name):
                if sub.name.startswith("W"):
                    week_md = sub / f"{ydir.name}-{sub.name}.md"
                    week = _record(week_md, bundle) or {
                        "kind": "week",
                        "period": f"{ydir.name}-{sub.name}",
                        "path": f"/okf/temporal/{ydir.name}/{mdir.name}/{sub.name}/{ydir.name}-{sub.name}.md",
                        "missing": True,
                    }
                    month["weeks"].append(week)
                    continue
                if not (sub.name.isdigit() and len(sub.name) == 2):
                    continue
                day_period = f"{ydir.name}-{mdir.name}-{sub.name}"
                day = _record(sub / f"{day_period}.md", bundle) or {
                    "kind": "day",
                    "period": day_period,
                    "path": f"/okf/temporal/{ydir.name}/{mdir.name}/{sub.name}/{day_period}.md",
                    "missing": True,
                }
                day["hours"] = []
                for hdir in sorted((p for p in sub.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: p.name):
                    hour_period = f"{day_period}T{hdir.name}"
                    hour = _record(hdir / f"{hour_period}.md", bundle) or {
                        "kind": "hour",
                        "period": hour_period,
                        "path": f"/okf/temporal/{ydir.name}/{mdir.name}/{sub.name}/{hdir.name}/{hour_period}.md",
                        "missing": True,
                    }
                    hour["sessions"] = []
                    sdir = hdir / "sessions"
                    if sdir.exists():
                        for smd in sorted(sdir.glob("*.md")):
                            if _is_session_artifact(smd.name):
                                continue
                            rec = _record(smd, bundle)
                            if rec:
                                hour["sessions"].append(rec)
                    day["hours"].append(hour)
                month["days"].append(day)
            year["children"].append(month)
        years.append(year)
    return years


def flatten_walk(tree: list[dict]) -> list[dict]:
    out: list[dict] = []

    def take(node: dict, skip_keys: tuple[str, ...]) -> dict:
        return {k: v for k, v in node.items() if k not in skip_keys}

    for year in tree:
        out.append(take(year, ("children",)))
        for month in year.get("children") or []:
            out.append(take(month, ("weeks", "days")))
            for week in month.get("weeks") or []:
                out.append(take(week, ()))
            for day in month.get("days") or []:
                out.append(take(day, ("hours",)))
                for hour in day.get("hours") or []:
                    out.append(take(hour, ("sessions",)))
                    for session in hour.get("sessions") or []:
                        out.append(session)
    return out


def cmd_walk(args) -> int:
    bundle = Path(args.bundle or os.environ.get("SECOND_BRAIN_ROOT") or "knowledge")
    tree = walk_tree(bundle)
    if args.flat:
        nodes = flatten_walk(tree)
        if args.kind:
            nodes = [n for n in nodes if n.get("kind") == args.kind]
        print(json.dumps({"ok": True, "engine": "filesystem", "nodes": nodes}, indent=2))
        return 0
    print(json.dumps({"ok": True, "engine": "filesystem", "tree": tree}, indent=2))
    return 0


def cmd_rollup(args) -> int:
    """Attach existing children to parent aggregates. No prose. Model proposes summaries separately."""
    author = resolve_author(args.author)
    bundle = resolve_bundle(args.bundle)
    kind = args.kind
    period = args.period
    parent = bundle / path_for(period, kind)
    if not parent.exists():
        print(json.dumps({"error": "parent node missing", "path": str(parent), "hint": "write-session --ensure-spine or write-aggregate first"}))
        return 1
    linked: list[str] = []
    if kind == "hour":
        sdir = parent.parent / "sessions"
        if sdir.exists():
            for smd in sorted(sdir.glob("*.md")):
                if _is_session_artifact(smd.name):
                    continue
                if _append_aggregate(parent, smd):
                    linked.append(smd.name)
    elif kind == "day":
        for hdir in sorted(p for p in parent.parent.iterdir() if p.is_dir() and p.name.isdigit()):
            hour_md = hdir / f"{period}T{hdir.name}.md"
            if hour_md.exists() and _append_aggregate(parent, hour_md):
                linked.append(hour_md.name)
    elif kind == "week":
        start, end = iso_week_range(period)
        cur = date.fromisoformat(start)
        last = date.fromisoformat(end)
        while cur <= last:
            day_rel = path_for(cur.isoformat(), "day")
            day_file = bundle / day_rel
            if day_file.exists() and _append_aggregate(parent, day_file):
                linked.append(day_rel.as_posix())
            cur += timedelta(days=1)
    elif kind == "month":
        year, month = period.split("-")
        mdir = parent.parent
        for sub in sorted(p for p in mdir.iterdir() if p.is_dir()):
            if sub.name.startswith("W"):
                week_md = sub / f"{year}-{sub.name}.md"
                if week_md.exists() and _append_aggregate(parent, week_md):
                    linked.append(week_md.name)
    elif kind == "year":
        ydir = parent.parent
        for mdir in sorted(p for p in ydir.iterdir() if p.is_dir() and p.name.isdigit()):
            month_md = mdir / f"{period}-{mdir.name}.md"
            if month_md.exists() and _append_aggregate(parent, month_md):
                linked.append(month_md.name)
    else:
        print(json.dumps({"error": f"rollup not defined for {kind}"}))
        return 1
    meta, body = parse_frontmatter(parent.read_text(encoding="utf-8"))
    meta["author"] = author
    meta["timestamp"] = now_iso()
    write_md(parent, meta, body)
    print(json.dumps({"ok": True, "path": str(parent), "linked": linked, "prose": "unchanged"}))
    return 0


def cmd_validate(args) -> int:
    bundle = Path(args.bundle or os.environ.get("SECOND_BRAIN_ROOT") or "knowledge")
    errors: list[str] = []
    seen = 0
    for c in iter_nodes(bundle) or []:
        seen += 1
        meta = c["meta"]
        typ = meta.get("type", "")
        if not typ:
            errors.append(f"{c['path']}: missing type")
            continue
        if typ not in OWNED_TYPES and typ != "Index":
            errors.append(f"{c['path']}: unowned type {typ}")
        if not meta.get("title"):
            errors.append(f"{c['path']}: missing title")
        kind = OWNED_TYPES.get(typ)
        period = meta.get("period")
        if kind in {"year", "month", "week", "day", "hour"}:
            if not period:
                errors.append(f"{c['path']}: missing period")
            else:
                try:
                    expected = path_for(period, kind)
                    actual = Path(c["path"].lstrip("/"))
                    if actual != expected:
                        errors.append(f"{c['path']}: path does not match period {period} (expected {expected.as_posix()})")
                except ValueError as e:
                    errors.append(f"{c['path']}: {e}")
            status = meta.get("status")
            if status and status not in STATUSES:
                errors.append(f"{c['path']}: invalid status {status}")
            errors.extend(validate_aggregates(bundle, c["file"], meta.get("aggregates") or []))
        if typ == "temporal.session":
            sid = meta.get("id", "")
            if not SESSION_SLUG.match(str(sid)):
                errors.append(f"{c['path']}: id must match role_name__agent_name__NNN")
            agent = meta.get("agent") or {}
            if not agent.get("name") or not agent.get("role"):
                errors.append(f"{c['path']}: agent.name and agent.role required (AgentIdentity, not a new type)")
            cr = meta.get("close_reason")
            if cr and cr not in CLOSE_REASONS:
                errors.append(f"{c['path']}: invalid close_reason {cr}")
            st = meta.get("status")
            if st and st not in STATUSES:
                errors.append(f"{c['path']}: invalid status {st}")
    result = {"ok": len(errors) == 0, "nodes": seen, "errors": errors}
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def main() -> int:
    p = argparse.ArgumentParser(prog="ots_common.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init")
    i.add_argument("--bundle", default="")

    pf = sub.add_parser("path-for")
    pf.add_argument("--period", required=True)
    pf.add_argument("--kind", required=True)
    pf.add_argument("--slug", default="")

    w = sub.add_parser("write-aggregate")
    w.add_argument("--bundle", default="")
    w.add_argument("--kind", required=True, choices=["year", "month", "week", "day", "hour"])
    w.add_argument("--period", required=True)
    w.add_argument("--title", default="")
    w.add_argument("--start-date", dest="start_date", default="")
    w.add_argument("--end-date", dest="end_date", default="")
    w.add_argument("--status", default="open")
    w.add_argument("--aggregates", default="")
    w.add_argument("--body", default="")
    w.add_argument("--author", default="")
    w.add_argument("--allow-dangling", action="store_true")

    s = sub.add_parser("write-session")
    s.add_argument("--bundle", default="")
    s.add_argument("--id", required=True)
    s.add_argument("--period", required=True, help="hour period, YYYY-MM-DDTHH")
    s.add_argument("--title", default="")
    s.add_argument("--agent-name", required=True)
    s.add_argument("--agent-role", required=True)
    s.add_argument("--machine", default="")
    s.add_argument("--started-at", dest="started_at", default="")
    s.add_argument("--ended-at", dest="ended_at", default="")
    s.add_argument("--close-reason", dest="close_reason", default="clear")
    s.add_argument("--status", default="finalized")
    s.add_argument("--telemetry", default="")
    s.add_argument("--summary", default="")
    s.add_argument("--saliency", default="")
    s.add_argument("--body", default="")
    s.add_argument("--author", default="")
    s.add_argument("--ensure-spine", dest="ensure_spine", action="store_true", default=True)
    s.add_argument("--no-ensure-spine", dest="ensure_spine", action="store_false")

    a = sub.add_parser("write-artifact")
    a.add_argument("--bundle", default="")
    a.add_argument("--session", required=True)
    a.add_argument("--kind", required=True, choices=["telemetry", "summary", "saliency"])
    a.add_argument("--n", default="")
    a.add_argument("--body", default="")
    a.add_argument("--author", default="")

    wk = sub.add_parser("walk")
    wk.add_argument("--bundle", default="")
    wk.add_argument("--flat", action="store_true")
    wk.add_argument("--kind", default="")

    ru = sub.add_parser("rollup")
    ru.add_argument("--bundle", default="")
    ru.add_argument("--kind", required=True, choices=["year", "month", "week", "day", "hour"])
    ru.add_argument("--period", required=True)
    ru.add_argument("--author", default="")

    v = sub.add_parser("validate")
    v.add_argument("--bundle", default="")

    args = p.parse_args()
    fn = {
        "init": cmd_init,
        "path-for": cmd_path_for,
        "write-aggregate": cmd_write_aggregate,
        "write-session": cmd_write_session,
        "write-artifact": cmd_write_artifact,
        "walk": cmd_walk,
        "rollup": cmd_rollup,
        "validate": cmd_validate,
    }[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
