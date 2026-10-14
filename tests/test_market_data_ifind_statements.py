# -*- coding: utf-8 -*-
"""iFinD 三表切源单测（stub iFinDPy，不登录不联网）。

覆盖：科目注册表完整性、单期报告组装与全空判定、全历史回补的连续 8 期空停止、
增量（新增期 + 最新期重取）、service 层 A 股切源与契约渲染。
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

# iFinDPy 可能未安装（项目 venv）：先注入 stub 再导入被测模块
if "iFinDPy" not in sys.modules:
    sys.modules["iFinDPy"] = types.ModuleType("iFinDPy")

from market_data_mcp import financial_subjects  # noqa: E402
from market_data_mcp.providers import ifind as ifind_provider  # noqa: E402
from market_data_mcp.routing import MarketCode  # noqa: E402


# --- 科目注册表 ---

def test_subject_registry_shape():
    assert len(financial_subjects.SUBJECTS) == 318
    codes = [s["ths_code"] for s in financial_subjects.SUBJECTS]
    assert len(codes) == len(set(codes)), "科目码必须唯一"
    counts = {statement: len(financial_subjects.subjects_for(statement))
              for statement in ("balance", "income", "cash_flow")}
    assert counts == {"balance": 131, "income": 82, "cash_flow": 105}


def test_subject_registry_non_additive():
    non_additive = [s for s in financial_subjects.SUBJECTS if not s["additive"]]
    assert {s["ths_code"] for s in non_additive} == {
        "ths_basic_eps_stock",
        "ths_dlt_earnings_per_share_stock",
        "ths_regular_report_actual_dd_stock",
        "ths_audit_opinion_type_stock",
        "ths_ica_opinion_type_stock",
    }


def test_subject_display_and_resolve():
    assert financial_subjects.display_name("ths_np_dnrgal_stock") == "扣非净利润"
    assert financial_subjects.resolve_name("货币资金")["ths_code"] == "ths_currency_fund_stock"
    assert financial_subjects.resolve_name("不存在的科目") is None
    # 序号前缀已去除
    assert financial_subjects.resolve_name("一、营业总收入") is None
    assert financial_subjects.resolve_name("营业总收入")["ths_code"] == "ths_operating_total_revenue_stock"


# --- 测试工具 ---

class _FakeResult:
    def __init__(self, errorcode=0, data=None, errmsg=None):
        self.errorcode = errorcode
        self.data = data
        self.errmsg = errmsg


def _install_fake_ths(monkeypatch, responder):
    """替换 ifind 模块内的 THS_iFinDLogin / THS_BD。responder(full_code, indicators, params)。"""
    monkeypatch.setattr(ifind_provider.ths, "THS_iFinDLogin", lambda acc, pwd: 0, raising=False)
    monkeypatch.setattr(ifind_provider.ths, "THS_BD",
                        lambda full, inds, params: responder(full, inds, params), raising=False)
    monkeypatch.setitem(ifind_provider._LOGIN_STATE, "done", False)
    monkeypatch.setattr(ifind_provider, "_load_accounts", lambda root: [("acc", "pwd")])


def _mk_mc(code="600106", suffix="SH", market="A"):
    return MarketCode(code=code, suffix=suffix, market=market)


def _frame_for(full_code, indicators, period, values_by_code):
    """构造 THS_BD 成功返回（.errorcode/.data 属性对象，data 为单行 DataFrame）。"""
    import pandas as pd

    row = {"thsCode": full_code}
    for ind in indicators.split(";"):
        row[ind] = values_by_code.get(ind)
    return _FakeResult(errorcode=0, data=pd.DataFrame([row]))


# --- 单期报告组装 ---

def test_period_report_all_empty():
    all_codes, by_statement = ifind_provider._statement_codes()
    values = {code: None for code in all_codes}
    reports, all_empty = ifind_provider._period_report("2025-09-30", values, by_statement)
    assert all_empty is True
    assert set(reports) == {"balance", "income", "cash_flow"}


def test_period_report_metadata_and_items():
    all_codes, by_statement = ifind_provider._statement_codes()
    values = {code: None for code in all_codes}
    values["ths_currency_fund_stock"] = 1072245692.17
    values["ths_operating_total_revenue_stock"] = 56316328.4
    values[_AUDIT_DD := "ths_regular_report_actual_dd_stock"] = "2025-08-15 00:00:00"
    reports, all_empty = ifind_provider._period_report("2025-06-30", values, by_statement)
    assert all_empty is False
    balance = reports["balance"]
    assert balance["report_date"] == "2025-06-30"
    assert balance["metadata"]["REPORT_DATE_NAME"] == "2025半年报"
    assert balance["metadata"]["CURRENCY"] == "CNY"
    assert balance["metadata"]["NOTICE_DATE"] == "2025-08-15"
    fund = next(item for item in balance["items"] if item["item_code"] == "ths_currency_fund_stock")
    assert fund == {"item_code": "ths_currency_fund_stock", "item_name": "货币资金",
                    "amount": 1072245692.17, "source": "ifind"}
    income = reports["income"]
    assert income["metadata"]["REPORT_DATE_NAME"] == "2025半年报"
    revenue = next(item for item in income["items"]
                   if item["item_code"] == "ths_operating_total_revenue_stock")
    assert revenue["amount"] == 56316328.4


# --- 全历史回补 ---

def test_fetch_statements_backfill_stops_after_empty_streak(tmp_path, monkeypatch):
    all_codes, _ = ifind_provider._statement_codes()

    def responder(full, indicators, params):
        period = params.split(";")[0].split(",")[0]  # YYYYMMDD
        iso = f"{period[:4]}-{period[4:6]}-{period[6:]}"
        # 只有最近 6 个季度有数（由近及远数），更早全空
        if iso >= "2024-06-30":
            return _frame_for(full, indicators, period,
                              {"ths_currency_fund_stock": 1.0})
        return _frame_for(full, indicators, period, {})

    _install_fake_ths(monkeypatch, responder)
    fetched = ifind_provider.fetch_statements(str(tmp_path), _mk_mc())
    assert fetched["ok"] is True
    assert fetched["source"] == "ifind"
    balance = fetched["statements"]["balance"]
    dates = [report["report_date"] for report in balance]
    assert dates == sorted(dates), "报告期必须升序"
    # 2024-03-31 及更早全空：连续 8 期空停止 → 只保留 2024-06-30 起到今天为止的季末
    assert dates[0] == "2024-06-30"
    from datetime import date

    today_iso = date.today().isoformat()
    expected = sorted(d for d in ifind_provider._quarter_ends_desc(date.today())
                      if d <= today_iso and d >= "2024-06-30")
    assert dates == expected
    assert fetched["metadata"]["sources"]["statements"] == "ifind"
    assert any("全历史回补" in note for note in fetched["notes"])


def test_fetch_statements_no_data_fails(tmp_path, monkeypatch):
    all_codes, _ = ifind_provider._statement_codes()

    def responder(full, indicators, params):
        return _frame_for(full, indicators, params.split(";")[0].split(",")[0], {})

    _install_fake_ths(monkeypatch, responder)
    fetched = ifind_provider.fetch_statements(str(tmp_path), _mk_mc())
    assert fetched["ok"] is False
    assert "无任何报告期数据" in fetched["error"]


def test_fetch_statements_retries_then_raises(tmp_path, monkeypatch):
    calls = {"n": 0}

    def responder(full, indicators, params):
        calls["n"] += 1
        return _FakeResult(errorcode=-340, data=None, errmsg="瞬时错误")

    _install_fake_ths(monkeypatch, responder)
    monkeypatch.setattr(ifind_provider.time, "sleep", lambda s: None)
    fetched = ifind_provider.fetch_statements(str(tmp_path), _mk_mc())
    assert fetched["ok"] is False
    assert calls["n"] == 2, "失败须重试一次（共 2 次调用）"
    assert "THS_BD" in fetched["error"]


# --- 增量 ---

def _seed_cache(root, reports_balance):
    from market_data_mcp import financial_cache

    batch = "b0001"
    metadata = {"meta": {"code": "600106.SH", "market": "A", "update_batch_id": batch,
                         "last_successful_update": "2026-10-01T00:00:00"}}
    payloads = {}
    for statement in ("balance", "income", "cash_flow"):
        reports = reports_balance if statement == "balance" else []
        payloads[statement] = financial_cache.merge_statement(
            None, reports, code="600106.SH", market="A", statement=statement,
            source="ifind", observed_at="2026-10-01T00:00:00", batch_id=batch)
    financial_cache.commit_bundle(root, "600106.SH", metadata, payloads)


def test_fetch_statements_incremental_fetches_new_and_latest(tmp_path, monkeypatch):
    all_codes, by_statement = ifind_provider._statement_codes()
    requested_periods: list[str] = []

    def responder(full, indicators, params):
        period = params.split(";")[0].split(",")[0]
        requested_periods.append(period)
        iso = f"{period[:4]}-{period[4:6]}-{period[6:]}"
        return _frame_for(full, indicators, period,
                          {"ths_currency_fund_stock": 2.0 if iso >= "2026-09-30" else 1.0})

    _install_fake_ths(monkeypatch, responder)

    def make_report(period, amount):
        _, by_stmt = ifind_provider._statement_codes()
        values = {code: None for code in all_codes}
        values["ths_currency_fund_stock"] = amount
        reports, _ = ifind_provider._period_report(period, values, by_stmt)
        return reports["balance"]

    _seed_cache(tmp_path, [make_report("2025-12-31", 1.0), make_report("2026-03-31", 1.0),
                           make_report("2026-06-30", 1.0)])
    requested_periods.clear()
    fetched = ifind_provider.fetch_statements(str(tmp_path), _mk_mc())
    assert fetched["ok"] is True
    # 缓存最新 2026-06-30 → 取 2026-09-30（新增）+ 2026-06-30（最新期重取）
    assert sorted(set(requested_periods)) == ["20260630", "20260930"]
    balance_dates = sorted({report["report_date"] for report in fetched["statements"]["balance"]})
    assert balance_dates == ["2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]
    # 旧期原样携带（携带内容=缓存当前版本）
    assert fetched["statements"]["balance"][0]["items"][0]["amount"] == 1.0
    assert any("增量取 2 期" in note for note in fetched["notes"])


def test_fetch_statements_rebuilds_legacy_east_cache(tmp_path, monkeypatch):
    """旧东财科目码缓存 → 整体重建（全历史回补），不与新 iFinD 期混装。"""
    from market_data_mcp import financial_cache

    batch = "b0001"
    metadata = {"meta": {"code": "600106.SH", "market": "A", "update_batch_id": batch,
                         "last_successful_update": "2026-10-01T00:00:00"}}
    legacy_report = {
        "report_date": "2025-06-30",
        "metadata": {"REPORT": "2025中报", "CURRENCY": "CNY"},
        "items": [{"item_code": "MONETARYFUNDS", "item_name": "货币资金",
                   "amount": 1.0, "source": "eastmoney"}],
    }
    payloads = {}
    for statement in ("balance", "income", "cash_flow"):
        payloads[statement] = financial_cache.merge_statement(
            None, [legacy_report] if statement == "balance" else [],
            code="600106.SH", market="A", statement=statement,
            source="eastmoney", observed_at="2026-10-01T00:00:00", batch_id=batch)
    financial_cache.commit_bundle(tmp_path, "600106.SH", metadata, payloads)

    requested: list[str] = []

    def responder(full, indicators, params):
        period = params.split(";")[0].split(",")[0]
        requested.append(period)
        return _frame_for(full, indicators, period, {"ths_currency_fund_stock": 1.0})

    _install_fake_ths(monkeypatch, responder)
    fetched = ifind_provider.fetch_statements(str(tmp_path), _mk_mc())
    assert fetched["ok"] is True
    assert any("整体重建" in note for note in fetched["notes"])
    assert any("全历史回补" in note for note in fetched["notes"])
    assert len(requested) > 2, "必须走全历史回补而非 2 期增量"
    codes = {item["item_code"]
             for report in fetched["statements"]["balance"]
             for item in report["items"]}
    assert "MONETARYFUNDS" not in codes


# --- service 层切源与渲染契约 ---

def test_service_a_share_uses_ifind_and_renders(tmp_path, monkeypatch):
    from market_data_mcp import service

    all_codes, by_statement = ifind_provider._statement_codes()

    def fake_fetch(root, mc, existing_metadata=None):
        values = {code: None for code in all_codes}
        values["ths_currency_fund_stock"] = 1072245692.17
        values["ths_operating_total_revenue_stock"] = 56316328.4
        values["ths_np_atoopc_stock"] = 5631632.84
        reports, _ = ifind_provider._period_report("2025-06-30", values, by_statement)
        return {
            "ok": True,
            "source": "ifind",
            "statements": {statement: [reports[statement]] for statement in ("balance", "income", "cash_flow")},
            "metadata": {"code": "600106.SH", "market": "A",
                         "sources": {"statements": "ifind"}, "filings": []},
            "error": None,
            "notes": ["单测注入"],
        }

    monkeypatch.setattr(service.ifind, "fetch_statements", fake_fetch)
    result = service.get_financial_statements(
        str(tmp_path), "600106.SH", amount_basis="cumulative",
        statements=["income"], items=["营业总收入"],
    )
    assert result["ok"] is True
    assert result["source"] == "ifind"
    assert result["statements"] == ["income"]
    rows = result["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["item_name"] == "营业总收入"
    assert "item_code" not in row, "MCP 输出不外露内部科目码"
    assert row["amount"] == 56316328.4
    # 缓存四文件落盘（reports[].versions[].items）
    payload = json.loads((tmp_path / "cache" / "600106.SH" / "financial_statements" / "income.json").read_text(encoding="utf-8"))
    cached_items = payload["reports"][0]["versions"][0]["items"]
    assert cached_items[0]["item_code"] == "ths_operating_total_revenue_stock"


def test_service_items_filter_accepts_ths_code_and_chinese(tmp_path, monkeypatch):
    from market_data_mcp import service

    all_codes, by_statement = ifind_provider._statement_codes()

    def fake_fetch(root, mc, existing_metadata=None):
        values = {code: None for code in all_codes}
        values["ths_currency_fund_stock"] = 1.0
        values["ths_operating_total_revenue_stock"] = 2.0
        reports, _ = ifind_provider._period_report("2025-06-30", values, by_statement)
        return {
            "ok": True,
            "source": "ifind",
            "statements": {statement: [reports[statement]] for statement in ("balance", "income", "cash_flow")},
            "metadata": {"code": "600106.SH", "market": "A",
                         "sources": {"statements": "ifind"}, "filings": []},
            "error": None,
            "notes": None,
        }

    monkeypatch.setattr(service.ifind, "fetch_statements", fake_fetch)
    result = service.get_financial_statements(
        str(tmp_path), "600106.SH", amount_basis="cumulative",
        items=["ths_operating_total_revenue_stock", "货币资金"],
    )
    assert result["ok"] is True
    assert result["failed_items"] == []
    got = sorted((row["item_name"], row["amount"]) for row in result["rows"])
    assert got == [("营业总收入", 2.0), ("货币资金", 1.0)]


def test_service_catalog_after_ifind_refresh(tmp_path, monkeypatch):
    from market_data_mcp import service

    all_codes, by_statement = ifind_provider._statement_codes()

    def fake_fetch(root, mc, existing_metadata=None):
        values = {code: None for code in all_codes}
        values["ths_currency_fund_stock"] = 1.0
        reports, _ = ifind_provider._period_report("2025-06-30", values, by_statement)
        return {
            "ok": True,
            "source": "ifind",
            "statements": {statement: [reports[statement]] for statement in ("balance", "income", "cash_flow")},
            "metadata": {"code": "600106.SH", "market": "A",
                         "sources": {"statements": "ifind"}, "filings": []},
            "error": None,
            "notes": None,
        }

    monkeypatch.setattr(service.ifind, "fetch_statements", fake_fetch)
    service.get_financial_statements(str(tmp_path), "600106.SH", amount_basis="cumulative")
    catalog = service.get_data_catalog(str(tmp_path), "600106.SH", statements=["balance"])
    assert catalog["ok"] is True
    names = [item["item_name"] for item in catalog["items"] if item["statement"] == "balance"]
    assert "货币资金" in names
