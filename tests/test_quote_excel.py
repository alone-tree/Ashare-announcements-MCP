"""内地公共入口的业务回归：整包、复权、缓存隔离、增量和字段失败。"""
import json
import re
from datetime import date, timedelta

import pytest

from market_data_mcp import cache, company_ifind_service, data_store, quote_excel, service
from market_data_mcp.providers import excel
from market_data_mcp.routing import parse_code


@pytest.fixture
def source(monkeypatch):
    calls = []
    monkeypatch.setattr(company_ifind_service, "get_quote_security", lambda root, mc: {
        "股份类型": "B股" if mc.code == "200725" else "A股", "交易所": "深交所", "上市日期": "20200101"})

    def fetch(root, mc, start, end, security):
        calls.append((mc, start, end, security))
        days = [(date.fromisoformat(start) + timedelta(days=i)).isoformat()
                for i in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)]
        data = {}
        for field in excel.FIELDS:
            records = []
            for i, day in enumerate(days):
                weekday = date.fromisoformat(day).weekday()
                value = {"amount": 0 if weekday >= 5 else 1000,
                    "turnover": 2.5, "company_total_shares": 10000, "security_total_shares": 6000,
                    "company_total_market_cap": 100000, "security_total_market_cap": 60000}.get(field)
                if value is None:
                    value = 10 + date.fromisoformat(day).day
                    if field == "close_no_forward":
                        # 0=周末节假日休市；停牌日不模拟为0（依据 docs/内地行情开市日过滤与后复权收盘切换方案-2026-11-06.md）。
                        value = 0 if weekday >= 5 else value * 5
                    elif field.endswith("_hfq"):
                        value *= 5
                records.append({"date": day, "value": value, "source": excel.SOURCE})
            data[field] = records
        return {"ok": True, "source": excel.SOURCE, "data": data, "notes": []}

    monkeypatch.setattr(excel, "fetch_quote", fetch)
    return calls


def test_public_entry_one_batch_all_fields_and_cache_hit(tmp_path, monkeypatch, source):
    root = str(tmp_path)
    result = service.get_quote(root, "300308.SZ", vars=["close"], adjust="qfq",
        start_date="2026-10-30", end_date="2026-11-02")
    assert result["ok"] and result["source"] == "ifind_excel"
    assert len(source) == 1
    assert [r["date"] for r in result["rows"]] == ["2026-10-30", "2026-11-02"]
    assert result["rows"][-1]["close"] == 12
    for field in excel.FIELDS:
        assert cache.read_cache(root, "300308.SZ", field)["meta"]["source"] == excel.SOURCE
    monkeypatch.setattr(company_ifind_service, "get_quote_security", lambda *a: pytest.fail("命中缓存不取证券资料"))
    again = service.get_quote(root, "300308.SZ", vars=["security_total_shares", "company_total_market_cap", "turnover"],
        start_date="2026-10-30", end_date="2026-11-02")
    assert len(source) == 1 and again["rows"][0]["security_total_shares"] == 6000
    assert again["rows"][0]["turnover"] == 0.025


def test_old_source_never_satisfies_excel_cache(tmp_path, source):
    root = str(tmp_path)
    cache.write_cache(root, "300308.SZ", "close", meta={"source": "sina",
        "date_range": {"start": "2020-01-01", "end": "2030-01-01"}},
        items=[{"date": "2026-11-03", "value": 999, "source": "sina"}])
    result = service.get_quote(root, "300308.SZ", start_date="2026-11-03", end_date="2026-11-04")
    assert result["rows"][0]["close"] == 13 and len(source) == 1
    assert all(row["source"] == excel.SOURCE for row in cache.read_cache(root, "300308.SZ", "close")["items"])


def test_incremental_only_once_from_previous_end(tmp_path, source):
    root = str(tmp_path)
    service.get_quote(root, "300308.SZ", start_date="2026-11-02", end_date="2026-11-03")
    for field in excel.FIELDS:
        path = tmp_path / "cache" / "300308.SZ" / cache.DATA_FILES[field]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["meta"]["updated_at"] = "2000-01-01T00:00:00"
        path.write_text(json.dumps(payload), encoding="utf-8")
    result = service.get_quote(root, "300308.SZ", vars=["open", "close", "amount", "company_total_shares"],
        start_date="2026-11-02", end_date="2026-11-05")
    assert len(source) == 2 and source[-1][1:3] == ("2026-11-03", "2026-11-05")
    assert [r["date"] for r in result["rows"]] == ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]


def test_all_history_reuses_listing_start_cache(tmp_path, source):
    # 只截取上市日附近，避免测试生成无意义长历史。
    root = str(tmp_path)
    result = service.get_quote(root, "300308.SZ", start_date="all", end_date="2020-01-03")
    assert result["ok"] and source[0][1] == "2020-01-01"
    service.get_quote(root, "300308.SZ", start_date="all", end_date="2020-01-03")
    assert len(source) == 1


def test_all_history_backfills_partial_skeleton_cache(tmp_path, source):
    """方案-2026-11-06：骨架缓存起点晚于上市日时，start=all 从上市日补缺口而非静默缩水。"""
    root = str(tmp_path)
    data_store.write(root, "300308.SZ", "company_data", "security", {
        "meta": {"schema_version": 2, "source": "ifind"},
        "data": {"股份类型": "A股", "交易所": "深交所", "上市日期": "20200101"},
        "checked_at": "2026-11-06T00:00:00+00:00"})
    service.get_quote(root, "300308.SZ", start_date="2026-11-03", end_date="2026-11-04")
    result = service.get_quote(root, "300308.SZ", start_date="all", end_date="2020-01-05")
    assert source[-1][1:3] == ("2020-01-01", "2020-01-05")
    assert result["ok"] and result["date_range"]["start"] == "2020-01-01"


@pytest.mark.parametrize("code,indicator", [("300308.SZ", "ths_total_ashare_stock"),
    ("200725.SZ", "ths_total_bshare_stock"), ("920002.BJ", "ths_total_ashare_stock")])
def test_formula_matrix_share_type_and_layout(code, indicator):
    market = {"300308.SZ": "A", "200725.SZ": "A", "920002.BJ": "BJ"}[code]
    fields, matrix = excel.formulas(code, ["2026-11-03", "2026-11-04"],
        "B股" if code == "200725.SZ" else "A股", market)
    assert len(matrix) == 2 and len(matrix[0]) == len(fields) == 13
    assert not {"open_hfq", "high_hfq", "low_hfq"} & set(fields)
    assert indicator in matrix[0][fields.index("security_total_shares")]
    assert '"2026-11-03"' in matrix[0][fields.index("open")]
    assert '"ths_market_value_stock"' in matrix[0][fields.index("company_total_market_cap")]
    assert '"ths_mv_sec_oriented_stock"' in matrix[0][fields.index("security_total_market_cap")]


def test_missing_classification_does_not_guess():
    fields, matrix = excel.formulas("200725.SZ", ["2026-11-04"], None, "A")
    assert "security_total_shares" not in fields and "close" in fields


def test_failure_never_falls_back_to_legacy_source(tmp_path, monkeypatch):
    monkeypatch.setattr(company_ifind_service, "get_quote_security", lambda *a: {"股份类型": "A股"})
    monkeypatch.setattr(excel, "fetch_quote", lambda *a: {"ok": False, "error": "插件不可用"})
    monkeypatch.setattr(service.sina, "fetch_raw", lambda *a, **k: pytest.fail("不应回退新浪"))
    result = service.get_quote(str(tmp_path), "300308.SZ", start_date="2026-11-03", end_date="2026-11-04")
    assert not result["ok"] and "插件不可用" in result["error"]


@pytest.mark.parametrize("kwargs", [{"vars": ["outstanding_share"]}, {"vars": ["float_market_cap"]},
    {"vars": []}, {"start_date": "bad"}, {"start_date": "2026-11-05", "end_date": "2026-11-04"}])
def test_invalid_input_never_fetches(tmp_path, monkeypatch, kwargs):
    monkeypatch.setattr(excel, "fetch_quote", lambda *a: pytest.fail("非法参数不应取数"))
    assert not service.get_quote(str(tmp_path), "300308.SZ", **kwargs)["ok"]


def test_minimal_security_only_three_fields_and_cache(tmp_path, monkeypatch):
    calls = []
    def basic(root, mc, fields):
        calls.append(fields)
        return {"交易所": "深交所", "股份类型": "B股", "上市日期": "19970610"}
    monkeypatch.setattr(company_ifind_service.company_ifind, "basic", basic)
    mc = parse_code("200725.SZ")
    assert company_ifind_service.get_quote_security(str(tmp_path), mc)["股份类型"] == "B股"
    company_ifind_service.get_quote_security(str(tmp_path), mc)
    assert len(calls) == 1 and len(calls[0]) == 3
    assert not (tmp_path / "cache" / "companies.json").exists()


def test_one_year_exports_only_requested_column(tmp_path, source):
    result = service.get_quote(str(tmp_path), "300308.SZ", vars=["close"], adjust="qfq",
        start_date="2025-11-05", end_date="2026-11-05")
    assert result["auto_exported"] and result["total_items"] > 200 and len(source) == 1
    assert open(result["path"], encoding="utf-8-sig").readline().strip() == "date,close"
    name = result["path"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    assert "_close_" in name and re.search(r"_\d{8}-\d{6}_[0-9a-f]{4}\.csv$", name)


def test_auto_export_names_never_collide(tmp_path, source):
    first = service.get_quote(str(tmp_path), "300308.SZ", vars=["close"], adjust="qfq",
        start_date="2025-11-05", end_date="2026-11-05")
    second = service.get_quote(str(tmp_path), "300308.SZ", vars=["close"], adjust="qfq",
        start_date="2025-11-05", end_date="2026-11-05")
    assert first["path"] != second["path"]


def test_matrix_error_column_does_not_become_successful_empty_cache(tmp_path, monkeypatch):
    columns, _ = excel.formulas("300308.SZ", ["2026-11-04"], "A股", "A")
    values = [[100 if f == "amount" else 10 for f in columns]]
    bad = columns.index("security_total_market_cap")
    values[0][bad] = None
    monkeypatch.setattr(excel.ifind_excel, "fetch_matrix", lambda *a, **k: {
        "values": values, "errors": [{"row": 0, "column": bad, "error": "参数错误"}]})
    result = excel.fetch_quote(str(tmp_path), parse_code("300308.SZ"),
        "2026-11-04", "2026-11-04", {"股份类型": "A股"})
    assert "close" in result["data"] and "security_total_market_cap" not in result["data"]
    assert "参数错误" in result["notes"][0]


def test_weekly_amount_volume_turnover_and_company_fields(tmp_path, source):
    result = service.get_quote(str(tmp_path), "300308.SZ",
        vars=["close", "volume", "amount", "turnover", "company_total_shares", "security_total_market_cap"],
        start_date="2026-11-02", end_date="2026-11-05", period="weekly")
    row = result["rows"][0]
    assert row["amount"] == 4000 and row["turnover"] == 0.1
    assert row["close"] == 15 and row["company_total_shares"] == 10000
    assert row["security_total_market_cap"] == 60000


def test_zero_calendar_tail_does_not_freeze_today_forever(tmp_path, monkeypatch, source):
    original = excel.fetch_quote
    def missing_tail(*args):
        result = original(*args)
        result["data"]["close_no_forward"][-1]["value"] = 0
        return result
    monkeypatch.setattr(excel, "fetch_quote", missing_tail)
    root = str(tmp_path)
    service.get_quote(root, "300308.SZ", start_date="2026-11-03", end_date="2026-11-05")
    for field in excel.FIELDS:
        path = tmp_path / "cache" / "300308.SZ" / cache.DATA_FILES[field]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["meta"]["updated_at"] = "2000-01-01T00:00:00"
        path.write_text(json.dumps(payload), encoding="utf-8")
    service.get_quote(root, "300308.SZ", start_date="2026-11-03", end_date="2026-11-05")
    assert len(source) == 2 and source[-1][1] == "2026-11-04"


def test_formula_close_no_forward_replaces_close_hfq_and_raw_close_kept():
    fields, matrix = excel.formulas("300308.SZ", ["2026-11-04"], "A股", "A")
    assert "close_no_forward" in fields and "close_hfq" not in fields
    assert "avg_price_hfq" in fields and "open_hfq" not in fields
    no_forward = matrix[0][fields.index("close_no_forward")]
    assert '"close_no_forward"' in no_forward and ",107)" in no_forward
    raw_close = matrix[0][fields.index("close")]
    assert '"ths_close_price_stock"' in raw_close and ",100," in raw_close


def test_suspension_days_kept_and_market_closed_dropped(tmp_path, monkeypatch):
    """方案-2026-11-06：no_fwd>0 的停牌日保留且量额换手为0；no_fwd=0 的周末剔除。"""
    monkeypatch.setattr(company_ifind_service, "get_quote_security",
        lambda root, mc: {"股份类型": "A股", "上市日期": "20200101"})

    def fetch(root, mc, start, end, security):
        days = [(date.fromisoformat(start) + timedelta(days=i)).isoformat()
                for i in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)]
        data = {}
        for field in excel.FIELDS:
            records = []
            for day in days:
                d = date.fromisoformat(day)
                weekend = d.weekday() >= 5
                suspended = day == "2026-11-05"
                price = 10 + d.day
                value = {"amount": 0 if weekend or suspended else 1000,
                    "turnover": 0 if weekend or suspended else 2.5,
                    "company_total_shares": 10000, "security_total_shares": 6000,
                    "company_total_market_cap": 100000, "security_total_market_cap": 60000}.get(field)
                if value is None:
                    if field == "close_no_forward":
                        value = 0 if weekend else price * 5
                    elif field.endswith("_hfq"):
                        value = price * 5
                    else:
                        value = price
                records.append({"date": day, "value": value, "source": excel.SOURCE})
            data[field] = records
        return {"ok": True, "source": excel.SOURCE, "data": data, "notes": []}

    monkeypatch.setattr(excel, "fetch_quote", fetch)
    result = service.get_quote(str(tmp_path), "300308.SZ",
        vars=["close", "volume", "amount", "turnover"],
        start_date="2026-11-02", end_date="2026-11-08", adjust="qfq")
    dates = [r["date"] for r in result["rows"]]
    assert dates == ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    susp = result["rows"][3]
    assert susp["date"] == "2026-11-05"
    assert susp["close"] == pytest.approx(15.0)
    assert susp["volume"] == 0 and susp["amount"] == 0 and susp["turnover"] == 0.0


def test_hk_formula_matrix_thirteen_columns():
    fields, matrix = excel.formulas("0700.HK", ["2026-11-04"], None, "HK")
    assert len(matrix[0]) == len(fields) == 13
    assert '"ths_open_price_hks"' in matrix[0][fields.index("open")]
    assert '"ths_high_d_hks"' in matrix[0][fields.index("high")]
    assert '"ths_low_d_hks"' in matrix[0][fields.index("low")]
    assert '"ths_close_price_hks"' in matrix[0][fields.index("close")]
    assert ',101,"")' in matrix[0][fields.index("avg_price_hfq")]
    assert ',107)' in matrix[0][fields.index("close_no_forward")]
    assert '"ths_sec_total_shares_hks"' in matrix[0][fields.index("security_total_shares")]
    assert '"ths_corp_total_shares_hks"' in matrix[0][fields.index("company_total_shares")]
    mv = matrix[0][fields.index("company_total_market_cap")]
    assert '"ths_market_value_hks"' in mv and '"HKD"' in mv
    sec_mv = matrix[0][fields.index("security_total_market_cap")]
    assert '"ths_totalcapitalforsecurities_hk"' in sec_mv and '"HKD"' in sec_mv


def test_hk_block_zero_fault_closes_excel_and_retries(tmp_path, monkeypatch):
    columns, _ = excel.formulas("0700.HK", ["2026-11-04"], None, "HK")
    calls = {"n": 0, "closed": 0, "visible": []}

    def fake_fetch(matrix, *, visible=None, text_ok=False, timeout=600):
        calls["n"] += 1
        calls["visible"].append(visible)
        if calls["n"] == 1:
            return {"values": [[0] * len(columns)], "errors": []}
        return {"values": [[10] * len(columns)], "errors": []}

    def fake_close(*a, **k):
        calls["closed"] += 1
        return {}

    monkeypatch.setattr(excel.ifind_excel, "fetch_matrix", fake_fetch)
    monkeypatch.setattr(excel.ifind_excel, "close_excel", fake_close)
    result = excel.fetch_quote(str(tmp_path), parse_code("00700.HK"),
        "2026-11-04", "2026-11-04", {})
    assert calls == {"n": 2, "closed": 1, "visible": [True, True]}
    assert result["ok"] and result["data"]["close"][0]["value"] == 10


def test_a_share_row_zero_fault_closes_excel_and_retries(tmp_path, monkeypatch):
    columns, _ = excel.formulas("300308.SZ", ["2026-11-04", "2026-11-05"], "A股", "A")
    normal = [10] * len(columns)
    bad = [10] * len(columns)
    for f in ("open", "high", "low", "close", "close_no_forward"):
        bad[columns.index(f)] = 0
    calls = {"n": 0, "closed": 0}

    def fake_fetch(matrix, *, visible=None, text_ok=False, timeout=600):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"values": [normal[:], bad[:]], "errors": []}
        return {"values": [normal[:], normal[:]], "errors": []}

    def fake_close(*a, **k):
        calls["closed"] += 1
        return {}

    monkeypatch.setattr(excel.ifind_excel, "fetch_matrix", fake_fetch)
    monkeypatch.setattr(excel.ifind_excel, "close_excel", fake_close)
    result = excel.fetch_quote(str(tmp_path), parse_code("300308.SZ"),
        "2026-11-04", "2026-11-05", {"股份类型": "A股", "上市日期": "20200101"})
    assert calls == {"n": 2, "closed": 1}
    assert result["ok"] and result["data"]["close"][1]["value"] == 10


def test_hk_listing_date_via_excel_text_mode(tmp_path, monkeypatch):
    calls = {}

    def fake_fetch_formulas(formulas, *, text_ok=False, visible=None, timeout=120):
        calls["formulas"] = formulas
        calls["text_ok"] = text_ok
        calls["count"] = calls.get("count", 0) + 1
        return {"values": ["2004-06-16"], "metrics": {}}

    from market_data_mcp import ifind_excel as ifind_excel_module
    monkeypatch.setattr(ifind_excel_module, "fetch_formulas", fake_fetch_formulas)
    monkeypatch.setattr(ifind_excel_module, "close_excel",
        lambda **kwargs: pytest.fail("有效的一维日期返回不应触发关闭重试"))
    mc = parse_code("00700.HK")
    data = company_ifind_service.get_quote_security(str(tmp_path), mc)
    assert data == {"上市日期": "20040616"}
    assert calls["text_ok"] is True
    assert "ths_ipo_date_hks" in calls["formulas"][0] and '"0700.HK"' in calls["formulas"][0]
    again = company_ifind_service.get_quote_security(str(tmp_path), mc)
    assert again == {"上市日期": "20040616"} and calls["count"] == 1


def test_hk_invalid_listing_date_reports_complete_text(tmp_path, monkeypatch):
    from market_data_mcp import ifind_excel

    calls = {"fetch": 0, "closed": 0}

    def fetch(formulas, **kwargs):
        calls["fetch"] += 1
        return {"values": ["invalid-date"]}

    def close(**kwargs):
        calls["closed"] += 1

    monkeypatch.setattr(ifind_excel, "fetch_formulas", fetch)
    monkeypatch.setattr(ifind_excel, "fetch_matrix", lambda *args, **kwargs: {})
    monkeypatch.setattr(ifind_excel, "close_excel", close)
    monkeypatch.setattr(company_ifind_service.time, "sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="港股上市日期返回异常：'invalid-date'"):
        company_ifind_service.get_quote_security(str(tmp_path), parse_code("00700.HK"))
    assert calls == {"fetch": 3, "closed": 2}
    assert not data_store.read(str(tmp_path), "00700.HK", "company_data", "security", "ifind_excel")


def test_hk_routes_to_excel_and_hkd_units(tmp_path, monkeypatch):
    monkeypatch.setattr(company_ifind_service, "get_quote_security",
        lambda root, mc: {"上市日期": "20040616"})
    captured = {}

    def fetch(root, mc, start, end, security):
        captured["market"] = mc.market
        captured["ipo"] = (security or {}).get("上市日期")
        days = ["2026-11-04", "2026-11-05"]
        data = {field: [{"date": d, "value": 10 + i, "source": excel.SOURCE}
                        for i, d in enumerate(days)] for field in excel.FIELDS}
        return {"ok": True, "source": excel.SOURCE, "data": data, "notes": []}

    monkeypatch.setattr(excel, "fetch_quote", fetch)
    result = service.get_quote(str(tmp_path), "00700.HK", vars=["close", "amount"],
        start_date="2026-11-04", end_date="2026-11-05")
    assert captured["market"] == "HK" and captured["ipo"] == "20040616"
    assert result["ok"] and result["source"] == excel.SOURCE
    assert result["units"]["close"] == "港元" and result["units"]["amount"] == "港元"


def test_a_share_suspension_row_survives_factor_restore(tmp_path, monkeypatch):
    """13列后停牌行保留：hfq close=cnf直取、OHL=raw×F(t)、hfq量=额÷后复权均价。"""
    monkeypatch.setattr(company_ifind_service, "get_quote_security",
        lambda root, mc: {"股份类型": "A股", "上市日期": "20200101"})
    days = ["2026-11-04", "2026-11-05", "2026-11-06"]
    price = {"2026-11-04": 10, "2026-11-05": 15, "2026-11-06": 20}

    def fetch(root, mc, start, end, security):
        data = {}
        for field in excel.FIELDS:
            records = []
            for d in days:
                p = price[d]
                suspended = d == "2026-11-05"
                base = {"amount": 0 if suspended else 1000,
                        "turnover": 0 if suspended else 2.5,
                        "company_total_shares": 10000, "security_total_shares": 6000,
                        "company_total_market_cap": 100000,
                        "security_total_market_cap": 60000}.get(field)
                if base is None:
                    if field == "close_no_forward":
                        base = p * 5
                    elif field == "avg_price_hfq":
                        base = p * 5
                    elif field.endswith("_hfq"):
                        base = p * 5
                    else:
                        base = p
                records.append({"date": d, "value": base, "source": excel.SOURCE})
            data[field] = records
        return {"ok": True, "source": excel.SOURCE, "data": data, "notes": []}

    monkeypatch.setattr(excel, "fetch_quote", fetch)
    result = service.get_quote(str(tmp_path), "300308.SZ",
        vars=["open", "close", "volume"], adjust="hfq",
        start_date="2026-11-04", end_date="2026-11-06")
    rows = result["rows"]
    assert [r["close"] for r in rows] == [50.0, 75.0, 100.0]
    assert rows[1]["open"] == 75.0 and rows[1]["volume"] == 0.0
    assert rows[0]["volume"] == 20.0  # hfq量=额÷后复权均价（脑图口径）
