from __future__ import annotations

import hashlib
import logging
import re
from functools import lru_cache
from pathlib import Path

import jieba

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_./:-]+")
_JIEBA_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

# Quiet the jieba build log on first import.
jieba.setLogLevel(logging.CRITICAL)


@lru_cache(maxsize=1)
def _warm_jieba() -> None:
    for _ in jieba.cut("知识库问答系统初始化"):
        pass


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


def tokenize(text: str) -> list[str]:
    """Tokenize mixed CJK/ASCII text for FTS indexing and query building.

    Chinese runs are segmented with jieba (word-level), ASCII identifiers are
    kept whole. Single-character Chinese fragments are dropped — the previous
    per-character tokenizer produced huge OR queries that matched noise.
    """
    _warm_jieba()
    normalized = normalize_text(text)
    tokens: list[str] = []
    for ascii_token in _TOKEN_PATTERN.findall(normalized):
        tokens.append(ascii_token.lower())
        normalized = normalized.replace(ascii_token, " ")
    for token in jieba.lcut(normalized):
        if _JIEBA_TOKEN_RE.fullmatch(token):
            tokens.append(token)
    return tokens


def build_search_text(text: str) -> str:
    return " ".join(tokenize(text))


def shorten_snippet(text: str, limit: int = 220) -> str:
    value = normalize_text(text)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
