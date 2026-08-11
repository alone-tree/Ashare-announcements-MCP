"""电话会议（transcripts）同步与查询的无网络测试。"""

from __future__ import annotations

from typing import Any

import pytest

from ashare_announcements_mcp import transcripts


def _report(form: str, report_date: str, accession: str, url: str = "https://x/") -> dict[str, Any]:
    return {
        "form": form,
        "report_date": report_date,
        "accession": accession,
        "url": url,
    }


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


def _alpha_html(first_line: str = "First Quarter 2025 Conference Call") -> str:
    def comment(author: str, text: str) -> str:
        return (
            '<div class="comment">'
            '<div class="avatar-container"><div class="avatar">'
            f'<div class="author">{author}'
            '<div class="description">executive</div>'
            "</div></div></div>"
            '<div class="content"><div class="text">'
            f"<p>{text}</p>"
            "</div></div></div>"
        )

    return (
        comment("Operator", first_line)
        + comment("Tim Cook", "We delivered record revenue.")
        + comment("Analyst", "Question about guidance.")
    )


def test_fiscal_fields_from_html(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        "<html><body>"
        "<dei:DocumentFiscalPeriodFocus>Q1</dei:DocumentFiscalPeriodFocus>"
        "<dei:DocumentFiscalYearFocus>2026</dei:DocumentFiscalYearFocus>"
        "<dei:DocumentPeriodEndDate>May 3, 2026</dei:DocumentPeriodEndDate>"
        "</body></html>"
    )
    monkeypatch.setattr(
        transcripts,
        "cache_filing_html",
        lambda _code, _accn, _url: _tmp_html(monkeypatch, html),
    )

    fields = transcripts._fiscal_fields("AAPL", "0001", "https://sec/x")

    assert fields["period"] == "Q1"
    assert fields["year"] == "2026"
    assert fields["end"] == "May 3, 2026"


def _tmp_html(monkeypatch: pytest.MonkeyPatch, html: str):
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "10q.html"
    tmp.write_text(html, encoding="utf-8")
    return tmp


def test_parse_comments() -> None:
    comments = transcripts._parse_comments(_alpha_html())
    assert len(comments) == 2
    assert comments[0]["author"] == "Operator"
    assert "record revenue" in comments[1]["text"]


def test_build_alpha_url() -> None:
    url = transcripts._build_alpha_url("AAPL", "3", "2026")
    assert url == (
        "https://www.alphaspread.com/security/nasdaq/aapl/"
        "investor-relations/earnings-call/q3-2026"
    )


def test_sync_transcripts_full_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    reports = [
        _report("10-Q", "2025-08-03", "ACC1"),
        _report("10-Q", "2025-11-02", "ACC2"),
        _report("10-K", "2026-02-01", "ACC3"),
    ]
    monkeypatch.setattr(transcripts, "load_cache", lambda _code: {"items": reports, "meta": {}})
    monkeypatch.setattr(transcripts, "load_transcripts", lambda _code: {"items": [], "meta": {}})
    monkeypatch.setattr(
        transcripts,
        "cache_filing_html",
        lambda _code, accn, _url: _tmp_html_for_accn(monkeypatch, accn),
    )
    monkeypatch.setattr(
        transcripts,
        "_fetch_alpha",
        lambda url: _fake_alpha_for_url(url),
    )
    monkeypatch.setattr(transcripts, "stock_cache_dir", lambda _code: tmp_path / "cache" / "AAPL")
    monkeypatch.setattr(transcripts, "time", _FakeTime())

    result = transcripts.sync_transcripts("AAPL", "AAPL")

    assert result["new"] == 3
    items = result["items"]
    # 10-K (FY) → Q4
    fy_item = [it for it in items if it["form"] == "10-K"][0]
    assert fy_item["fiscal_quarter"] == "FY2025-FY"
    assert fy_item["status"] == "ok"
    # 10-Q 用 URL 里 q 编号
    assert any(it["fiscal_quarter"] == "FY2026-Q3" for it in items)


class _FakeTime:
    def sleep(self, _seconds: float) -> None:
        return None


def _tmp_html_for_accn(monkeypatch: pytest.MonkeyPatch, accn: str):
    period_map = {"ACC1": ("Q2", "2026"), "ACC2": ("Q3", "2026"), "ACC3": ("FY", "2025")}
    period, year = period_map.get(accn, ("Q1", "2026"))
    html = (
        f"<dei:DocumentFiscalPeriodFocus>{period}</dei:DocumentFiscalPeriodFocus>"
        f"<dei:DocumentFiscalYearFocus>{year}</dei:DocumentFiscalYearFocus>"
    )
    return _tmp_html(monkeypatch, html)


def _fake_alpha_for_url(url: str):
    if "q4-2025" in url:
        return (200, _alpha_html("Fourth Quarter 2025 Financial Results"))
    if "404" in url:
        return (404, "not found")
    return (200, _alpha_html("Earnings Conference Call"))


def test_query_transcripts_not_applicable_for_hk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        transcripts,
        "resolve_company",
        lambda code: (
            code,
            [{"code": "00700", "market": "H", "name": "腾讯控股"}],
        ),
    )
    result = transcripts.query_transcripts("00700")
    assert result["applicable"] is False


def test_query_transcripts_by_period(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        {
            "fiscal_quarter": "FY2026-Q2",
            "report_date": "2025-08-03",
            "form": "10-Q",
            "status": "ok",
            "first_line": "Second Quarter 2025",
            "body_file": "BODY",
        }
    ]
    monkeypatch.setattr(
        transcripts,
        "resolve_company",
        lambda code: (code, [{"code": "AAPL", "market": "US", "name": "Apple"}]),
    )
    monkeypatch.setattr(transcripts, "sync_transcripts", lambda _c, _t, **kw: {"items": items, "new": 0, "cache_hit": False})
    monkeypatch.setattr(
        transcripts,
        "Path",
        lambda *a, **k: _FakePath(a[0] if a else "BODY"),
    )

    result = transcripts.query_transcripts("AAPL", period="FY2026-Q2")

    assert result["matched"] == 1
    assert result["fiscal_quarter"] == "FY2026-Q2"
    assert "body" in result


class _FakePath:
    def __init__(self, *args: Any) -> None:
        self._p = args[0] if args else ""

    def read_text(self, encoding: str = "utf-8") -> str:
        return (
            '{"meta": {"first_line": "Second Quarter 2025"}, '
            '"body": [{"author": "Operator", "text": "We delivered record revenue this quarter."}]}'
        )


def test_search_transcripts_finds_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        {
            "fiscal_quarter": "FY2026-Q2",
            "report_date": "2025-08-03",
            "status": "ok",
            "body_file": "BODY",
        }
    ]
    monkeypatch.setattr(
        transcripts,
        "resolve_company",
        lambda code: (code, [{"code": "AAPL", "market": "US", "name": "Apple"}]),
    )
    monkeypatch.setattr(transcripts, "load_transcripts", lambda _code: {"items": items, "meta": {}})
    monkeypatch.setattr(
        transcripts,
        "Path",
        lambda *a, **k: _FakePath("x"),
    )
    result = transcripts.search_transcripts("AAPL", "record revenue")

    assert result["matched"] == 1
    assert result["results"][0]["fiscal_quarter"] == "FY2026-Q2"
