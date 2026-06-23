from __future__ import annotations

import hashlib
import re
from pathlib import Path


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_./:-]+|[\u4e00-\u9fff]")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sanitize_filename(filename: str) -> str:
    path = Path(filename)
    clean_name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", path.name).strip("._")
    return clean_name or "upload.bin"


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_search_text(text: str) -> str:
    normalized = normalize_text(text)
    tokens = TOKEN_PATTERN.findall(normalized)
    return " ".join(tokens)


def shorten_snippet(text: str, limit: int = 220) -> str:
    value = normalize_text(text)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
