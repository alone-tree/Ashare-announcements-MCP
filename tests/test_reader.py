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


def _fake_index(native_chars: list[int], needs_ocr: list[bool]) -> dict:
    return {
        "version": reader.INDEX_VERSION,
        "source_size": 100,
        "source_mtime_ns": 1,
        "toc": [],
        "pages": [
            {
                "page": i + 1,
                "native_text": "正文" * max(native_chars[i] // 2, 1),
                "native_chars": native_chars[i],
                "image_count": 0,
                "needs_ocr": needs_ocr[i],
                "heading": f"标题{i + 1}",
            }
            for i in range(len(native_chars))
        ],
    }


def _patch_read(monkeypatch, index: dict) -> None:
    monkeypatch.setattr(
        reader,
        "_load_index",
        lambda _code, _path: (Path("index.json"), index),
    )
    monkeypatch.setattr(reader, "_cache_native_markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(reader, "_ocr_pages", lambda _path, pages: {p: "" for p in pages})
    monkeypatch.setattr(reader, "_ensure_page_text", lambda *a, **k: ("第 N 页正文", "native_markdown", False))


def test_read_detect_mode_short_returns_full_text(monkeypatch) -> None:
    index = _fake_index(native_chars=[100] * 3, needs_ocr=[False] * 3)
    _patch_read(monkeypatch, index)

    result = reader.read_pdf(Path("sample.pdf"), "000001")

    assert result["profile"] == "short"
    assert result["pages_returned"] == [1, 2, 3]
    assert result["next_page"] is None
    assert result["is_last_chunk"] is True
    assert result["recommended_workflow"] == "公告较短，已直接返回全文。"


def test_read_detect_mode_long_returns_profile_and_three_pages(monkeypatch) -> None:
    index = _fake_index(native_chars=[200] * 141, needs_ocr=[False] * 141)
    _patch_read(monkeypatch, index)

    result = reader.read_pdf(Path("sample.pdf"), "000001")

    assert result["profile"] == "long_structured"
    assert result["total_pages"] == 141
    assert result["pages_returned"] == [1, 2, 3]
    assert result["next_page"] == 4
    assert "共 141 页" in result["recommended_workflow"]
    assert result["scanned_page_count"] == 0
    assert result["native_text_chars"] == 200 * 141


def test_read_detect_mode_long_mixed_scan(monkeypatch) -> None:
    index = _fake_index(
        native_chars=[200] * 20,
        needs_ocr=[False] * 20,
    )
    for page in index["pages"][8:12]:
        page["needs_ocr"] = True
    _patch_read(monkeypatch, index)

    result = reader.read_pdf(Path("sample.pdf"), "000001")

    assert result["profile"] == "long_mixed_scan"
    assert result["scanned_pages"] == "9-12"
    assert "扫描页" in result["recommended_workflow"]


def test_read_detect_mode_still_respects_explicit_start_page(monkeypatch) -> None:
    index = _fake_index(native_chars=[200] * 141, needs_ocr=[False] * 141)
    _patch_read(monkeypatch, index)

    result = reader.read_pdf(Path("sample.pdf"), "000001", start_page=50, end_page=52)

    assert result["pages_returned"] == [50, 51, 52]
    assert result["profile"] == "long_structured"
    assert "recommended_workflow" not in result
