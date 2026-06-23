from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.domain import ParsedDocument


class Parser(Protocol):
    parser_name: str

    def parse(self, path: Path) -> ParsedDocument:
        ...
