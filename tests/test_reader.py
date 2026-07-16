"""公告阅读核心逻辑的无网络测试。"""

import json
from pathlib import Path

from ashare_announcements_mcp import reader
from ashare_announcements_mcp.reader import (
    _cache_native_markdown,
    _load_index,
    _native_markdown_pages,
    _page_ranges,
    _query_terms,
)


def test_page_ranges() -> None:
    assert _page_ranges([]) == ""
    assert _page_ranges([1, 2, 4, 6, 7]) == "1-2, 4, 6-7"


def test_query_terms() -> None:
    assert _query_terms("收入 利润") == (["收入", "利润"], False)
    assert _query_terms("收入 AND 利润") == (["收入", "利润"], True)


def test_native_markdown_uses_layout_page_chunks(monkeypatch) -> None:
    calls = []

    class Converter:
        @staticmethod
        def to_markdown(path, **kwargs):
            calls.append((path, kwargs))
            return [
                {"metadata": {"page_number": 2}, "text": "# 第二页\n\n正文"},
                {"metadata": {"page_number": 4}, "text": "# 第四页\n\n表格"},
            ]

    monkeypatch.setattr(reader, "_PYMUPDF4LLM", Converter())
    result = _native_markdown_pages(Path("sample.pdf"), [2, 4])

    assert result == {2: "# 第二页\n\n正文", 4: "# 第四页\n\n表格"}
    _, kwargs = calls[0]
    assert kwargs["pages"] == [1, 3]
    assert kwargs["page_chunks"] is True
    assert kwargs["header"] is False
    assert kwargs["footer"] is False
    assert kwargs["use_ocr"] is False


def test_cache_native_markdown_skips_scanned_pages(tmp_path, monkeypatch) -> None:
    index = {
        "pages": [
            {"needs_ocr": False},
            {"needs_ocr": True},
            {"needs_ocr": False, "markdown_attempted": True},
        ]
    }
    monkeypatch.setattr(
        reader,
        "_native_markdown_pages",
        lambda _path, pages: {page: f"page {page}" for page in pages},
    )
    index_path = tmp_path / "index.json"

    _cache_native_markdown(
        Path("sample.pdf"),
        index_path,
        index,
        [1, 2, 3],
    )

    assert index["pages"][0]["markdown"] == "page 1"
    assert index["pages"][0]["markdown_attempted"] is True
    assert "markdown" not in index["pages"][1]
    assert "markdown" not in index["pages"][2]


def test_index_upgrade_preserves_ocr_but_discards_old_markdown(
    tmp_path,
    monkeypatch,
) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    stat = pdf_path.stat()
    index_path = tmp_path / "sample.json"
    index_path.write_text(
        json.dumps(
            {
                "version": 3,
                "source_size": stat.st_size,
                "source_mtime_ns": stat.st_mtime_ns,
                "pages": [
                    {
                        "ocr_text": "已缓存 OCR",
                        "ocr_attempted": True,
                        "markdown": "旧版 Markdown",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(reader, "_index_path", lambda _code, _path: index_path)
    monkeypatch.setattr(
        reader,
        "_build_index",
        lambda _path: {
            "version": reader.INDEX_VERSION,
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "pages": [{"needs_ocr": True}],
        },
    )

    _, index = _load_index("000001", pdf_path)

    assert index["pages"][0]["ocr_text"] == "已缓存 OCR"
    assert index["pages"][0]["ocr_attempted"] is True
    assert "markdown" not in index["pages"][0]
