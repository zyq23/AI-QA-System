from __future__ import annotations

from pathlib import Path
from io import BytesIO
import re

import fitz
import numpy as np
from PIL import Image

from app.domain import ParsedDocument, SourceBlock
from app.parsers.ocr_utils import LIST_MARKER_RE, clean_ocr_text, split_visual_text
from app.utils import normalize_text

TABLE_ROW_SPLIT_RE = re.compile(r"\s{3,}|\t+|[|｜]")


def _looks_like_table(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    if normalized.count("|") >= 2 or normalized.count("｜") >= 2:
        return True
    lines = [line for line in normalized.splitlines() if line.strip()]
    if len(lines) < 2:
        tokens = [token for token in normalized.split(" ") if token]
        if len(tokens) >= 3 and sum(1 for token in tokens if len(token) <= 6) >= 3:
            return True
        return False
    row_like = 0
    for line in lines[:6]:
        split_cells = [cell for cell in TABLE_ROW_SPLIT_RE.split(line) if cell.strip()]
        if len(split_cells) >= 3:
            row_like += 1
            continue
        space_cells = [cell for cell in line.split(" ") if cell.strip()]
        if len(space_cells) >= 3 and sum(1 for cell in space_cells if len(cell) <= 8) >= 3:
            row_like += 1
    return row_like >= 2


def _split_paragraph_units(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    lines = [normalize_text(line) for line in re.split(r"[\r\n]+", normalized) if normalize_text(line)]
    if not lines:
        return []
    units: list[str] = []
    current: list[str] = []
    for line in lines:
        if LIST_MARKER_RE.match(line):
            if current:
                units.append(normalize_text(" ".join(current)))
                current = []
            units.append(line)
            continue
        if len(line) <= 28 and any(token in line for token in ("步骤", "流程", "申请", "优势", "方向", "重构", "课程", "体系")):
            if current:
                units.append(normalize_text(" ".join(current)))
                current = []
            units.append(line)
            continue
        current.append(line)
        current_text = normalize_text(" ".join(current))
        if len(current_text) >= 120 and re.search(r"[。；;:：]$", line):
            units.append(current_text)
            current = []
    if current:
        units.append(normalize_text(" ".join(current)))
    return [unit for unit in units if unit]


def _merge_ocr_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = normalize_text(line)
        if not stripped:
            if current:
                merged.append(normalize_text(" ".join(current)))
                current = []
            continue
        starts_new = bool(
            LIST_MARKER_RE.match(stripped)
            or len(stripped) <= 20
            or stripped.endswith(("：", ":"))
            or any(token in stripped for token in ("步骤", "流程", "优势", "方向", "重构", "课程", "申请"))
        )
        if starts_new and current:
            merged.append(normalize_text(" ".join(current)))
            current = [stripped]
            continue
        current.append(stripped)
        current_text = normalize_text(" ".join(current))
        if len(current_text) >= 90 and re.search(r"[。；;]$", stripped):
            merged.append(current_text)
            current = []
    if current:
        merged.append(normalize_text(" ".join(current)))
    return [item for item in merged if item]


def _extract_page_image_texts(page: fitz.Page, ocr: PaddleOcrAdapter) -> list[tuple[str, float]]:
    image_blocks: list[tuple[str, float]] = []
    seen_xrefs: set[int] = set()
    for image_info in page.get_images(full=True):
        if not image_info:
            continue
        xref = int(image_info[0])
        if xref in seen_xrefs:
            continue
        seen_xrefs.add(xref)
        try:
            extracted = page.parent.extract_image(xref)
        except Exception:
            continue
        raw = extracted.get("image") if isinstance(extracted, dict) else None
        if not raw:
            continue
        raw_ocr_text = ocr.extract_image_text(raw)
        cleaned_text, quality_score = clean_ocr_text(raw_ocr_text)
        if cleaned_text:
            image_blocks.append((cleaned_text, quality_score))
    return image_blocks


class PaddleOcrAdapter:
    def __init__(self, language: str = "ch") -> None:
        self.language = language
        self._ocr = None
        self._rapid_ocr = None
        self.available = True

    def _load(self):
        if self._ocr is not None:
            return self._ocr
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # pragma: no cover - optional dependency
            self.available = False
            raise RuntimeError("PaddleOCR is not installed.") from exc

        try:
            self._ocr = PaddleOCR(use_angle_cls=True, lang=self.language, show_log=False)
        except Exception as exc:
            if "show_log" not in str(exc):
                raise
            # PaddleOCR 3.x removed `show_log`; keep compatibility with both APIs.
            self._ocr = PaddleOCR(use_angle_cls=True, lang=self.language)
        return self._ocr

    def _load_rapid(self):
        if self._rapid_ocr is not None:
            return self._rapid_ocr
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("RapidOCR is not installed.") from exc
        self._rapid_ocr = RapidOCR()
        return self._rapid_ocr

    def extract_page_text(self, page: fitz.Page) -> str:
        pixmap = page.get_pixmap(dpi=160)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
        if pixmap.n == 4:
            image = image[:, :, :3]
        return self.extract_array_text(image)

    def extract_array_text(self, image: np.ndarray) -> str:
        try:
            ocr = self._load()
            try:
                result = ocr.ocr(image, cls=True)
            except Exception as exc:
                if "unexpected keyword argument 'cls'" not in str(exc):
                    raise
                result = ocr.ocr(image)
            return self._parse_paddle_result(result)
        except Exception as exc:
            rapid_ocr = self._load_rapid()
            result, _ = rapid_ocr(image)
            return self._parse_rapid_result(result, fallback_error=exc)

    @staticmethod
    def _parse_paddle_result(result) -> str:
        lines: list[str] = []
        for region in result or []:
            if isinstance(region, dict):
                texts = region.get("rec_texts") or []
                for value in texts:
                    text = normalize_text(str(value))
                    if text:
                        lines.append(text)
                continue
            for item in region or []:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                text = normalize_text(item[1][0])
                if text:
                    lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def _parse_rapid_result(result, fallback_error: Exception | None = None) -> str:
        lines: list[str] = []
        for item in result or []:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            text = normalize_text(str(item[1]))
            if text:
                lines.append(text)
        if lines:
            return "\n".join(lines)
        if fallback_error is not None:
            raise fallback_error
        return ""

    @staticmethod
    def _is_meaningful_text(text: str) -> bool:
        normalized = normalize_text(text)
        if len(normalized) < 4:
            return False
        chinese_count = sum(1 for char in normalized if "\u4e00" <= char <= "\u9fff")
        ascii_count = sum(1 for char in normalized if char.isascii() and char.isalpha())
        digit_count = sum(1 for char in normalized if char.isdigit())
        return chinese_count >= 2 or ascii_count >= 6 or (chinese_count + ascii_count + digit_count) >= 10

    def extract_image_text(self, raw: bytes) -> str:
        image = Image.open(BytesIO(raw))
        rgb = image.convert("RGB")
        rgb_array = np.array(rgb)

        from app.parsers.ocr_utils import clean_ocr_text

        def _ocr_and_score(engine: str) -> tuple[str, float]:
            try:
                if engine == "rapid":
                    rapid_ocr = self._load_rapid()
                    rapid_result, _ = rapid_ocr(rgb_array)
                    text = self._parse_rapid_result(rapid_result)
                else:
                    text = self.extract_array_text(rgb_array)
                if not text or not self._is_meaningful_text(text):
                    return "", 0.0
                cleaned, quality = clean_ocr_text(text)
                return cleaned, quality
            except Exception:
                return "", 0.0

        # Try both engines, pick the one with better quality
        rapid_text, rapid_score = _ocr_and_score("rapid")
        paddle_text, paddle_score = _ocr_and_score("paddle")

        if rapid_score >= paddle_score and rapid_text:
            return rapid_text
        if paddle_text:
            return paddle_text
        return rapid_text or ""


class PdfParser:
    parser_name = "pymupdf"

    def __init__(self, enable_ocr_fallback: bool = True, ocr_language: str = "ch") -> None:
        self.enable_ocr_fallback = enable_ocr_fallback
        self.ocr = PaddleOcrAdapter(language=ocr_language) if enable_ocr_fallback else None

    def parse(self, path: Path) -> ParsedDocument:
        document = fitz.open(path)
        blocks: list[SourceBlock] = []
        markdown_lines: list[str] = []
        warnings: list[str] = []
        ocr_used = False

        for page_index, page in enumerate(document, start=1):
            text_blocks = page.get_text("blocks")
            sorted_blocks = sorted(text_blocks, key=lambda item: (item[1], item[0]))
            page_text_parts: list[str] = []
            page_blocks: list[SourceBlock] = []
            page_or_slide = f"page-{page_index}"
            section_path = f"第 {page_index} 页"
            block_counter = 0
            text = ""
            usable_block_count = 0
            for raw_block in sorted_blocks:
                content = normalize_text(raw_block[4])
                if not content:
                    continue
                usable_block_count += 1
                page_text_parts.append(content)
                block_counter += 1
                block_label = f"{section_path} / 区块 {block_counter}"
                if _looks_like_table(content):
                    page_blocks.append(
                        SourceBlock(
                            page_or_slide=page_or_slide,
                            section_path=block_label,
                            content=content,
                            kind="table",
                        )
                    )
                    continue
                split_units = _split_paragraph_units(content)
                if len(split_units) > 1:
                    for part_index, unit in enumerate(split_units, start=1):
                        page_blocks.append(
                            SourceBlock(
                                page_or_slide=page_or_slide,
                                section_path=f"{block_label} / 文本 {part_index}",
                                content=unit,
                                kind="list" if LIST_MARKER_RE.match(unit) else "paragraph",
                            )
                        )
                    continue
                page_blocks.append(
                    SourceBlock(
                        page_or_slide=page_or_slide,
                        section_path=block_label,
                        content=content,
                        kind="paragraph",
                    )
                )
            text = "\n\n".join(page_text_parts)
            # Trigger full-page OCR when text density is low:
            # 1. Total text is below absolute minimum
            # 2. Average chars per text block is low (page likely image-heavy)
            # 3. Total chars across many blocks but each block is tiny (scattered text)
            avg_chars_per_block = len(text) / max(1, usable_block_count)
            should_ocr_fallback = (
                self.enable_ocr_fallback
                and self.ocr
                and (
                    len(text) < 80
                    or avg_chars_per_block < 28
                    or (usable_block_count >= 3 and len(text) < max(80, usable_block_count * 40))
                )
            )
            if should_ocr_fallback:
                try:
                    ocr_text = normalize_text(self.ocr.extract_page_text(page))
                    if len(ocr_text) > len(text):
                        text = ocr_text
                        ocr_used = True
                        ocr_lines = [line for line in re.split(r"[\r\n]+", ocr_text) if normalize_text(line)]
                        page_blocks = []
                        for line_index, line in enumerate(_merge_ocr_lines(ocr_lines), start=1):
                            page_blocks.append(
                                SourceBlock(
                                    page_or_slide=page_or_slide,
                                    section_path=f"{section_path} / OCR {line_index}",
                                    content=line,
                                    kind="image_ocr_low_conf",
                                    quality_score=0.5,
                                )
                            )
                except Exception as exc:  # pragma: no cover - optional dependency
                    warnings.append(f"第 {page_index} 页 OCR 回退失败: {exc}")
            if self.enable_ocr_fallback and self.ocr:
                try:
                    image_texts = _extract_page_image_texts(page, self.ocr)
                    for image_index, (image_text, quality_score) in enumerate(image_texts, start=1):
                        block_kind = "image_ocr" if quality_score >= 0.8 else "image_ocr_low_conf"
                        for part_index, part in enumerate(split_visual_text(image_text) or [image_text], start=1):
                            page_blocks.append(
                                SourceBlock(
                                    page_or_slide=page_or_slide,
                                    section_path=f"{section_path} / 图片 OCR {image_index}-{part_index}",
                                    content=part,
                                    kind=block_kind,
                                    quality_score=quality_score,
                                )
                            )
                            page_text_parts.append(part)
                    if image_texts:
                        ocr_used = True
                        text = "\n\n".join(page_text_parts)
                except Exception as exc:  # pragma: no cover - optional dependency
                    warnings.append(f"第 {page_index} 页图片 OCR 失败: {exc}")

            if not text:
                continue

            markdown_lines.append(f"## {section_path}")
            if not page_blocks:
                fallback_parts = [normalize_text(part) for part in text.split("\n\n") if normalize_text(part)]
                page_blocks = [
                    SourceBlock(page_or_slide=page_or_slide, section_path=section_path, content=paragraph)
                    for paragraph in fallback_parts
                ]
            for block in page_blocks:
                blocks.append(block)
                markdown_lines.append(block.content)

        return ParsedDocument(
            title=document.metadata.get("title") or path.stem,
            blocks=blocks,
            raw_markdown="\n\n".join(markdown_lines),
            parser_name=self.parser_name,
            ocr_used=ocr_used,
            warnings=warnings,
        )
