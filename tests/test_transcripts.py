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
            '{"meta": {"source": "alphaspread"}, '
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


def test_sync_only_recent_limits_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """only_recent=True：财季数 > RECENT_QUARTERS 时只下载最近 12 个。"""
    # 构造 20 个财季（5 年 × 4，2022-06-30 的 10-K 起）
    reports = []
    for year in range(2022, 2027):
        reports.append(_report("10-K", f"{year}-06-30", f"K{year}"))
        reports.append(_report("10-Q", f"{year}-09-30", f"Q{year}1"))
        reports.append(_report("10-Q", f"{year}-12-31", f"Q{year}2"))
        reports.append(_report("10-Q", f"{year+1}-03-31", f"Q{year}3"))
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

    result = transcripts.sync_transcripts("AAPL", "AAPL", only_recent=True)

    assert result["new"] == transcripts.RECENT_QUARTERS
    # 下载的是最近 12 个财季（report_date 最大的 12 个）
    dates = sorted(it["report_date"] for it in result["items"])
    assert len(dates) == transcripts.RECENT_QUARTERS
    assert dates[-1] == "2027-03-31"  # 最新报告期在
    assert "2022-06-30" not in dates  # 最早的被截断


def test_sync_target_period_fetches_specific(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """target_period：只下载指定早期财季（按需补下载），不触发全量。"""
    reports = [
        _report("10-K", "2020-06-30", "K2020"),
        _report("10-K", "2021-06-30", "K2021"),
        _report("10-K", "2022-06-30", "K2022"),
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

    result = transcripts.sync_transcripts("AAPL", "AAPL", only_recent=False,
                                          target_period="FY2020-FY")

    assert result["new"] == 1
    assert result["items"][0]["fiscal_quarter"] == "FY2020-FY"
    assert result["items"][0]["status"] == "ok"


def test_query_transcripts_period_backfills_early(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """query_transcripts(period=早期季)：常规同步没下载时，按需补下载目标季。"""
    recent_items = []  # 常规同步只返回空（未下载早期季）
    backfilled = [
        {
            "fiscal_quarter": "FY2020-Q1",
            "report_date": "2019-12-31",
            "form": "10-Q",
            "status": "ok",
            "body_file": "BODY",
        }
    ]
    calls = []

    def fake_sync(_c, _t, **kw):
        calls.append(kw)
        if kw.get("target_period"):
            return {"items": backfilled, "new": 1}
        return {"items": recent_items, "new": 0}

    monkeypatch.setattr(
        transcripts,
        "resolve_company",
        lambda code: (code, [{"code": "AAPL", "market": "US", "name": "Apple"}]),
    )
    monkeypatch.setattr(transcripts, "sync_transcripts", fake_sync)
    monkeypatch.setattr(
        transcripts,
        "Path",
        lambda *a, **k: _FakePath("BODY"),
    )

    result = transcripts.query_transcripts("AAPL", period="FY2020-Q1")

    assert result["matched"] == 1
    assert result["fiscal_quarter"] == "FY2020-Q1"
    # 第二次调用带 target_period（按需补下载）
    assert calls[-1].get("target_period") == "FY2020-Q1"


def test_company_slug() -> None:
    """公司名 → AlphaStreet URL slug。"""
    assert transcripts._company_slug("Lumentum Holdings Inc") == "lumentum-holdings-inc"
    assert transcripts._company_slug("Apple Inc.") == "apple-inc"
    assert transcripts._company_slug("  Coherent Corp (COHR) ") == "coherent-corp"
    assert transcripts._company_slug("Alphabet Inc. (Class A)") == "alphabet-inc"


def test_parse_alphastreet() -> None:
    """AlphaStreet 正文：连续 <p> 段落，含 Q&A 前介绍，不区分 speaker。"""
    html = """
    <html><body>
    <h1>Lumentum Holdings Inc (LITE) Q1 2026 Earnings Call Transcript</h1>
    <p>Good day, everyone, and welcome to the Lumentum Holdings First Quarter Fiscal Year 2026 Earnings Call.</p>
    <p>At this time I would like to turn the call over to Kathy Ta.</p>
    <p>Thank you, and welcome to Lumentum's first quarter of fiscal year 2026.</p>
    <p>Operator: We will now begin the question-and-answer session.</p>
    <p>Hi, just making sure, can you hear me?</p>
    <p>Yeah, we can hear you.</p>
    <div>Disclaimer: The information provided is for informational purposes only.</div>
    </body></html>
    """
    parts = transcripts._parse_alphastreet(html)
    assert len(parts) == 6
    assert all(p["author"] == "" for p in parts)  # 不区分 speaker
    assert "Good day" in parts[0]["text"]  # 含 Q&A 前介绍
    assert "question-and-answer" in parts[3]["text"]
    assert "Disclaimer" not in "".join(p["text"] for p in parts)  # 不包含声明


def test_download_body_falls_back_to_alphastreet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alpha Spread 无收录 → 尝试 AlphaStreet 备用源。"""
    monkeypatch.setattr(transcripts, "_company_name", lambda code: "Lumentum Holdings Inc")
    calls = []

    def fake_fetch(url):
        calls.append(url)
        if "alphaspread.com" in url:
            return 404, "<html>not found</html>"
        return 200, """
            <html><body>
            <h1>Lumentum (LITE) Q4 2026 Earnings Call Transcript</h1>
            <p>Good day, everyone, and welcome to the Lumentum Fourth Quarter Fiscal Year 2026 Earnings Call.</p>
            <p>Revenue surged year-over-year.</p>
            </body></html>
        """

    monkeypatch.setattr(transcripts, "_fetch_alpha", fake_fetch)
    body, meta = transcripts._download_body("LITE", "LITE", "4", "2026")

    assert body is not None
    assert meta["source"] == "alphastreet"
    assert "alphaspread.com" in calls[0]
    assert "news.alphastreet.com" in calls[1]
    assert len(calls) == 2


def test_download_body_uses_alphaspread_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alpha Spread 有收录 → 不用备用源。"""
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return 200, _alpha_html("Fourth Quarter Fiscal Year 2026 Conference Call")

    monkeypatch.setattr(transcripts, "_fetch_alpha", fake_fetch)
    body, meta = transcripts._download_body("LITE", "LITE", "4", "2026")

    assert meta["source"] == "alphaspread"
    assert len(calls) == 1  # 只请求主源


def test_sync_alphastreet_retried_next_time(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """备源结果（source=alphastreet）不算已保存：下次同步仍试主源，主源收录后覆盖。"""
    reports = [
        _report("10-K", "2025-06-30", "A1"),
        _report("10-K", "2026-06-30", "A5"),
    ]
    monkeypatch.setattr(transcripts, "_company_cik", lambda code: "0000789019")
    monkeypatch.setattr(transcripts, "sync_edgar_archive", lambda code, cik: (None, None))
    monkeypatch.setattr(transcripts, "load_cache", lambda _code: {"items": reports, "meta": {}})
    monkeypatch.setattr(transcripts, "load_transcripts", lambda _code: {"items": [], "meta": {}})
    monkeypatch.setattr(transcripts, "stock_cache_dir", lambda _code: tmp_path / "cache" / "AAPL")
    monkeypatch.setattr(transcripts, "time", _FakeTime())
    monkeypatch.setattr(transcripts, "_company_name", lambda code: "Apple Inc")

    # 第一次：主源 404，备源成功
    def fake_fetch(url):
        if "alphaspread.com" in url:
            return 404, "<html>x</html>"
        return 200, '<html><h1>Apple Q1 2026</h1><p>Good day everyone.</p></html>'

    monkeypatch.setattr(transcripts, "_fetch_alpha", fake_fetch)
    result = transcripts.sync_transcripts("AAPL", "AAPL", only_recent=True)
    street_items = [it for it in result["items"] if it.get("source") == "alphastreet"]
    assert street_items, "备源应成功"

    # 第二次：主源已收录（200 + comment），应覆盖备源
    def fake_fetch_ok(url):
        if "alphaspread.com" in url:
            return 200, _alpha_html("Earnings Conference Call")
        return 404, "<html>x</html>"

    monkeypatch.setattr(transcripts, "_fetch_alpha", fake_fetch_ok)
    result2 = transcripts.sync_transcripts("AAPL", "AAPL", only_recent=True)
    spread_items = [it for it in result2["items"] if it.get("source") == "alphaspread"]
    assert spread_items, "主源收录后应覆盖备源"
    street_left = [it for it in result2["items"] if it.get("source") == "alphastreet"]
    assert not street_left, "备源记录应被主源覆盖"
