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
