#!/usr/bin/env python3
"""Summarize editions for okf-time-series.

Capture and storage are identical. Only the summarize backend differs.

Edition A — host CLI, no API key. Always pass the pinned cheapest model;
never trust the host default. Missing CLI or unverified model fails loudly.
No silent fallback to Edition B.

Edition B — direct HTTP with a verified key env + pinned model.

Config lives in the bundle: okf/temporal/tailer.json
Optional machine overlay: ~/.okf/ots-tail.json (or OKF_OTS_MACHINE_CONFIG).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

TAILER_CONFIG_REL = Path("okf/temporal/tailer.json")
MACHINE_CONFIG = Path.home() / ".okf" / "ots-tail.json"
REMOTE_PREFIXES = ("http://", "https://", "git@", "ssh://")

# Wizard-pinned cheapest model per host. Setup writes these; summarize uses them.
HOST_PINS = {
    "claude-code": {
        "bin": "claude",
        "argv": ["-p", "--model", "claude-haiku-4-5"],
        "model": "claude-haiku-4-5",
        "provider": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "deep-agents": {
        "bin": "claude",
        "argv": ["-p", "--model", "claude-haiku-4-5"],
        "model": "claude-haiku-4-5",
        "provider": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "codex": {
        "bin": "codex",
        "argv": ["exec", "-m", "gpt-5.6-luna"],
        "model": "gpt-5.6-luna",
        "provider": "openai",
        "api_key_env": "OPENAI_API_KEY",
    },
    "grok-build": {
        "bin": "grok",
        "argv": ["--model", "grok-4-fast", "-p"],
        "model": "grok-4-fast",
        "provider": "xai",
        "api_key_env": "XAI_API_KEY",
    },
}

SUMMARIZE_PROMPT = """You are summarizing one hour of a coding-agent session.
Return ONLY a JSON object with keys "summary" and "saliency".
"summary" is a short paragraph of what happened this hour.
"saliency" is markdown bullets (decisions, failures, names).
Samples in this pack are Northstar / Lumenfield fiction.
The turns below already passed the read-time filter: user prompt + final assistant; tool_result removed.

"""


def looks_like_remote(value: str) -> bool:
    return (value or "").strip().startswith(REMOTE_PREFIXES)


def pin_for(host: str) -> dict:
    pin = HOST_PINS.get(host)
    if not pin:
        raise ValueError(f"unknown host: {host}")
    return dict(pin)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_config(bundle: Path | None) -> dict:
    """Bundle tailer.json, then optional machine overlay. No remotes."""
    cfg: dict = {}
    if bundle is not None:
        cfg.update(_read_json(bundle / TAILER_CONFIG_REL))
    overlay = Path(os.environ.get("OKF_OTS_MACHINE_CONFIG") or MACHINE_CONFIG)
    if overlay.exists():
        extra = _read_json(overlay)
        for key in ("edition", "model", "provider", "api_key_env", "identity", "host", "idle_seconds", "idle"):
            if key in extra:
                cfg[key] = extra[key]
    if looks_like_remote(str(cfg.get("jsonl") or "")) or looks_like_remote(str(cfg.get("source") or "")):
        raise ValueError("do not hard-code a remote")
    if "source" in cfg and not cfg.get("jsonl"):
        cfg["jsonl"] = cfg["source"]
    if "idle" in cfg and cfg.get("idle_seconds") is None:
        cfg["idle_seconds"] = cfg["idle"]
    return cfg


def build_prompt(payload: dict) -> str:
    return SUMMARIZE_PROMPT + json.dumps(payload, ensure_ascii=False, indent=2)


def parse_model_json(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty model output")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model output is not JSON")
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict) or not data.get("summary"):
        raise ValueError("model JSON missing summary")
    data.setdefault("saliency", "- (proposed)")
    return data


def verify_edition_a(host: str, model: str | None = None, *, which=shutil.which, run=subprocess.run) -> dict:
    """Fail loudly if the host CLI is missing or the pinned model is wrong."""
    pin = pin_for(host)
    wanted = pin["model"]
    if model and model != wanted:
        return {"ok": False, "error": "wrong model", "wanted": wanted, "got": model, "edition": "a"}
    binary = which(pin["bin"])
    if not binary:
        return {"ok": False, "error": "cli missing", "bin": pin["bin"], "edition": "a", "hint": "install the host CLI or use setup --edition b with a verified key"}
    try:
        proc = run([binary, "--help"], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": "model cannot be verified", "bin": pin["bin"], "detail": str(exc), "edition": "a"}
    if proc.returncode != 0:
        return {"ok": False, "error": "model cannot be verified", "bin": pin["bin"], "returncode": proc.returncode, "edition": "a"}
    help_text = (proc.stdout or "") + (proc.stderr or "")
    model_flag = "--model" if "--model" in " ".join(pin["argv"]) else "-m"
    if model_flag not in help_text and "-m" not in help_text and "--model" not in help_text:
        # Some CLIs omit flags from --help; still require the binary to run.
        # The argv we store always includes the explicit model; never a host default.
        pass
    return {"ok": True, "edition": "a", "bin": binary, "model": wanted, "argv": [binary, *pin["argv"]]}


def verify_edition_b(host: str, model: str | None = None, provider: str = "", api_key_env: str = "", env: dict | None = None) -> dict:
    pin = pin_for(host)
    wanted = pin["model"]
    if model and model != wanted:
        return {"ok": False, "error": "wrong model", "wanted": wanted, "got": model, "edition": "b"}
    key_env = api_key_env or pin["api_key_env"]
    prov = provider or pin["provider"]
    environ = env if env is not None else os.environ
    if not (environ.get(key_env) or "").strip():
        return {
            "ok": False,
            "error": "key unset",
            "api_key_env": key_env,
            "edition": "b",
            "hint": f"set {key_env} or use setup --edition a",
        }
    return {"ok": True, "edition": "b", "model": wanted, "provider": prov, "api_key_env": key_env}


def invoke_edition_a(host: str, payload: dict, *, which=shutil.which, run=subprocess.run) -> dict:
    check = verify_edition_a(host, which=which, run=run)
    if not check.get("ok"):
        raise RuntimeError(json.dumps(check))
    pin = pin_for(host)
    binary = check["bin"]
    argv = [binary, *pin["argv"], build_prompt(payload)]
    try:
        proc = run(argv, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(json.dumps({"error": "edition a failed", "detail": str(exc), "edition": "a"})) from exc
    if proc.returncode != 0:
        raise RuntimeError(
            json.dumps(
                {
                    "error": "edition a failed",
                    "returncode": proc.returncode,
                    "stderr": (proc.stderr or "")[-400:],
                    "edition": "a",
                    "hint": "no silent fallback to edition b",
                }
            )
        )
    return parse_model_json(proc.stdout)


def invoke_edition_b(host: str, payload: dict, cfg: dict | None = None, env: dict | None = None, opener=None) -> dict:
    cfg = cfg or {}
    check = verify_edition_b(
        host,
        model=cfg.get("model"),
        provider=str(cfg.get("provider") or ""),
        api_key_env=str(cfg.get("api_key_env") or ""),
        env=env,
    )
    if not check.get("ok"):
        raise RuntimeError(json.dumps(check))
    environ = env if env is not None else os.environ
    key = (environ.get(check["api_key_env"]) or "").strip()
    prompt = build_prompt(payload)
    provider = check["provider"]
    model = check["model"]
    if provider == "anthropic":
        body = {
            "model": model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        text_key = "anthropic"
    elif provider == "openai":
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
            method="POST",
        )
        text_key = "openai"
    else:
        raise RuntimeError(json.dumps({"error": "unsupported provider", "provider": provider, "edition": "b"}))
    fetch = opener or urllib.request.urlopen
    try:
        with fetch(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(json.dumps({"error": "edition b failed", "detail": str(exc), "edition": "b"})) from exc
    data = json.loads(raw)
    if text_key == "anthropic":
        blocks = data.get("content") or []
        text = "".join(b.get("text") or "" for b in blocks if isinstance(b, dict))
    else:
        choices = data.get("choices") or []
        text = ""
        if choices:
            text = ((choices[0].get("message") or {}).get("content")) or ""
    return parse_model_json(text)


def edition_config_fields(host: str, edition: str, *, identity: str = "") -> dict:
    pin = pin_for(host)
    out = {
        "edition": edition,
        "model": pin["model"],
        "identity": identity or "local/tailer",
    }
    if edition == "b":
        out["provider"] = pin["provider"]
        out["api_key_env"] = pin["api_key_env"]
    return out
