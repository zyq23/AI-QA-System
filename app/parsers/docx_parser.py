from __future__ import annotations

from pathlib import Path

import mammoth
from bs4 import BeautifulSoup, Tag

from app.domain import ParsedDocument, SourceBlock
from app.utils import normalize_text


def _table_to_markdown(table: Tag) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        row = [normalize_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if any(row):
            rows.append(row)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    header = padded[0]
    divider = ["---"] * width
    body = padded[1:] or [[""] * width]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(divider) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


class DocxParser:
    parser_name = "mammoth"

    def parse(self, path: Path) -> ParsedDocument:
        with path.open("rb") as handle:
            result = mammoth.convert_to_html(handle)

        soup = BeautifulSoup(result.value, "html.parser")
        root = soup.body or soup
        heading_stack: list[str] = []
        markdown_lines: list[str] = []
        blocks: list[SourceBlock] = []
        title = path.stem

        for node in root.children:
            if not isinstance(node, Tag):
                continue

            tag_name = node.name.lower()
            if tag_name.startswith("h") and len(tag_name) == 2 and tag_name[1].isdigit():
                level = int(tag_name[1])
                text = normalize_text(node.get_text(" ", strip=True))
                if not text:
                    continue
                if title == path.stem:
                    title = text
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(text)
                markdown_lines.append(f"{'#' * level} {text}")
                continue

            section_path = " / ".join(heading_stack) or title
            if tag_name == "table":
                table_md = _table_to_markdown(node)
                if table_md:
                    blocks.append(SourceBlock(page_or_slide="docx", section_path=section_path, content=table_md, kind="table"))
                    markdown_lines.append(table_md)
                continue

            if tag_name in {"ul", "ol"}:
                items = []
                for index, item in enumerate(node.find_all("li", recursive=False), start=1):
                    text = normalize_text(item.get_text(" ", strip=True))
                    if not text:
                        continue
                    prefix = "-" if tag_name == "ul" else f"{index}."
                    items.append(f"{prefix} {text}")
                if items:
                    content = "\n".join(items)
                    blocks.append(SourceBlock(page_or_slide="docx", section_path=section_path, content=content, kind="list"))
                    markdown_lines.append(content)
                continue

            text = normalize_text(node.get_text(" ", strip=True))
            if not text:
                continue
            blocks.append(SourceBlock(page_or_slide="docx", section_path=section_path, content=text, kind="paragraph"))
            markdown_lines.append(text)

        warnings = [message.message for message in result.messages]
        raw_markdown = "\n\n".join(markdown_lines)
        return ParsedDocument(
            title=title,
            blocks=blocks,
            raw_markdown=raw_markdown,
            parser_name=self.parser_name,
            warnings=warnings,
        )
