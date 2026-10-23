"""新契约的依赖、缓存、部分失败与真实输出验证（不联网）。"""
from datetime import datetime, timedelta, timezone
import json

import pytest

from market_data_mcp import data_store, financial_service as fs, market_help


def report(period, values, statement="income"):
    labels = {"03-31": "一季报", "06-30": "中报", "09-30": "三季报", "12-31": "年报"}
    return {"report_date": period,
            "metadata": {"REPORT_TYPE": labels[period[5:]], "CURRENCY": "CNY", "NOTICE_DATE": "2025-10-20"},
            "items": [{"item_code": key, "item_name": key, "amount": value, "source": "eastmoney"}
                      for key, value in values.items()]}


@pytest.fixture
def source(monkeypatch):
    calls = []
    records = [report("2024-06-30", {"OPERATE_INCOME": 100, "OPERATE_COST": 60}),
               report("2024-09-30", {"OPERATE_INCOME": 180, "OPERATE_COST": 100}),
               report("2024-12-31", {"OPERATE_INCOME": 300, "OPERATE_COST": 180}),
               report("2025-03-31", {"OPERATE_INCOME": 90, "OPERATE_COST": 45}),
               report("2025-06-30", {"OPERATE_INCOME": 210, "OPERATE_COST": 100}),
               report("2025-09-30", {"OPERATE_INCOME": 390, "OPERATE_COST": 190})]
    def fetch(root, mc, statement):
        calls.append(statement)
        return records
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", fetch)
    return calls, records


def test_single_dependencies_not_exposed_and_shared_fetch(tmp_path, source):
    calls, records = source
    result = fs.get_financial_data(str(tmp_path), "600519.SH", "single", periods=["2025-09-30"],
                                   items=["营业收入", "毛利率"])
    assert result["ok"] and calls == ["income"]
    assert {r["report_date"] for r in result["rows"]} == {"2025-09-30"}
    amounts = {r["item_name"]: r["amount"] for r in result["rows"]}
    assert amounts["营业收入"] == 180
    assert amounts["毛利率"] == pytest.approx(0.5)
    fs.get_financial_data(str(tmp_path), "600519.SH", "single", periods=["2025-09-30"], items=["毛利率"])
    assert calls == ["income"]


def test_default_five_and_growth_auto_dependencies(tmp_path, source):
    result = fs.get_financial_data(str(tmp_path), "600519.SH", "single", items=["营业收入同比增长率", "营业收入环比增长率"])
    assert len(result["periods"]) == 5
    last = {r["item_name"]: r["amount"] for r in result["rows"] if r["report_date"] == "2025-09-30"}
    assert last["营业收入同比增长率"] == pytest.approx(1.25)
    assert last["营业收入环比增长率"] == pytest.approx(0.5)
    assert not any(r["report_date"] == "2024-06-30" for r in result["rows"])


def test_missing_cost_isolated(tmp_path, source):
    calls, records = source
    for record in records:
        record["items"] = [i for i in record["items"] if i["item_code"] != "OPERATE_COST"]
    result = fs.get_financial_data(str(tmp_path), "600519.SH", "single", periods=["2025-09-30"], items=["营业收入", "毛利率"])
    assert result["ok"] and result["status"] == "partial_success"
    assert len(result["rows"]) == 1
    assert result["failed_items"][0]["item"] == "毛利率"


def test_checked_empty_ttl_and_new_scope(tmp_path, source):
    calls, records = source
    fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", periods=["2025-12-31"], items=["营业收入"])
    fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", periods=["2025-12-31"], items=["营业收入"])
    assert calls == ["income"]
    fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", periods=["2023-12-31"], items=["营业收入"])
    assert calls == ["income", "income"]
    payload = data_store.read(str(tmp_path), "600519.SH", fs.DOMAIN, "income")
    payload["checks"]["2025-12-31"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    data_store.write(str(tmp_path), "600519.SH", fs.DOMAIN, "income", payload)
    fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", periods=["2025-12-31"], items=["营业收入"])
    assert len(calls) == 3


def test_refresh_failure_keeps_values_and_checked_time(tmp_path, monkeypatch, source):
    result = fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", periods=["2025-09-30"], items=["营业收入"])
    before = data_store.read(str(tmp_path), "600519.SH", fs.DOMAIN, "income")
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", lambda *args: (_ for _ in ()).throw(RuntimeError("upstream failed")))
    stale = fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", periods=["2025-09-30"], items=["营业收入"], force_refresh=True)
    assert stale["ok"] and stale["stale"]
    assert stale["rows"][0]["amount"] == result["rows"][0]["amount"]
    assert data_store.read(str(tmp_path), "600519.SH", fs.DOMAIN, "income") == before


def test_all_items_export_and_observed_versions(tmp_path, source):
    calls, records = source
    args = dict(periods=["2025-09-30"], statements=["income"], items=["ALL_ITEMS"])
    fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", **args)
    records[-1]["items"][0]["amount"] = 400
    result = fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", **args,
        include_versions=True, force_refresh=True, export_path=str(tmp_path / "out.csv"))
    assert result["ok"] and result["total_items"] == 4
    assert (tmp_path / "out.csv").is_file()
    assert "version_id" in (tmp_path / "out.csv").read_text(encoding="utf-8-sig")
    assert not any("ths_" in i["item_code"] for r in data_store.read(str(tmp_path), "600519.SH", fs.DOMAIN, "income")["reports"] for i in r["versions"][-1]["items"])


def test_help_pure_local_no_directory_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", lambda *args: pytest.fail("不应联网"))
    result = market_help.get_market_data_help(str(tmp_path), code="600519.SH", topic="cache")
    assert result["ok"] and result["cache"] == []
    assert list(tmp_path.iterdir()) == []


def test_segments_checked_empty_not_retried_and_single_note(tmp_path, monkeypatch, source):
    calls = []
    monkeypatch.setattr(fs.company_ifind, "latest_report", lambda *args: "2025-09-30")
    monkeypatch.setattr(fs.company_ifind, "segments", lambda *args: calls.append(1) or [{"rank": 1, "name": "产品", "income": 0, "gross_profit": None}])
    args = dict(periods=["2025-09-30"], items=["income by product"])
    a = fs.get_financial_data(str(tmp_path), "600519.SH", "single", **args)
    b = fs.get_financial_data(str(tmp_path), "600519.SH", "single", **args)
    assert a["ok"] and a["segments"][0]["income"] == 0
    assert a["notes"] and len(calls) == 1


def test_noncalendar_report_date_accepted(tmp_path):
    from market_data_mcp.financial_contract import validate_financial_request
    assert validate_financial_request("AAPL.US", "single", ["2025-09-27"], None, None).market == "US"


def test_all_items_allows_explicit_ratio(tmp_path, source):
    result = fs.get_financial_data(str(tmp_path), "600519.SH", "single", statements=["income"],
        periods=["2025-09-30"], items=["ALL_ITEMS", "毛利率"])
    assert result["ok"]
    assert len(result["rows"]) == 3
    assert next(r for r in result["rows"] if r["item_name"] == "毛利率")["unit"] == "ratio"


def test_partial_write_failure_does_not_rollback_other_table(tmp_path, monkeypatch, source):
    original = data_store.write
    def write(root, code, domain, module, payload):
        if module == "balance":
            raise OSError("模拟写失败")
        return original(root, code, domain, module, payload)
    monkeypatch.setattr(data_store, "write", write)
    result = fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", periods=["2025-09-30"],
        statements=["balance", "income"], items=["ALL_ITEMS"])
    assert result["ok"] and result["status"] == "partial_success"
    assert data_store.read(str(tmp_path), "600519.SH", fs.DOMAIN, "income") is not None
    assert data_store.read(str(tmp_path), "600519.SH", fs.DOMAIN, "balance") is None


def test_negative_growth_base_exposes_comparison_values(tmp_path, source):
    calls, records = source
    records[1]["items"][0]["amount"] = -10
    result = fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", periods=["2025-09-30"],
        items=["营业收入", "营业收入同比增长率"])
    assert result["ok"] and result["status"] == "partial_success"
    failure = next(f for f in result["failed_items"] if f["item"] == "营业收入同比增长率")
    assert failure["previous_amount"] == -10 and failure["current_amount"] == 390


def test_new_metrics_always_use_current_version(tmp_path, source):
    calls, records = source
    args = dict(periods=["2025-09-30"], items=["毛利率"], include_versions=True)
    fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", **args)
    records[-1]["items"][0]["amount"] = 400
    result = fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", force_refresh=True, **args)
    assert len(result["rows"]) == 1
    assert result["rows"][0]["amount"] == pytest.approx((400-190)/400)


def test_eastmoney_reads_all_announced_pages(monkeypatch):
    provider = fs.financial_statements
    calls = []
    def page(root, mc, api, params, headers):
        n = int(params.get("pageNumber") or 1)
        calls.append(n)
        return {"result": {"pages": 3, "data": [{"page": n}]}}
    monkeypatch.setattr(provider, "_request_page", page)
    result = provider._request_json("root", None, "reports", {})
    assert calls == [1, 2, 3]
    assert result["result"]["data"] == [{"page": 1}, {"page": 2}, {"page": 3}]


def test_profit_in_cashflow_does_not_ambiguate_income_profit(tmp_path, monkeypatch):
    def fetch(root, mc, statement):
        values = {"NETPROFIT": 30} if statement == "income" else {"NETPROFIT": 30, "NETCASH_OPERATE": 50}
        return [report("2025-09-30", values)]
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", fetch)
    result = fs.get_financial_data(str(tmp_path), "600519.SH", "cumulative", periods=["2025-09-30"],
        items=["合并净利润", "经营活动现金流量净额"])
    assert result["status"] == "success" and len(result["rows"]) == 2
    assert next(r for r in result["rows"] if r["statement"] == "income")["amount"] == 30
