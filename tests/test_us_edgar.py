"""美股 EDGAR 通道的无网络测试。"""

from __future__ import annotations

from typing import Any

import pytest

from ashare_announcements_mcp import service, us_edgar


def test_split_html_pages_uses_page_break() -> None:
    html = (
        "<html><body>"
        "<div>第一页内容</div>"
        '<div style="page-break-after:always"></div>'
        "<div>第二页内容</div>"
        '<div style="page-break-before:always"></div>'
        "<div>第三页内容</div>"
        "</body></html>"
    )
    pages = us_edgar.split_html_pages(html)
    assert len(pages) == 3
    assert "第一页内容" in pages[0]
    assert "第二页内容" in pages[1]
    assert "第三页内容" in pages[2]


def test_split_html_pages_falls_back_to_blocks() -> None:
    html = (
        "<html><body>"
        "<div>段落一，内容足够长用于切块测试，需要累积到目标字符数才会成为一块，这里继续补充文本。"
        "段落一，内容足够长用于切块测试，需要累积到目标字符数才会成为一块，这里继续补充文本。</div>"
        "<div>段落二</div>"
        "</body></html>"
    )
    pages = us_edgar.split_html_pages(html)
    # 无 page-break 时按 div 块切，至少一块
    assert len(pages) >= 1
    assert "段落一" in pages[0]


def test_clean_html_removes_xbrl_header() -> None:
    html = (
        "<html><body>"
        "<ix:header><div>XBRL 元数据</div></ix:header>"
        "<div>真实内容</div>"
        "</body></html>"
    )
    cleaned = us_edgar._clean_html(html)
    assert "XBRL" not in cleaned
    assert "真实内容" in cleaned


def test_expand_submissions_handles_older_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """历史分片文件顶层无 filings 包装，需兼容。"""
    calls = {"count": 0}

    def fake_get(url: str, **kwargs: Any):
        calls["count"] += 1
        if "submissions-001" in url:
            return _FakeResponse(
                {
                    "accessionNumber": ["0000000001-15-000001"],
                    "filingDate": ["2015-05-30"],
                    "form": ["10-K"],
                    "primaryDocument": ["old.htm"],
                    "primaryDocDescription": ["10-K"],
                }
            )
        return _FakeResponse(
            {
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000000001-26-000001"],
                        "filingDate": ["2026-07-01"],
                        "form": ["8-K"],
                        "primaryDocument": ["new.htm"],
                        "primaryDocDescription": ["8-K"],
                    },
                    "files": [{"name": "CIK0000000001-submissions-001.json"}],
                }
            }
        )

    monkeypatch.setattr(us_edgar.requests, "get", fake_get)

    result = us_edgar.fetch_submissions("0000000001")

    assert len(result["items"]) == 2
    assert result["items"][0]["filing_date"] == "2026-07-01"
    assert result["items"][1]["filing_date"] == "2015-05-30"
    assert calls["count"] == 2


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def test_format_us_filing_builds_unified_item() -> None:
    item = {
        "accession": "0000320193-26-000018",
        "filing_date": "2026-07-30",
        "form": "8-K",
        "document": "aapl-20260730.htm",
        "description": "8-K",
    }
    result = service._format_us_filing("AAPL", "0000320193", item)
    assert result["code"] == "0000320193-26-000018"
    assert result["display_time"] == "2026-07-30 00:00:00"
    assert result["form"] == "8-K"
    assert "sec.gov" in result["url"]
    assert result["title"].startswith("8-K")
