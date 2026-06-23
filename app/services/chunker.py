from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
import re

from app.domain import ChunkRecord, ParsedDocument, SourceBlock
from app.utils import build_search_text, normalize_text, sha256_text


SHORT_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；;])")


def _split_block_for_chunking(block: SourceBlock) -> list[str]:
    content = normalize_text(block.content)
    if not content:
        return []
    if block.kind == "table":
        return [content]
    if block.kind in {"list", "title"}:
        return [content]
    if block.kind == "image_ocr_low_conf":
        parts = [normalize_text(part) for part in re.split(r"[\r\n]+", content) if normalize_text(part)]
        filtered_parts = [
            part
            for part in parts
            if len(part) >= 4 and re.search(r"[\u4e00-\u9fffA-Za-z]{2,}", part)
        ]
        return filtered_parts or ([content] if len(content) >= 8 else [])
    if len(content) <= 220:
        return [content]
    sentences = [normalize_text(part) for part in SHORT_SENTENCE_SPLIT_RE.split(content) if normalize_text(part)]
    if len(sentences) <= 1:
        return [content]
    parts: list[str] = []
    buffer: list[str] = []
    for sentence in sentences:
        candidate = normalize_text("".join(buffer + [sentence]))
        if buffer and len(candidate) > 180:
            parts.append(normalize_text("".join(buffer)))
            buffer = [sentence]
        else:
            buffer.append(sentence)
    if buffer:
        parts.append(normalize_text("".join(buffer)))
    return [part for part in parts if part]


@dataclass(slots=True)
class ChunkingContext:
    document_id: str
    version_id: str
    file_name: str
    source_type: str
    trust_level: str
    target_size: int = 700
    overlap: int = 120


def _flush_chunk(
    chunks: list[ChunkRecord],
    buffer: list[str],
    *,
    context: ChunkingContext,
    page_or_slide: str,
    section_path: str,
    chunk_index: int,
) -> None:
    text = normalize_text("\n\n".join(part for part in buffer if normalize_text(part)))
    if not text:
        return
    chunk_hash = sha256_text(f"{context.version_id}:{chunk_index}:{text}")
    chunks.append(
        ChunkRecord(
            chunk_id=chunk_hash[:32],
            document_id=context.document_id,
            version_id=context.version_id,
            file_name=context.file_name,
            source_type=context.source_type,
            trust_level=context.trust_level,
            page_or_slide=page_or_slide,
            section_path=section_path,
            chunk_index=chunk_index,
            chunk_hash=chunk_hash,
            markdown_text=text,
            plain_text=text,
            search_text=build_search_text(text),
        )
    )


class ChunkerService:
    def __init__(self, target_size: int = 700, overlap: int = 120) -> None:
        self.target_size = target_size
        self.overlap = overlap

    def chunk(self, parsed_document: ParsedDocument, context: ChunkingContext) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        chunk_index = 0

        grouped = groupby(
            parsed_document.blocks,
            key=lambda block: (block.page_or_slide, block.section_path),
        )
        for (page_or_slide, section_path), group in grouped:
            buffer: list[str] = []
            buffer_length = 0
            carryover = ""
            for block in group:
                split_parts = _split_block_for_chunking(block)
                if not split_parts:
                    continue
                if block.kind == "table":
                    if buffer:
                        _flush_chunk(
                            chunks,
                            buffer,
                            context=context,
                            page_or_slide=page_or_slide,
                            section_path=section_path,
                            chunk_index=chunk_index,
                        )
                        chunk_index += 1
                        carryover = normalize_text("".join(buffer))[-self.overlap :]
                        buffer = []
                        buffer_length = 0
                    _flush_chunk(
                        chunks,
                        [split_parts[0]],
                        context=context,
                        page_or_slide=page_or_slide,
                        section_path=section_path,
                        chunk_index=chunk_index,
                    )
                    chunk_index += 1
                    carryover = split_parts[0][-self.overlap :]
                    continue

                for content in split_parts:
                    projected = buffer_length + len(content)
                    if block.kind == "image_ocr_low_conf" and buffer and buffer_length >= max(180, context.target_size // 3):
                        _flush_chunk(
                            chunks,
                            buffer,
                            context=context,
                            page_or_slide=page_or_slide,
                            section_path=section_path,
                            chunk_index=chunk_index,
                        )
                        chunk_index += 1
                        carryover = ""
                        buffer = []
                        buffer_length = 0
                    if projected > context.target_size and buffer:
                        _flush_chunk(
                            chunks,
                            buffer,
                            context=context,
                            page_or_slide=page_or_slide,
                            section_path=section_path,
                            chunk_index=chunk_index,
                        )
                        chunk_index += 1
                        carryover = normalize_text("\n".join(buffer))[-context.overlap :]
                        buffer = [carryover, content] if carryover else [content]
                        buffer_length = len(carryover) + len(content)
                    else:
                        buffer.append(content)
                        buffer_length += len(content)

            if buffer:
                _flush_chunk(
                    chunks,
                    buffer,
                    context=context,
                    page_or_slide=page_or_slide,
                    section_path=section_path,
                    chunk_index=chunk_index,
                )
                chunk_index += 1

        return chunks
