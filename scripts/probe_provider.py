#!/usr/bin/env python3
"""Probe an OpenAI-compatible LLM without exposing credentials.

The probe records endpoint host, model, latency, completion success, and JSON
response-format compatibility. It never prints the API key or response body.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openai import OpenAI

from app.config import Settings


@dataclass
class ProbeResult:
    generated_at: str
    provider: str
    endpoint_host: str | None
    model: str | None
    completion_ok: bool
    json_object_ok: bool | None
    latency_ms: int | None
    error_type: str | None
    error_message: str | None


def _safe_error(exc: Exception, api_key: str | None = None) -> tuple[str, str]:
    message = str(exc).replace("\n", " ").strip()
    # Avoid accidentally persisting authorization material from a provider error.
    for token in (api_key, os.getenv("LLM_API_KEY")):
        if token:
            message = message.replace(token, "[redacted]")
    return type(exc).__name__, message[:300]


def _host(base_url: str | None) -> str | None:
    if not base_url:
        return None
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        return None
    try:
        return socket.getfqdn(host) if host not in {"127.0.0.1", "localhost"} else host
    except Exception:
        return host


def _settings(**overrides: str | None) -> Settings:
    """Load repo .env the same way the app does, letting explicit overrides win.

    A raw Settings() would resolve .env relative to the caller's cwd, so the probe
    pins it to the repository root and keeps environment variables authoritative.
    """
    settings = Settings(_env_file=ROOT / ".env")
    for field, value in overrides.items():
        if value:
            setattr(settings, field, value)
    return settings


def probe(*, base_url: str | None, api_key: str | None, model: str | None, provider: str) -> dict:
    result = ProbeResult(
        generated_at=datetime.now(timezone.utc).isoformat(),
        provider=provider,
        endpoint_host=_host(base_url),
        model=model,
        completion_ok=False,
        json_object_ok=None,
        latency_ms=None,
        error_type=None,
        error_message=None,
    )
    if not (base_url and api_key and model):
        result.error_type = "ConfigurationError"
        result.error_message = "base_url, api_key, and model are required"
        return asdict(result)

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=30.0, max_retries=0)
    messages = [{"role": "user", "content": "Return JSON with exactly one key: ok, whose value is true."}]
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=32,
        )
        result.completion_ok = bool(response.choices and response.choices[0].message.content)
        result.latency_ms = round((time.perf_counter() - started) * 1000)
    except Exception as exc:
        result.latency_ms = round((time.perf_counter() - started) * 1000)
        result.error_type, result.error_message = _safe_error(exc, api_key)
        return asdict(result)

    try:
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=32,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content if response.choices else ""
        json.loads(content or "")
        result.json_object_ok = True
    except Exception as exc:
        result.json_object_ok = False
        result.error_type, result.error_message = _safe_error(exc, api_key)
    return asdict(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe an OpenAI-compatible provider without printing secrets")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--provider", default=None)
    args = parser.parse_args()
    settings = _settings(
        llm_base_url=args.base_url,
        llm_model=args.model,
        llm_provider=args.provider,
    )
    payload = probe(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        provider=settings.llm_provider,
    )
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if payload["completion_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
