from __future__ import annotations

import re

from app.utils import normalize_text

OCR_ANCHOR_PATTERNS = (
    "Unitree G1",
    "宇树G1",
    "自由度",
    "总自由度",
    "课程",
    "专业",
    "机器人",
    "机械臂",
    "大模型",
    "Jupyter",
    "学院",
    "产业",
    "治理",
    "课程体系",
    "培养",
    "实践",
    "华为",
    "申请",
    "优势",
    "重构",
    "方向",
)

LIST_MARKER_RE = re.compile(r"^(?:\d+[.)、]|[一二三四五六七八九十]+[、.]|[-*•])\s*")
SHORT_FRAGMENT_RE = re.compile(r"^[\u4e00-\u9fff]{1,3}$")


def ocr_line_quality(text: str) -> float:
    normalized = normalize_text(text)
    if not normalized:
        return 0.0
    length = len(normalized)
    chinese_count = sum(1 for char in normalized if "\u4e00" <= char <= "\u9fff")
    ascii_word_count = len(re.findall(r"[A-Za-z]{2,}", normalized))
    digit_count = sum(1 for char in normalized if char.isdigit())
    bad_symbol_count = sum(1 for char in normalized if char in "�■◆◇○●□△▽※¤")
    punctuation_count = sum(1 for char in normalized if char in "，。；：！？、,.!?;:()（）【】[]- ")
    punctuation_ratio = punctuation_count / max(length, 1)
    mixed_token_count = len(re.findall(r"[\u4e00-\u9fff]+\d+|\d+[\u4e00-\u9fff]+", normalized))
    useful_ratio = (chinese_count + ascii_word_count * 2 + digit_count) / max(length, 1)
    noise_ratio = max(0.0, (bad_symbol_count * 2 + max(length - chinese_count - digit_count - punctuation_count, 0) * 0.08) / max(length, 1))
    score = useful_ratio - noise_ratio
    if mixed_token_count >= 2:
        score -= 0.35
    if punctuation_ratio >= 0.2:
        score -= 0.2
    if any(pattern.lower() in normalized.lower() for pattern in OCR_ANCHOR_PATTERNS):
        score += 0.35
    if re.search(r"\d+\s*个", normalized):
        score += 0.2
    if re.fullmatch(r"[A-Za-z0-9 ]{1,6}", normalized):
        score -= 0.4
    return max(0.0, min(score, 1.0))


def clean_ocr_text(text: str) -> tuple[str, float]:
    cleaned_lines: list[str] = []
    line_scores: list[float] = []
    salvage_lines: list[tuple[float, str]] = []
    raw_lines = [line for line in re.split(r"[\r\n]+", text) if normalize_text(line)]
    for raw_line in raw_lines:
        normalized = normalize_text(raw_line)
        if not normalized:
            continue
        normalized = re.sub(r"[|¦]+", " ", normalized)
        normalized = re.sub(r"\s{2,}", " ", normalized)
        score = ocr_line_quality(normalized)
        anchored = any(pattern.lower() in normalized.lower() for pattern in OCR_ANCHOR_PATTERNS)
        if re.search(r"[?？!！]{2,}", normalized) and not anchored:
            score -= 0.25
        if score >= 0.42 or anchored:
            cleaned_lines.append(normalized)
            line_scores.append(max(score, 0.35 if anchored else score))
            continue
        if score >= 0.18 and len(normalized) >= 6:
            salvage_lines.append((score, normalized))
    if not cleaned_lines:
        if not salvage_lines:
            return "", 0.0
        salvage_lines.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        rescued = [line for _, line in salvage_lines[:3]]
        quality = min(0.45, max(0.18, sum(score for score, _ in salvage_lines[:3]) / len(rescued)))
        return "\n".join(rescued), round(quality, 3)
    cleaned_text = "\n".join(cleaned_lines)
    retention_ratio = len(cleaned_lines) / max(len(raw_lines), 1)
    quality = (sum(line_scores) / len(line_scores)) - (1.0 - retention_ratio) * 0.8
    return cleaned_text, round(max(0.0, min(quality, 1.0)), 3)


def _merge_fragmented_parts(parts: list[str]) -> list[str]:
    merged: list[str] = []
    buffer: list[str] = []

    def flush_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        merged.append("".join(buffer))
        buffer = []

    for part in parts:
        normalized = normalize_text(part)
        if not normalized:
            flush_buffer()
            continue
        if SHORT_FRAGMENT_RE.fullmatch(normalized) and not LIST_MARKER_RE.match(normalized):
            candidate = "".join(buffer + [normalized])
            if len(candidate) <= 8:
                buffer.append(normalized)
                continue
        flush_buffer()
        merged.append(normalized)
    flush_buffer()
    return [part for part in merged if part]


def split_visual_text(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    lines = [normalize_text(line) for line in re.split(r"[\r\n]+", normalized) if normalize_text(line)]
    parts: list[str] = []
    buffer: list[str] = []
    for line in lines:
        starts_new = bool(
            LIST_MARKER_RE.match(line)
            or len(line) <= 26
            or line.endswith(("：", ":"))
            or any(token in line for token in ("步骤", "流程", "优势", "方向", "重构", "课程", "申请"))
        )
        if starts_new and buffer:
            parts.append(normalize_text(" ".join(buffer)))
            buffer = [line]
            continue
        if LIST_MARKER_RE.match(line):
            parts.append(line)
            continue
        buffer.append(line)
        current = normalize_text(" ".join(buffer))
        if len(current) >= 100 and re.search(r"[。；;]$", line):
            parts.append(current)
            buffer = []
    if buffer:
        parts.append(normalize_text(" ".join(buffer)))
    return _merge_fragmented_parts([part for part in parts if part])
