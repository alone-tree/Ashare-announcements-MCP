"""电话会议（transcripts）同步与查询的无网络测试。"""

from __future__ import annotations

from typing import Any

import pytest

from ashare_announcements_mcp import transcripts


def _report(form: str, report_date: str, accession: str) -> dict[str, Any]:
    return {
        "form": form,
        "report_date": report_date,
        "accession": accession,
    }


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
        + comment("Operator", "Thank you.")
    )


def test_add_months() -> None:
    from datetime import date

    assert transcripts._add_months(date(2026, 3, 31), -3) == date(2025, 12, 31)
    assert transcripts._add_months(date(2026, 3, 31), -6) == date(2025, 9, 30)
    assert transcripts._add_months(date(2026, 3, 31), -9) == date(2025, 6, 30)
    assert transcripts._add_months(date(2026, 6, 30), 3) == date(2026, 9, 30)


def test_derive_quarters_anchors_on_latest_10k() -> None:
    """MSFT 财年 6 月底结束：最近 10-K 2026-06-30 → FY2026，往前推 FY2025/2024…"""
    reports = [
        _report("10-K", "2024-06-30", "A1"),
        _report("10-Q", "2024-09-30", "A2"),
        _report("10-Q", "2024-12-31", "A3"),
        _report("10-Q", "2025-03-31", "A4"),
        _report("10-K", "2025-06-30", "A5"),
        _report("10-Q", "2025-09-30", "A6"),
        _report("10-Q", "2025-12-31", "A7"),
        _report("10-Q", "2026-03-31", "A8"),
        _report("10-K", "2026-06-30", "A9"),
    ]
    quarters = transcripts._derive_quarters(reports)
    by_date = {q["report_date"]: q for q in quarters}

    assert by_date["2026-06-30"]["fiscal_quarter"] == "FY2026-FY"
    assert by_date["2026-03-31"]["fiscal_quarter"] == "FY2026-Q3"
    assert by_date["2025-12-31"]["fiscal_quarter"] == "FY2026-Q2"
    assert by_date["2025-09-30"]["fiscal_quarter"] == "FY2026-Q1"
    assert by_date["2025-06-30"]["fiscal_quarter"] == "FY2025-FY"
    assert by_date["2024-06-30"]["fiscal_quarter"] == "FY2024-FY"


def test_derive_quarters_respects_min_year() -> None:
    """早期报告期（<2018 财年）不应被推算（Alpha 无数据）。"""
    reports = [
        _report("10-K", "2000-06-30", "O1"),
        _report("10-K", "2024-06-30", "A1"),
        _report("10-K", "2025-06-30", "A2"),
    ]
    quarters = transcripts._derive_quarters(reports)
    # 财季标签 FY 年份 ≥ 2018（FY2018-Q1 报告期在 2017 自然年属正常）
    years = {int(q["fiscal_quarter"][2:6]) for q in quarters}
    assert all(y >= 2018 for y in years)
    # 2000 年报告期被忽略
    assert "2000-06-30" not in {q["report_date"] for q in quarters}


def test_derive_quarters_handles_new_fiscal_q1_after_latest_10k() -> None:
    """最新 10-K 之后还有新财年 Q1（如最新披露报告期晚于锚点）。"""
    reports = [
        _report("10-K", "2025-06-30", "A1"),
        _report("10-Q", "2025-09-30", "A2"),
    ]
    quarters = transcripts._derive_quarters(reports)
    by_date = {q["report_date"]: q for q in quarters}
    assert by_date["2025-09-30"]["fiscal_quarter"] == "FY2026-Q1"


def test_derive_quarters_no_10k_falls_back_to_latest() -> None:
    """无 10-K（刚上市只有 10-Q）：以最新报告期为锚。"""
    reports = [
        _report("10-Q", "2026-03-31", "N1"),
        _report("10-Q", "2026-06-30", "N2"),
    ]
    quarters = transcripts._derive_quarters(reports)
    # 最新 2026-06-30 视为该财年 Q3（anchor 估算）
    assert quarters  # 不崩溃，返回非空


def test_parse_comments() -> None:
    comments = transcripts._parse_comments(_alpha_html())
    assert len(comments) == 4
    assert comments[0]["author"] == "Operator"
    assert "record revenue" in comments[1]["text"]


def test_build_alpha_url() -> None:
    url = transcripts._build_alpha_url("AAPL", "3", "2026")
    assert url == (
        "https://www.alphaspread.com/security/nasdaq/aapl/"
        "investor-relations/earnings-call/q3-2026"
    )


def test_sync_transcripts_fetches_derived_quarters(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    reports = [
        _report("10-K", "2025-06-30", "A1"),
        _report("10-Q", "2025-09-30", "A2"),
        _report("10-Q", "2025-12-31", "A3"),
        _report("10-Q", "2026-03-31", "A4"),
        _report("10-K", "2026-06-30", "A5"),
    ]
    monkeypatch.setattr(transcripts, "_company_cik", lambda code: "0000789019")
    monkeypatch.setattr(transcripts, "sync_edgar_archive", lambda code, cik: (None, None))
    monkeypatch.setattr(transcripts, "load_cache", lambda _code: {"items": reports, "meta": {}})
    monkeypatch.setattr(transcripts, "load_transcripts", lambda _code: {"items": [], "meta": {}})
    monkeypatch.setattr(
        transcripts,
        "_fetch_alpha",
        lambda url: (200, _alpha_html("Earnings Conference Call")),
    )
    monkeypatch.setattr(transcripts, "stock_cache_dir", lambda _code: tmp_path / "cache" / "AAPL")
    monkeypatch.setattr(transcripts, "time", _FakeTime())

    result = transcripts.sync_transcripts("AAPL", "AAPL")

    assert result["new"] == 5
    items = result["items"]
    fiscal_quarters = {it["fiscal_quarter"] for it in items}
    assert fiscal_quarters == {"FY2025-FY", "FY2026-Q1", "FY2026-Q2", "FY2026-Q3", "FY2026-FY"}
    assert all(it["status"] == "ok" for it in items)


class _FakeTime:
    def sleep(self, _seconds: float) -> None:
        return None


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
            "report_date": "2025-12-31",
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
    monkeypatch.setattr(transcripts, "sync_transcripts", lambda _c, _t, **kw: {"items": items, "new": 0})
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
            "report_date": "2025-12-31",
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
