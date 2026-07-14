"""PDF 文本提取。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pdfplumber


def read_pdf(
    path: Path,
    max_chars: int,
    start_page: int = 0,
    start_char: int = 0,
) -> dict[str, Any]:
    """从指定页和页内字符开始提取，达到字符上限后停止。"""
    texts: list[str] = []
    chars = 0
    pages_read = 0
    with pdfplumber.open(path) as pdf:
        total_pages = len(pdf.pages)
        if start_page < 0 or start_page >= total_pages:
            raise ValueError(f"start_page 必须在 0 到 {max(total_pages - 1, 0)} 之间")
        if start_char < 0:
            raise ValueError("start_char 不能小于 0")
        next_page: int | None = None
        next_char = 0
        for page_index, page in enumerate(pdf.pages[start_page:], start=start_page):
            full_text = page.extract_text() or ""
            page_offset = start_char if page_index == start_page else 0
            text = full_text[page_offset:]
            separator = "\n\n" if texts else ""
            remaining = max_chars - chars - len(separator)
            if remaining <= 0:
                break
            texts.append(separator + text[:remaining])
            chars += len(separator) + min(len(text), remaining)
            pages_read += 1
            if len(text) > remaining:
                next_page = page_index
                next_char = page_offset + remaining
                break
            if chars >= max_chars:
                next_page = page_index + 1 if page_index + 1 < total_pages else None
                break
        else:
            next_page = None
    return {
        "text": "".join(texts),
        "total_pages": total_pages,
        "start_page": start_page,
        "pages_read": pages_read,
        "next_page": next_page,
        "next_char": next_char,
        "chars_returned": chars,
        "is_last_chunk": next_page is None,
    }
