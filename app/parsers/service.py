from __future__ import annotations

from pathlib import Path

from app.domain import ParsedDocument
from app.parsers.docx_parser import DocxParser
from app.parsers.pdf_parser import PdfParser
from app.parsers.pptx_parser import PptxParser


class DocumentParserService:
    def __init__(self, enable_ocr_fallback: bool = True, ocr_language: str = "ch") -> None:
        self.docx_parser = DocxParser()
        self.pptx_parser = PptxParser(enable_ocr_fallback=enable_ocr_fallback, ocr_language=ocr_language)
        self.pdf_parser = PdfParser(enable_ocr_fallback=enable_ocr_fallback, ocr_language=ocr_language)

    def parse(self, path: Path) -> ParsedDocument:
        suffix = path.suffix.lower()
        if suffix == ".docx":
            return self.docx_parser.parse(path)
        if suffix == ".pptx":
            return self.pptx_parser.parse(path)
        if suffix == ".pdf":
            return self.pdf_parser.parse(path)
        raise ValueError(f"Unsupported file type: {path.suffix}")
