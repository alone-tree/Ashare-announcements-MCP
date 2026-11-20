"""电话会议（transcripts）同步与查询的无网络测试。"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from ashare_announcements_mcp import roic_api, transcripts


class _NoSleep:
    def sleep(self, _seconds: float) -> None:  # pragma: no cover - 仅替换限速
        pass


def _report(form: str, report_date: str, accession: str) -> dict[str, Any]:
    return {"form": form, "report_date": report_date, "accession": accession}


def _index_html(labels: list[tuple[int, int]]) -> str:
    rows = "".join(
        f'<a href="/stocks/aapl/transcripts/{900000 + year * 10 + q}-q{q}-{year}/">'
        f"Earnings Call: Q{q} {year}</a>"
        for year, q in labels
    )
    return f'<html><body><div class="transcript-list">{rows}</div></body></html>'


def _turn(author: str, *paragraphs: str) -> str:
    body = "".join(
        f'<p class="text-default mt-2"><span class="transcript-sentence rounded">'
        f"{p}</span></p>"
        for p in paragraphs
    )
    return (
        '<div class="border-t border-sharp pt-5 first:border-t-0 first:pt-0">'
        f'<div class="text-lg font-bold text-default md:text-xl">{author}</div>'
        f"{body}</div>"
    )


def _transcript_html() -> str:
    return (
        '<html><body><div id="transcript-panel-full" role="region">'
        '<div class="space-y-6">'
        + _turn("Operator", "Good afternoon.", "My name is Krista.")
        + _turn("Tim Cook", "We delivered record revenue of $100 billion.")
        + _turn("Analyst", "Question about guidance.")
        + '</div></div><div id="transcript-panel-preview"></div></body></html>'
    )


def test_add_months() -> None:
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

    assert by_date["2026-06-30"]["fiscal_quarter"] == "FY2026-Q4"
    assert by_date["2026-03-31"]["fiscal_quarter"] == "FY2026-Q3"
    assert by_date["2025-12-31"]["fiscal_quarter"] == "FY2026-Q2"
    assert by_date["2025-09-30"]["fiscal_quarter"] == "FY2026-Q1"
    assert by_date["2025-06-30"]["fiscal_quarter"] == "FY2025-Q4"
    assert by_date["2024-06-30"]["fiscal_quarter"] == "FY2024-Q4"


def test_parse_index() -> None:
    html = _index_html([(2026, 3), (2026, 2), (2025, 4)])
    entries = transcripts._parse_index(html)
    assert set(entries) == {(2026, 3), (2026, 2), (2025, 4)}
    assert entries[(2026, 3)] == f"/stocks/aapl/transcripts/{900000 + 2026 * 10 + 3}-q3-2026/"


def test_parse_index_ignores_non_earnings_entries() -> None:
    html = (
        '<a href="/stocks/aapl/transcripts/759230-meta-connect-2026-opening-keynote/">Keynote</a>'
        + _index_html([(2026, 2)])
    )
    entries = transcripts._parse_index(html)
    assert set(entries) == {(2026, 2)}


def test_hk_index_url() -> None:
    """港股五位代码转上游四位习惯写法；美股路径不受影响。"""
    assert transcripts._index_url("00700", "H") == "https://stockanalysis.com/quote/hkg/0700/transcripts/"
    assert transcripts._index_url("1024", "H") == "https://stockanalysis.com/quote/hkg/1024/transcripts/"
    assert transcripts._index_url("AAPL") == "https://stockanalysis.com/stocks/aapl/transcripts/"


def test_parse_transcript_stops_at_site_footer() -> None:
    """正文截取在站点注记/页脚前截止，不混入最后一轮发言。"""
    html = (
        '<html><body><div id="transcript-panel-full" role="region">'
        + _turn("Tim Cook", "We delivered record revenue of $100 billion.")
        + "<p>Play Audio Download Transcript</p>"
        + '<summary><div class="border-t"><p>Earnings call transcripts are provided by '
        + '<a href="https://quartr.com/">Quartr</a> and are published within hours.</p></div></summary>'
        + "<footer>© 2026 StockAnalysis.com. All rights reserved.</footer>"
        + "</div></body></html>"
    )
    turns = transcripts._parse_transcript(html)
    assert len(turns) == 1
    assert "record revenue" in turns[0]["text"]
    assert "StockAnalysis" not in turns[0]["text"]
    assert "Quartr" not in turns[0]["text"]


def test_parse_transcript() -> None:
    turns = transcripts._parse_transcript(_transcript_html())
    assert [t["author"] for t in turns] == ["Operator", "Tim Cook", "Analyst"]
    assert "record revenue" in turns[1]["text"]
    assert "My name is Krista." in turns[0]["text"]
    assert "transcript-panel-preview" not in turns[-1]["text"]


def _fake_fetch(index_html: str, body_html: str, status: int = 200):
    def fetch(url: str) -> tuple[int, str]:
        if url.endswith("/transcripts/"):
            return 200, index_html
        return status, body_html

    return fetch


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path, reports: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(transcripts, "_company_cik", lambda code: "0000789019")
    monkeypatch.setattr(transcripts, "sync_edgar_archive", lambda code, cik: (None, None))
    monkeypatch.setattr(transcripts, "load_cache", lambda _code: {"items": reports, "meta": {}})
    monkeypatch.setattr(transcripts, "load_transcripts", lambda _code: {"items": [], "meta": {}})
    monkeypatch.setattr(
        transcripts, "stock_cache_dir", lambda _code: tmp_path / "cache" / "AAPL"
    )
    monkeypatch.setattr(transcripts, "time", _NoSleep())
    # 单元测试一律无 ROIC key：防止读到本机真实 config.yaml 打真实网络
    monkeypatch.setattr(roic_api, "load_api_key", lambda: "")


def test_sync_transcripts_downloads_and_maps_report_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    reports = [
        _report("10-K", "2025-09-30", "A1"),
        _report("10-Q", "2025-12-31", "A2"),
        _report("10-Q", "2026-03-31", "A3"),
    ]
    _setup(monkeypatch, tmp_path, reports)
    monkeypatch.setattr(
        transcripts,
        "_fetch_html",
        _fake_fetch(_index_html([(2026, 2), (2026, 1), (2025, 4)]), _transcript_html()),
    )

    result = transcripts.sync_transcripts("AAPL", "AAPL")
    items = {it["fiscal_quarter"]: it for it in result["items"]}

    assert result["new"] == 3
    assert set(items) == {"FY2026-Q2", "FY2026-Q1", "FY2025-Q4"}
    assert all(it["status"] == "ok" for it in items.values())
    assert items["FY2026-Q2"]["report_date"] == "2026-03-31"
    assert items["FY2026-Q1"]["report_date"] == "2025-12-31"
    assert items["FY2026-Q1"]["form"] == "10-Q"
    assert items["FY2025-Q4"]["report_date"] == "2025-09-30"
    assert items["FY2025-Q4"]["form"] == "10-K"
    assert items["FY2026-Q2"]["url"].startswith("https://stockanalysis.com/stocks/aapl/")
    body = __import__("json").loads(
        __import__("pathlib").Path(items["FY2026-Q2"]["body_file"]).read_text(encoding="utf-8")
    )
    assert body["meta"]["source"] == "stockanalysis"
    assert len(body["body"]) == 3


def test_sync_transcripts_marks_missing_and_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _setup(monkeypatch, tmp_path, [])
    monkeypatch.setattr(
        transcripts,
        "_fetch_html",
        _fake_fetch(_index_html([(2026, 1)]), "<html>error</html>", status=404),
    )
    result = transcripts.sync_transcripts("AAPL", "AAPL")
    assert result["items"][0]["status"] == "missing"

    monkeypatch.setattr(
        transcripts,
        "_fetch_html",
        _fake_fetch(_index_html([(2026, 1)]), "<html>error</html>", status=503),
    )
    result = transcripts.sync_transcripts("AAPL", "AAPL")
    assert result["items"][0]["status"] == "failed"
    assert result["items"][0]["http_status"] == 503


def test_sync_transcripts_failed_when_parse_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _setup(monkeypatch, tmp_path, [])
    monkeypatch.setattr(
        transcripts,
        "_fetch_html",
        _fake_fetch(_index_html([(2026, 1)]), "<html>no turns</html>"),
    )
    result = transcripts.sync_transcripts("AAPL", "AAPL")
    assert result["items"][0]["status"] == "failed"
    assert "解析不出" in result["items"][0]["error"]


def test_sync_transcripts_only_recent_limit(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    labels = [(2026 - i // 4, 4 - i % 4) for i in range(20)]
    _setup(monkeypatch, tmp_path, [])
    monkeypatch.setattr(
        transcripts, "_fetch_html", _fake_fetch(_index_html(labels), _transcript_html())
    )
    result = transcripts.sync_transcripts("AAPL", "AAPL", only_recent=True)
    assert result["new"] == transcripts.RECENT_QUARTERS
    assert len(result["items"]) == 20


def test_sync_transcripts_target_period(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    labels = [(2026, 2), (2026, 1), (2025, 4)]
    _setup(monkeypatch, tmp_path, [])
    monkeypatch.setattr(
        transcripts, "_fetch_html", _fake_fetch(_index_html(labels), _transcript_html())
    )
    result = transcripts.sync_transcripts(
        "AAPL", "AAPL", only_recent=True, target_period="FY2025-Q4"
    )
    assert result["new"] == 1
    statuses = {it["fiscal_quarter"]: it.get("status") for it in result["items"]}
    assert statuses["FY2025-Q4"] == "ok"
    assert statuses["FY2026-Q2"] is None


def test_sync_transcripts_keeps_cached_ok(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    labels = [(2026, 1)]
    _setup(monkeypatch, tmp_path, [])
    monkeypatch.setattr(
        transcripts, "_fetch_html", _fake_fetch(_index_html(labels), _transcript_html())
    )
    first = transcripts.sync_transcripts("AAPL", "AAPL")
    assert first["new"] == 1

    monkeypatch.setattr(
        transcripts,
        "load_transcripts",
        lambda _code: {"items": first["items"], "meta": {}},
    )
    second = transcripts.sync_transcripts("AAPL", "AAPL")
    assert second["new"] == 0
    assert second["items"][0]["status"] == "ok"

    third = transcripts.sync_transcripts("AAPL", "AAPL", force_refresh=True)
    assert third["new"] == 1


def test_cross_listing_index_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR 美股页无电话会时，读个股页 transcriptsLinkSymbol 指向主上市代码。"""
    monkeypatch.setattr(
        transcripts,
        "_fetch_html",
        lambda _url: (200, '<script>transcriptsLinkSymbol:"TPE-2330"</script>'),
    )
    assert transcripts._cross_listing_index_url("TSM") == (
        "https://stockanalysis.com/quote/tpe/2330/transcripts/"
    )

    monkeypatch.setattr(
        transcripts, "_fetch_html", lambda _url: (200, 'transcriptsLinkSymbol:"META"')
    )
    assert transcripts._cross_listing_index_url("META") is None


def test_sync_transcripts_uses_cross_listing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """US 代码页 404 → 落到 /quote/{exch}/{code}/transcripts/ 并正常下载。"""
    _setup(monkeypatch, tmp_path, [])
    calls: list[str] = []

    def fetch(url: str) -> tuple[int, str]:
        calls.append(url)
        if url.endswith("/stocks/aapl/transcripts/"):
            return 404, "not found"
        if url.endswith("/stocks/aapl/"):
            return 200, 'transcriptsLinkSymbol:"TPE-2330"'
        if url.endswith("/quote/tpe/2330/transcripts/"):
            return 200, _index_html([(2026, 3)])
        return 200, _transcript_html()

    monkeypatch.setattr(transcripts, "_fetch_html", fetch)
    result = transcripts.sync_transcripts("AAPL", "AAPL")
    assert result["items"][0]["status"] == "ok"
    assert result["items"][0]["url"].endswith("-q3-2026/")
    assert any("/quote/tpe/2330/" in c for c in calls)


def test_fetch_html_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """代理偶发断连：重试后成功。"""
    attempts = {"n": 0}

    class _Resp:
        status_code = 200
        text = "ok"

    def fake_get(url, headers=None, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise transcripts.requests.exceptions.ConnectionError("boom")
        return _Resp()

    monkeypatch.setattr(transcripts.requests, "get", fake_get)
    monkeypatch.setattr(transcripts, "time", _NoSleep())
    assert transcripts._fetch_html("https://stockanalysis.com/x") == (200, "ok")
    assert attempts["n"] == 2


def test_sync_transcripts_index_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """站点没有该公司的电话会页面（404）：不抛异常，返回空索引。"""
    _setup(monkeypatch, tmp_path, [])
    monkeypatch.setattr(transcripts, "_fetch_html", lambda _url: (404, "<html>not found</html>"))
    result = transcripts.sync_transcripts("TSM", "TSM")
    assert result["items"] == []
    assert result["index_available"] is False
    assert result["new"] == 0


def test_query_transcripts_index_missing_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcripts, "normalize_stock_code", lambda code: "TSM")
    monkeypatch.setattr(
        transcripts, "resolve_company", lambda code: ("TSM", [{"market": "US", "code": "TSM"}])
    )
    monkeypatch.setattr(
        transcripts,
        "sync_transcripts",
        lambda _c, _t, **kw: {"items": [], "new": 0, "index_available": False},
    )
    result = transcripts.query_transcripts("TSM")
    assert result["total_transcripts"] == 0
    assert "没有该公司的电话会页面" in result["note"]


def test_query_transcripts_routes_pure_hk(monkeypatch: pytest.MonkeyPatch) -> None:
    """纯港股走 hkg 路径；指定财季 missing 时如实返回未收录。"""
    captured: dict[str, Any] = {}

    def fake_sync(code, ticker, market="US", **kw):
        captured.update(code=code, ticker=ticker, market=market)
        return {"items": [{"fiscal_quarter": "FY2026-Q3", "status": "missing"}], "new": 0}

    monkeypatch.setattr(transcripts, "normalize_stock_code", lambda code: "00700")
    monkeypatch.setattr(
        transcripts, "resolve_company", lambda code: ("00700", [{"market": "H", "code": "00700"}])
    )
    monkeypatch.setattr(transcripts, "sync_transcripts", fake_sync)

    result = transcripts.query_transcripts("00700", period="FY2026-Q3")
    assert captured == {"code": "00700", "ticker": "00700", "market": "H"}
    assert result["applicable"] is True
    assert result["matched"] == 0
    assert result["results"][0]["status"] == "missing"


def test_query_transcripts_ah_pair_uses_hk_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """A+H 公司从 A 股代码查询时，电话稿按 H 股代码存取。"""
    captured: dict[str, Any] = {}

    def fake_sync(code, ticker, market="US", **kw):
        captured.update(code=code, market=market)
        return {"items": [], "new": 0}

    monkeypatch.setattr(transcripts, "normalize_stock_code", lambda code: "300308")
    monkeypatch.setattr(
        transcripts,
        "resolve_company",
        lambda code: (
            "300308",
            [{"market": "A", "code": "300308"}, {"market": "H", "code": "03308"}],
        ),
    )
    monkeypatch.setattr(transcripts, "sync_transcripts", fake_sync)

    transcripts.query_transcripts("300308")
    assert captured == {"code": "03308", "market": "H"}


def test_query_transcripts_period_only_targets_quarter(monkeypatch: pytest.MonkeyPatch) -> None:
    """指定财季时只处理该季，不触发最近 12 季批量下载。"""
    captured: dict[str, Any] = {}

    def fake_sync(code, ticker, market="US", only_recent=True, target_period=None, **kw):
        captured.update(only_recent=only_recent, target_period=target_period)
        return {"items": [{"fiscal_quarter": "FY2020-Q1", "status": "missing"}], "new": 0}

    monkeypatch.setattr(transcripts, "normalize_stock_code", lambda code: "AAPL")
    monkeypatch.setattr(
        transcripts, "resolve_company", lambda code: ("AAPL", [{"market": "US", "code": "AAPL"}])
    )
    monkeypatch.setattr(transcripts, "sync_transcripts", fake_sync)

    transcripts.query_transcripts("AAPL", period="FY2020-Q1")
    assert captured == {"only_recent": False, "target_period": "FY2020-Q1"}


def test_search_transcripts_uses_hk_store(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A+H 检索与查询同键：从 A 股入口检索 H 股代码下的缓存。"""
    import json

    body_file = tmp_path / "FY2026-Q3.json"
    body_file.write_text(
        json.dumps(
            {"meta": {"source": "stockanalysis"}, "body": [{"author": "CEO", "text": "revenue up"}]}
        ),
        encoding="utf-8",
    )
    items = [{"fiscal_quarter": "FY2026-Q3", "status": "ok", "body_file": str(body_file)}]
    seen: dict[str, Any] = {}

    def fake_load(code: str):
        seen["code"] = code
        return {"items": items, "meta": {}}

    monkeypatch.setattr(transcripts, "normalize_stock_code", lambda code: "300308")
    monkeypatch.setattr(
        transcripts,
        "resolve_company",
        lambda code: (
            "300308",
            [{"market": "A", "code": "300308"}, {"market": "H", "code": "03308"}],
        ),
    )
    monkeypatch.setattr(transcripts, "load_transcripts", fake_load)

    result = transcripts.search_transcripts("300308", "revenue")
    assert seen["code"] == "03308"
    assert result["applicable"] is True
    assert result["matched"] == 1


def test_sync_transcripts_force_refresh_keeps_ok_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """强制刷新正文下载失败时保留已缓存旧稿，只记刷新失败原因。"""
    _setup(monkeypatch, tmp_path, [])
    monkeypatch.setattr(
        transcripts, "_fetch_html", _fake_fetch(_index_html([(2026, 1)]), _transcript_html())
    )
    first = transcripts.sync_transcripts("AAPL", "AAPL")
    assert first["items"][0]["status"] == "ok"
    body_file = first["items"][0]["body_file"]

    monkeypatch.setattr(
        transcripts,
        "load_transcripts",
        lambda _code: {"items": first["items"], "meta": {}},
    )
    monkeypatch.setattr(
        transcripts,
        "_fetch_html",
        lambda url: (200, _index_html([(2026, 1)])) if url.endswith("/transcripts/") else (503, ""),
    )
    second = transcripts.sync_transcripts("AAPL", "AAPL", force_refresh=True)
    item = second["items"][0]
    assert item["status"] == "ok"
    assert item["body_file"] == body_file
    assert "503" in str(item.get("refresh_error"))


def _roic_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    key: str = "k",
    identifier: str = "HKEX:700",
    events: list[dict[str, Any]] | None = None,
    raw: str = "ROICTEXT",
    list_error: Exception | None = None,
    raw_error: Exception | None = None,
) -> dict[str, Any]:
    """统一 mock ROIC 适配层，返回调用记录。"""
    calls: dict[str, Any] = {"resolve": 0, "list": 0, "raw": []}
    monkeypatch.setattr(roic_api, "load_api_key", lambda: key)
    monkeypatch.setattr(transcripts, "time", _NoSleep())

    def fake_resolve(ticker: str, market: str, cik: str = "") -> str:
        calls["resolve"] += 1
        return identifier

    def fake_list(ident: str, limit: int = 2) -> list[dict[str, Any]]:
        calls["list"] += 1
        if list_error:
            raise list_error
        return events or []

    def fake_raw(tid: str) -> str:
        calls["raw"].append(tid)
        if raw_error:
            raise raw_error
        return raw

    monkeypatch.setattr(roic_api, "resolve_identifier", fake_resolve)
    monkeypatch.setattr(roic_api, "list_recent", fake_list)
    monkeypatch.setattr(roic_api, "fetch_raw", fake_raw)
    return calls


def test_roic_backfill_covers_missing_quarter(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """主源缺稿 + ROIC 有：补位成 ok，正文缓存标注 roic 来源。"""
    import json
    from pathlib import Path

    _setup(monkeypatch, tmp_path, [])
    events = [
        {
            "fiscal_year": 2026,
            "fiscal_quarter": 3,
            "period_end_date": "2026-09-30",
            "transcripts": [{"id": "trraw_a"}],
        }
    ]
    calls = _roic_mocks(monkeypatch, events=events)
    items = [{"fiscal_quarter": "FY2026-Q3", "report_date": "", "form": "", "status": "missing"}]

    meta = transcripts._roic_backfill("00700", "00700", "H", "", items, {}, False, None)

    assert meta["merged"] == ["FY2026-Q3"]
    assert meta["identifier"] == "HKEX:700"
    assert calls["raw"] == ["trraw_a"]
    item = items[0]
    assert item["status"] == "ok"
    assert item["source"] == "roic"
    assert item["report_date"] == "2026-09-30"
    body = json.loads(Path(item["body_file"]).read_text(encoding="utf-8"))
    assert body["meta"]["source"] == "roic"
    assert body["body"] == [{"author": "", "text": "ROICTEXT"}]


def test_roic_backfill_skips_when_primary_complete(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """指定财季且主源已给出正文：不发起任何 ROIC 请求。"""
    _setup(monkeypatch, tmp_path, [])
    body_file = tmp_path / "b.json"
    body_file.write_text("{}", encoding="utf-8")
    items = [
        {"fiscal_quarter": "FY2026-Q3", "status": "ok", "source": "stockanalysis",
         "body_file": str(body_file)},
    ]
    calls = _roic_mocks(monkeypatch)

    meta = transcripts._roic_backfill("x", "x", "US", "1", items, {}, False, "FY2026-Q3")

    assert meta == {}
    assert calls["list"] == 0
    assert calls["resolve"] == 0


def test_roic_backfill_lists_recent_without_period(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """不传财季时必须独立查 ROIC：主源目录完好也要列一次，避免旧季掩盖新稿。"""
    _setup(monkeypatch, tmp_path, [])
    body_file = tmp_path / "b.json"
    body_file.write_text("{}", encoding="utf-8")
    items = [
        {"fiscal_quarter": "FY2026-Q3", "status": "ok", "source": "stockanalysis",
         "body_file": str(body_file)},
        {"fiscal_quarter": "FY2026-Q2", "status": "ok", "source": "stockanalysis",
         "body_file": str(body_file)},
    ]
    calls = _roic_mocks(monkeypatch)

    meta = transcripts._roic_backfill("x", "x", "US", "1", items, {}, False, None)

    assert calls["list"] == 1
    assert meta.get("merged") == []
    assert len(items) == 2


def test_roic_backfill_surfaces_rate_limit(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """429 限流如实透传 retry_after_seconds，主源条目保持原状。"""
    _setup(monkeypatch, tmp_path, [])
    calls = _roic_mocks(monkeypatch, list_error=roic_api.RoicRateLimited(12, 1795142531))
    items = [{"fiscal_quarter": "FY2026-Q3", "status": "missing"}]

    meta = transcripts._roic_backfill("00700", "00700", "H", "", items, {}, False, None)

    assert meta["rate_limited"] == {"retry_after_seconds": 12, "reset_epoch": 1795142531}
    assert items[0]["status"] == "missing"


def test_roic_backfill_disabled_without_key(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """未配置 key：补位关闭，不发任何请求。"""
    _setup(monkeypatch, tmp_path, [])
    calls = _roic_mocks(monkeypatch, key="")

    meta = transcripts._roic_backfill(
        "x", "x", "US", "1", [{"fiscal_quarter": "FY2026-Q3", "status": "missing"}], {}, False, None
    )

    assert meta == {}
    assert calls["resolve"] == 0


def test_roic_backfill_out_of_window(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """402 超免费窗口：跳过该场并记录，不冒充成功。"""
    _setup(monkeypatch, tmp_path, [])
    events = [
        {
            "fiscal_year": 2026,
            "fiscal_quarter": 3,
            "period_end_date": "2026-09-30",
            "transcripts": [{"id": "trraw_a"}],
        }
    ]
    _roic_mocks(monkeypatch, events=events, raw_error=roic_api.RoicOutOfWindow("w"))
    items = [{"fiscal_quarter": "FY2026-Q3", "status": "missing"}]

    meta = transcripts._roic_backfill("00700", "00700", "H", "", items, {}, False, None)

    assert meta["out_of_window"] == ["FY2026-Q3"]
    assert meta.get("merged") == []
    assert items[0]["status"] == "missing"


def test_roic_backfill_target_period_filters(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """指定财季时只取目标季，另一场不下载。"""
    _setup(monkeypatch, tmp_path, [])
    events = [
        {"fiscal_year": 2026, "fiscal_quarter": 3, "period_end_date": "2026-09-30",
         "transcripts": [{"id": "trraw_q3"}]},
        {"fiscal_year": 2026, "fiscal_quarter": 2, "period_end_date": "2026-06-30",
         "transcripts": [{"id": "trraw_q2"}]},
    ]
    calls = _roic_mocks(monkeypatch, events=events)

    meta = transcripts._roic_backfill("00700", "00700", "H", "", [], {}, False, "FY2026-Q2")

    assert calls["raw"] == ["trraw_q2"]
    assert meta["merged"] == ["FY2026-Q2"]


def test_roic_identifier_rules() -> None:
    """港股去前导零规则；美股必须带交易所前缀（纯代码被上游 400 拒绝）。"""
    assert roic_api.resolve_identifier("00700", "H") == "HKEX:700"
    assert roic_api.resolve_identifier("1024", "H") == "HKEX:1024"


def test_roic_request_injects_apikey(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归：_request 必须自动携带 apikey（曾漏带导致所有调用 401）。"""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(roic_api, "load_api_key", lambda: "k123")

    class FakeResp:
        status_code = 200

        def __init__(self, url: str) -> None:
            self._url = url

        def json(self) -> dict:
            if self._url.endswith("/raw"):
                return {"text": "RAWBODY"}
            return {"data": []}

    def fake_get(url: str, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResp(url)

    monkeypatch.setattr(roic_api.requests, "get", fake_get)

    roic_api.list_recent("HKEX:700")

    assert captured["params"]["apikey"] == "k123"
    assert captured["params"]["identifier"] == "HKEX:700"
    assert captured["url"].endswith("/company-events")

    roic_api.fetch_raw("trraw_x")

    assert captured["url"].endswith("/documents/transcripts/trraw_x/raw")


def test_roic_identifier_us_uses_edgar_exchange(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """US 交易所前缀来自 EDGAR 元数据并永久缓存，只请求一次。"""
    monkeypatch.setattr(roic_api, "_symbols_cache_path", lambda: tmp_path / "roic_symbols.json")

    class FakeResp:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"exchanges": ["Nasdaq"]}

    calls: list[str] = []

    def fake_get(url: str, **kw):
        calls.append(url)
        return FakeResp()

    monkeypatch.setattr(roic_api.requests, "get", fake_get)

    assert roic_api.resolve_identifier("ROST", "US", "0000745732") == "NASDAQ:ROST"
    assert roic_api.resolve_identifier("ROST", "US", "0000745732") == "NASDAQ:ROST"
    assert len(calls) == 1


def test_query_transcripts_period_roic_rate_limit_note(monkeypatch: pytest.MonkeyPatch) -> None:
    """指定财季缺稿且 ROIC 限流时，note 附等待秒数。"""
    monkeypatch.setattr(transcripts, "normalize_stock_code", lambda code: "AAPL")
    monkeypatch.setattr(
        transcripts, "resolve_company", lambda code: ("AAPL", [{"market": "US", "code": "AAPL"}])
    )
    monkeypatch.setattr(
        transcripts,
        "sync_transcripts",
        lambda _c, _t, **kw: {
            "items": [{"fiscal_quarter": "FY2026-Q3", "status": "missing"}],
            "new": 0,
            "roic": {
                "source": "roic",
                "rate_limited": {"retry_after_seconds": 12, "reset_epoch": 1},
            },
        },
    )

    result = transcripts.query_transcripts("AAPL", period="FY2026-Q3")

    assert "12 秒后可重试" in result["note"]
    assert result["results"][0]["status"] == "missing"


def test_query_transcripts_by_period(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import json

    body_file = tmp_path / "FY2026-Q2.json"
    body_file.write_text(
        json.dumps({"meta": {"source": "stockanalysis"}, "body": [{"author": "CEO", "text": "hi"}]}),
        encoding="utf-8",
    )
    items = [
        {"fiscal_quarter": "FY2026-Q2", "report_date": "2026-03-31", "status": "ok",
         "body_file": str(body_file)},
    ]
    monkeypatch.setattr(transcripts, "normalize_stock_code", lambda code: "AAPL")
    monkeypatch.setattr(
        transcripts, "resolve_company", lambda code: ("AAPL", [{"market": "US", "code": "AAPL"}])
    )
    monkeypatch.setattr(transcripts, "sync_transcripts", lambda _c, _t, **kw: {"items": items, "new": 0})

    result = transcripts.query_transcripts("AAPL", period="FY2026-Q2")
    assert result["matched"] == 1
    assert result["body"][0]["author"] == "CEO"


def test_query_transcripts_period_missing_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcripts, "normalize_stock_code", lambda code: "AAPL")
    monkeypatch.setattr(
        transcripts, "resolve_company", lambda code: ("AAPL", [{"market": "US", "code": "AAPL"}])
    )
    monkeypatch.setattr(
        transcripts,
        "sync_transcripts",
        lambda _c, _t, **kw: {"items": [{"fiscal_quarter": "FY2026-Q2", "status": "missing"}], "new": 0},
    )
    result = transcripts.query_transcripts("AAPL", period="FY2025-Q1")
    assert result["matched"] == 0
    assert "索引里没有" in result["note"]


def test_search_transcripts_finds_keyword(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import json

    body_file = tmp_path / "FY2026-Q2.json"
    body_file.write_text(
        json.dumps(
            {
                "meta": {"source": "stockanalysis"},
                "body": [
                    {"author": "CEO", "text": "We delivered record revenue this quarter."},
                    {"author": "CFO", "text": "Margins expanded."},
                ],
            }
        ),
        encoding="utf-8",
    )
    items = [{"fiscal_quarter": "FY2026-Q2", "status": "ok", "body_file": str(body_file)}]
    monkeypatch.setattr(transcripts, "normalize_stock_code", lambda code: "AAPL")
    monkeypatch.setattr(
        transcripts, "resolve_company", lambda code: ("AAPL", [{"market": "US", "code": "AAPL"}])
    )
    monkeypatch.setattr(transcripts, "load_transcripts", lambda _code: {"items": items, "meta": {}})

    result = transcripts.search_transcripts("AAPL", "record revenue")
    assert result["matched"] == 1
    assert result["results"][0]["segments"][0]["author"] == "CEO"
