from __future__ import annotations

import hashlib
import logging
import re
from functools import lru_cache
from pathlib import Path

import jieba

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_./:-]+")
_JIEBA_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
# Function/unit single chars: when jieba splits a compound noun these must not be
# glued to the neighbour (网络|年 -> 网络年), but a genuine bound tail (机械|臂)
# or head (根|技术) should merge back into one FTS token (机械臂 / 根技术).
_SINGLE_FUNC_CHARS = frozenset(
    "和与或的了在是对从到以而并被把等及之其于有年月日时分秒个项次条台套页号种家位名篇章步骤"
)

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
    kept whole. Single-character fragments are not simply dropped: a single char
    that directly abuts a segmented word is merged back (机械|臂 -> 机械臂), so
    compound nouns survive tokenization on both the index and the query side.
    Leftover function/unit singles are dropped.
    """
    _warm_jieba()
    normalized = normalize_text(text)
    tokens: list[str] = []
    for ascii_token in _TOKEN_PATTERN.findall(normalized):
        tokens.append(ascii_token.lower())
        normalized = normalized.replace(ascii_token, " ")
    merged: list[str] = []
    prev_end = -1
    for word, start, end in jieba.tokenize(normalized):
        if _TOKEN_PATTERN.fullmatch(word):
            continue  # already collected via the ASCII pass
        if _JIEBA_TOKEN_RE.fullmatch(word):
            if (
                merged
                and start == prev_end
                and len(merged[-1]) == 1
                and merged[-1] not in _SINGLE_FUNC_CHARS
            ):
                # A parked head single char (根|技术 -> 根技术).
                merged[-1] += word
            else:
                merged.append(word)
            prev_end = end
        elif re.fullmatch(r"[\u4e00-\u9fff]", word) and word not in _SINGLE_FUNC_CHARS:
            if merged and start == prev_end and len(merged[-1]) >= 2:
                # A bound tail char (机械|臂 -> 机械臂).
                merged[-1] += word
            else:
                # Park the char; it may merge forward into the next word.
                merged.append(word)
            prev_end = end
        else:
            prev_end = end
    tokens.extend(token for token in merged if len(token) >= 2)
    return tokens


def build_search_text(text: str) -> str:
    return " ".join(tokenize(text))


def shorten_snippet(text: str, limit: int = 220) -> str:
    value = normalize_text(text)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
