"""本地公司（LOCAL- 前缀）档案的无网络测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ashare_announcements_mcp import service


def _local_registry() -> dict[str, Any]:
    return {
        "companies": {
            "LOCAL-YXG": {
                "local": True,
                "name": "大连优欣光",
                "securities": [
                    {
                        "code": "LOCAL-YXG",
                        "market": "LOCAL",
                        "name": "大连优欣光",
                        "classify": "LOCAL",
                        "inner_code": "",
                    }
                ],
            }
        },
        "aliases": {"LOCAL-YXG": "LOCAL-YXG", "大连优欣光": "LOCAL-YXG"},
    }


def _local_items() -> list[dict[str, Any]]:
    return [
        {
            "code": "a.pdf",
            "url": "D:/cache/LOCAL-YXG/pdfs/a.pdf",
            "title": "招股说明书（注册稿）",
            "display_time": "2022-04-06 00:00:00",
            "column_name": "本地材料",
            "short_name": "大连优欣光",
        },
        {
            "code": "b.pdf",
            "url": "D:/cache/LOCAL-YXG/pdfs/b.pdf",
            "title": "审核问询函的回复",
            "display_time": "2021-08-15 00:00:00",
            "column_name": "本地材料",
            "short_name": "大连优欣光",
        },
    ]


def test_normalize_stock_code_accepts_local_code() -> None:
    assert service.normalize_stock_code("LOCAL-YXG") == "LOCAL-YXG"
    assert service.normalize_stock_code("local-yxg") == "LOCAL-YXG"


def test_query_archive_local_skips_network_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "load_companies", _local_registry)
    monkeypatch.setattr(service, "load_cache", lambda _code: {"items": _local_items(), "meta": {"cache_complete": True}})

    # 若误走网络同步会因缺 ann_type 参数报错，本地路径不应触发
    result = service.query_archive("LOCAL-YXG", start_date="2022-01-01", keyword="注册")

    assert result["total_announcements"] == 2
    assert result["matched"] == 1
    assert result["results"][0]["title"] == "招股说明书（注册稿）"
    assert result["securities"][0]["update"]["success"] is True
    assert result["securities"][0]["update"]["new"] == 0


def test_query_archive_local_supports_date_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "load_companies", _local_registry)
    monkeypatch.setattr(service, "load_cache", lambda _code: {"items": _local_items(), "meta": {"cache_complete": True}})

    result = service.query_archive("LOCAL-YXG", start_date="2022-01-01", end_date="2022-12-31")

    assert result["matched"] == 1
    assert result["results"][0]["title"] == "招股说明书（注册稿）"


def test_query_a_share_interactions_local_returns_not_applicable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "load_companies", _local_registry)

    result = service.query_a_share_interactions("LOCAL-YXG")

    assert result["applicable"] is False
    assert result["matched"] == 0
    assert result["results"] == []


def test_downloader_returns_local_pdf_directly(tmp_path: pytest.TempPathFactory) -> None:
    from ashare_announcements_mcp import downloader

    pdf = tmp_path / "local.pdf"
    pdf.write_bytes(b"%PDF-1.7 local test")
    from ashare_announcements_mcp import cache

    monkeypatch_pdf_dir = _pdf_dir(tmp_path)
    cache.pdf_dir = monkeypatch_pdf_dir

    path, cache_hit = downloader.download_pdf("LOCAL-YXG", str(pdf))
    assert path == pdf
    assert cache_hit is True


def _pdf_dir(root: Path):
    def _inner(stock_code: str) -> Path:
        target = root / "cache" / stock_code / "pdfs"
        target.mkdir(parents=True, exist_ok=True)
        return target

    return _inner
