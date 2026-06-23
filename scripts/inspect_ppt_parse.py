from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from app.domain import ParsedDocument, SourceBlock
from app.parsers.pptx_parser import _is_placeholder_text
from app.parsers.service import DocumentParserService
from app.services.chunker import ChunkerService, ChunkingContext
from app.utils import normalize_text


LOW_QUALITY_SHORT_LINE_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")
DEFAULT_KEY_SLIDES = [21, 33, 48, 70, 74, 79, 80, 89, 90]


@dataclass(slots=True)
class SlideSummary:
    slide: str
    block_count: int
    image_ocr_count: int
    image_ocr_low_conf_count: int
    warning_count: int
    placeholder_hits: int
    low_quality_short_noise_hits: int
    chunk_count: int
    first_text_preview: str


@dataclass(slots=True)
class FocusSlideDetail:
    slide: str
    summary: SlideSummary
    block_previews: list[dict[str, object]]
    chunk_previews: list[str]


def _looks_like_low_quality_short_noise(block: SourceBlock) -> bool:
    if block.kind != "image_ocr_low_conf":
        return False
    parts = [normalize_text(part) for part in re.split(r"[\r\n]+", block.content) if normalize_text(part)]
    noisy_parts = [part for part in parts if LOW_QUALITY_SHORT_LINE_RE.fullmatch(part)]
    return bool(noisy_parts)


def _preview(text: str, limit: int = 80) -> str:
    normalized = normalize_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def build_slide_summaries(parsed: ParsedDocument, chunks_by_slide: dict[str, int]) -> list[SlideSummary]:
    warnings_by_slide: Counter[str] = Counter()
    for warning in parsed.warnings:
        match = re.search(r"第\s*(\d+)\s*页", warning)
        if match:
            warnings_by_slide[f"slide-{int(match.group(1))}"] += 1

    blocks_by_slide: dict[str, list[SourceBlock]] = defaultdict(list)
    for block in parsed.blocks:
        blocks_by_slide[block.page_or_slide].append(block)

    slide_summaries: list[SlideSummary] = []
    for slide_name, blocks in sorted(blocks_by_slide.items(), key=lambda item: int(item[0].split("-")[-1])):
        first_text = next((block.content for block in blocks if normalize_text(block.content)), "")
        slide_summaries.append(
            SlideSummary(
                slide=slide_name,
                block_count=len(blocks),
                image_ocr_count=sum(1 for block in blocks if block.kind == "image_ocr"),
                image_ocr_low_conf_count=sum(1 for block in blocks if block.kind == "image_ocr_low_conf"),
                warning_count=warnings_by_slide.get(slide_name, 0),
                placeholder_hits=sum(1 for block in blocks if _is_placeholder_text(block.content)),
                low_quality_short_noise_hits=sum(1 for block in blocks if _looks_like_low_quality_short_noise(block)),
                chunk_count=chunks_by_slide.get(slide_name, 0),
                first_text_preview=_preview(first_text),
            )
        )
    return slide_summaries


def inspect_ppt(
    path: Path,
    *,
    enable_ocr_fallback: bool,
    target_size: int,
    overlap: int,
    focus_slides: set[str] | None = None,
) -> dict[str, object]:
    parser = DocumentParserService(enable_ocr_fallback=enable_ocr_fallback)
    parsed = parser.parse(path)
    chunker = ChunkerService(target_size=target_size, overlap=overlap)
    chunks = chunker.chunk(
        parsed,
        ChunkingContext(
            document_id="parse-only",
            version_id=f"parse-only:{path.name}:{'ocr' if enable_ocr_fallback else 'no-ocr'}",
            file_name=path.name,
            source_type="parse-only",
            trust_level="internal",
            target_size=target_size,
            overlap=overlap,
        ),
    )
    chunks_by_slide: Counter[str] = Counter(chunk.page_or_slide for chunk in chunks)
    slide_summaries = build_slide_summaries(parsed, dict(chunks_by_slide))
    summary_map = {summary.slide: summary for summary in slide_summaries}
    focus_slide_details: list[dict[str, object]] = []
    if focus_slides:
        blocks_by_slide: dict[str, list[SourceBlock]] = defaultdict(list)
        for block in parsed.blocks:
            blocks_by_slide[block.page_or_slide].append(block)
        chunk_text_by_slide: dict[str, list[str]] = defaultdict(list)
        for chunk in chunks:
            chunk_text_by_slide[chunk.page_or_slide].append(chunk.plain_text)
        for slide in sorted(focus_slides, key=lambda item: int(item.split("-")[-1])):
            summary = summary_map.get(slide)
            if not summary:
                continue
            detail = FocusSlideDetail(
                slide=slide,
                summary=summary,
                block_previews=[
                    {
                        "kind": block.kind,
                        "quality_score": round(block.quality_score, 3),
                        "content_preview": _preview(block.content, limit=120),
                    }
                    for block in blocks_by_slide.get(slide, [])[:12]
                ],
                chunk_previews=[_preview(text, limit=140) for text in chunk_text_by_slide.get(slide, [])[:6]],
            )
            focus_slide_details.append(
                {
                    "slide": detail.slide,
                    "summary": asdict(detail.summary),
                    "block_previews": detail.block_previews,
                    "chunk_previews": detail.chunk_previews,
                }
            )
    return {
        "file": str(path),
        "title": parsed.title,
        "parser_name": parsed.parser_name,
        "enable_ocr_fallback": enable_ocr_fallback,
        "ocr_used": parsed.ocr_used,
        "warning_count": len(parsed.warnings),
        "warnings": parsed.warnings,
        "slide_count": len({block.page_or_slide for block in parsed.blocks}),
        "block_count": len(parsed.blocks),
        "chunk_count": len(chunks),
        "slides": [asdict(summary) for summary in slide_summaries],
        "focus_slide_details": focus_slide_details,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect one PPTX in parse-only mode without ingestion.")
    parser.add_argument("path", type=Path, help="Target .pptx file path")
    parser.add_argument("--enable-ocr-fallback", action="store_true", help="Enable OCR fallback during parse-only inspection")
    parser.add_argument("--target-size", type=int, default=700)
    parser.add_argument("--overlap", type=int, default=120)
    parser.add_argument("--slides", default="", help="Comma-separated slide numbers to print in detail")
    parser.add_argument("--json-out", type=Path, default=None, help="Optional JSON output path")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    detailed_slides = {
        f"slide-{int(item)}"
        for item in (args.slides.split(",") if args.slides else [])
        if item.strip()
    } or {f"slide-{num}" for num in DEFAULT_KEY_SLIDES}
    result = inspect_ppt(
        args.path,
        enable_ocr_fallback=args.enable_ocr_fallback,
        target_size=args.target_size,
        overlap=args.overlap,
        focus_slides=detailed_slides,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
