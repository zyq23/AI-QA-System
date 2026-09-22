"""Log sanitization utilities for production observability.

This module provides PII redaction and credential masking for structured logging.
Patterns match common secrets (tokens, keys, passwords, email addresses, phone numbers)
and replace them with a safe placeholder.  The sanitizer is intentionally conservative
— it never throws, only transforms strings passed to the logger.

Production note: The global ``sanitize()`` helper should be called on any user-provided
or request-scoped data before logging.  For performance, the compiled regexes are cached
at module import time.  A ``SanitizeLogFilter`` is also provided to auto-sanitize all
log records at emit time (added to the root logger in ``app.main.setup_logging``).
"""
from __future__ import annotations

import logging
import re


_PATTERNS = [
    # Authorization headers (Bearer tokens, Basic creds)
    (re.compile(r"(Authorization:\s*)(Bearer\s+[A-Za-z0-9\-_.+=]+)", re.I), r"\1[BEARER_TOKEN_REDACTED]"),
    (re.compile(r"(Authorization:\s*)(Basic\s+[A-Za-z0-9+/=]+)", re.I), r"\1[BASIC_CRED_REDACTED]"),
    # API keys & tokens
    (re.compile(r"api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9]{16,}['\"]?", re.I), "[API_KEY_REDACTED]"),
    (re.compile(r"token\s*[=:]\s*['\"]?[A-Za-z0-9\-_.+=]{16,}['\"]?", re.I), "[TOKEN_REDACTED]"),
    (re.compile(r"secret[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9]{16,}['\"]?", re.I), "[SECRET_REDACTED]"),
    (re.compile(r"password\s*[=:]\s*['\"]?[^\s'\"]{8,}['\"]?", re.I), "[PASSWORD_REDACTED]"),
    # Email addresses
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}"), "[EMAIL_REDACTED]"),
    # Phone numbers (simple patterns, may catch false positives)
    (re.compile(r"\b(?:\+?86[-.]?)?1[3-9]\d{9}\b"), "[PHONE_REDACTED]"),
    # OAuth/OIDC IDs and session cookies
    (re.compile(r"(session[_-]?id|sid)\s*[=:]\s*['\"]?[A-Za-z0-9\-_]{16,}['\"]?", re.I), r"\1=[SESSION_ID_REDACTED]"),
    # Hex-encoded secrets (JWT payloads, hex tokens)
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "[HEX_SECRET_REDACTED]"),
]


def sanitize(value: str) -> str:
    """Return a sanitized copy of ``value`` with credentials and PII replaced.

    If ``value`` is empty or already safe, it is returned unchanged.  Multiple
    patterns may match the same string; they are applied sequentially.

    Production note: This function never raises.  Regex failures fall back to
    returning the original input so logging always succeeds.
    """
    if not value:
        return value
    result = value
    try:
        for pattern, replacement in _PATTERNS:
            result = pattern.sub(replacement, result)
    except Exception:
        # Never let sanitization break logging
        return value
    return result


def sanitize_dict(d: dict) -> dict:
    """Recursively sanitize string values in a dictionary."""
    result: dict = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = sanitize_dict(v)
        elif isinstance(v, str):
            result[k] = sanitize(v)
        else:
            result[k] = v
    return result


class SanitizeLogFilter(logging.Filter):
    """Auto-sanitize all log records: message + any str args + exception text."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize(str(record.msg))
        if record.args:
            try:
                record.args = tuple(
                    sanitize(str(a)) if isinstance(a, str) else a for a in record.args
                )
            except Exception:
                pass
        if record.exc_info and record.exc_text:
            record.exc_text = sanitize(record.exc_text)
        return True
