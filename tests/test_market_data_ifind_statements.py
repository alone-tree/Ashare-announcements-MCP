# -*- coding: utf-8 -*-
"""iFinD 三表切源单测（stub iFinDPy，不登录不联网）。

覆盖：科目注册表完整性、单期报告组装与全空判定、最新报告期探针、
按指定报告期惰性取数（单期失败/全空不中断）、service 层 A 股切源与契约渲染。
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
    assert len(financial_subjects.SUBJECTS) == 330
    codes = [s["ths_code"] for s in financial_subjects.SUBJECTS]
    assert len(codes) == len(set(codes)), "科目码必须唯一"
    counts = {statement: len(financial_subjects.subjects_for(statement))
              for statement in ("balance", "income", "cash_flow", "meta")}
    assert counts == {"balance": 133, "income": 83, "cash_flow": 110, "meta": 4}


def test_subject_registry_non_additive():
    non_additive = [s for s in financial_subjects.SUBJECTS if not s["additive"]]
    assert {s["ths_code"] for s in non_additive} == {
        "ths_basic_eps_stock",
        "ths_dlt_earnings_per_share_stock",
        "ths_audit_institution_stock",
        "ths_regular_report_actual_dd_stock",
        "ths_audit_opinion_type_stock",
        "ths_ica_opinion_type_stock",
    }


def test_subject_info_rows_named():
    # 2026-10-19 用户编辑器公式：4 个报表信息行以编辑器名入表（原模板占位名「有数据」废弃）
    assert financial_subjects.display_name("ths_audit_institution_stock") == "审计单位"
    assert financial_subjects.display_name("ths_regular_report_actual_dd_stock") == "定期报告实际披露日期"
    assert financial_subjects.display_name("ths_audit_opinion_type_stock") == "审计意见类型"
    assert financial_subjects.display_name("ths_ica_opinion_type_stock") == "内控审计意见类型"


def test_subject_display_and_resolve():
    # 扣非旧码 2026-10-19 拍板不保留，换新分析码
    assert financial_subjects.display_name("ths_np_dnrgal_stock") is None
    assert (
        financial_subjects.display_name("ths_new_analyse_np_dnrgal_stock")
        == "扣除非经常性损益后的归属母公司股东净利润"
    )
    assert financial_subjects.resolve_name("货币资金")["ths_code"] == "ths_currency_fund_stock"
    assert financial_subjects.resolve_name("不存在的科目") is None
    # 序号前缀已去除（含 "N," 数字前缀）
    assert financial_subjects.resolve_name("一、营业总收入") is None
    assert financial_subjects.resolve_name("营业总收入")["ths_code"] == "ths_operating_total_revenue_stock"
    assert (
        financial_subjects.resolve_name("重新计量设定受益计划净负债或净资产的变动")["ths_code"]
        == "ths_asset_change_due_to_remeasure_stock"
    )


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
    assert set(reports) == {"balance", "income", "cash_flow", "meta"}


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


# --- 最新报告期探针 ---

def test_probe_latest_report_parses_yyyymmdd(tmp_path, monkeypatch):
    import pandas as pd

    seen = {}

    def responder(full, indicators, params):
        seen["indicators"] = indicators
        return _FakeResult(errorcode=0, data=pd.DataFrame([{"thscode": full, "value": "20250930"}]))

    _install_fake_ths(monkeypatch, responder)
    result = ifind_provider.probe_latest_report(str(tmp_path), _mk_mc())

    assert seen["indicators"] == "ths_regular_report_latest_rp_stock"
    assert result == {"ok": True, "report_date": "2025-09-30", "error": None}


def test_probe_latest_report_failure_is_not_fatal(tmp_path, monkeypatch):
    def responder(full, indicators, params):
        return _FakeResult(errorcode=-205, data=None, errmsg="request data error")

    _install_fake_ths(monkeypatch, responder)
    monkeypatch.setattr(ifind_provider.time, "sleep", lambda s: None)
    result = ifind_provider.probe_latest_report(str(tmp_path), _mk_mc())

    assert result["ok"] is False
    assert result["report_date"] is None
    assert "request data error" in result["error"]


# --- 按指定报告期取数 ---

def test_fetch_statements_fetches_only_named_periods(tmp_path, monkeypatch):
    requested: list[str] = []

    def responder(full, indicators, params):
        period = params.split(";")[0].split(",")[0]  # YYYYMMDD
        requested.append(period)
        return _frame_for(full, indicators, period, {"ths_currency_fund_stock": 1.0})

    _install_fake_ths(monkeypatch, responder)
    fetched = ifind_provider.fetch_statements(
        str(tmp_path), _mk_mc(), ["2025-09-30", "2025-12-31"]
    )

    assert fetched["ok"] is True
    assert requested == ["20250930", "20251231"]
    assert sorted(fetched["periods"]) == ["2025-09-30", "2025-12-31"]
    assert fetched["failed"] == [] and fetched["empty"] == []
    assert "balance" in fetched["periods"]["2025-09-30"]


def test_fetch_statements_all_empty_periods_are_not_failures(tmp_path, monkeypatch):
    def responder(full, indicators, params):
        return _frame_for(full, indicators, params.split(";")[0].split(",")[0], {})

    _install_fake_ths(monkeypatch, responder)
    fetched = ifind_provider.fetch_statements(
        str(tmp_path), _mk_mc(), ["2025-09-30", "2025-12-31"]
    )

    assert fetched["ok"] is True
    assert fetched["periods"] == {}
    assert fetched["empty"] == ["2025-09-30", "2025-12-31"]
    assert fetched["failed"] == []


def test_fetch_statements_retries_per_period_and_keeps_others(tmp_path, monkeypatch):
    calls = {"n": 0}

    def responder(full, indicators, params):
        period = params.split(";")[0].split(",")[0]
        if period == "20251231":
            calls["n"] += 1
            return _FakeResult(errorcode=-205, data=None, errmsg="request data error")
        return _frame_for(full, indicators, period, {"ths_currency_fund_stock": 1.0})

    _install_fake_ths(monkeypatch, responder)
    monkeypatch.setattr(ifind_provider.time, "sleep", lambda s: None)
    fetched = ifind_provider.fetch_statements(
        str(tmp_path), _mk_mc(), ["2025-09-30", "2025-12-31"]
    )

    assert fetched["ok"] is True, "登录成功即 ok，单期失败进 failed"
    assert calls["n"] == 4, "失败须退避重试三次（共 4 次调用）"
    assert [item["period"] for item in fetched["failed"]] == ["2025-12-31"]
    assert "THS_BD" in fetched["failed"][0]["error"]
    assert list(fetched["periods"]) == ["2025-09-30"]


# --- 旧缓存重建判定 ---

def _seed(root, item_code):
    from market_data_mcp import financial_cache

    batch = "b0001"
    report = {
        "report_date": "2025-06-30",
        "metadata": {"CURRENCY": "CNY"},
        "items": [{"item_code": item_code, "item_name": "x", "amount": 1.0, "source": "ifind"}],
    }
    payloads = {
        name: financial_cache.merge_statement(
            None,
            [report] if name == "balance" else [],
            code="600106.SH", market="A", statement=name,
            source="ifind", observed_at="2026-10-01T00:00:00", batch_id=batch,
        )
        for name in ("balance", "income", "cash_flow", "meta")
    }
    metadata = {"meta": {"code": "600106.SH", "market": "A", "update_batch_id": batch,
                         "last_successful_update": "2026-10-01T00:00:00"}}
    financial_cache.commit_bundle(root, "600106.SH", metadata, payloads)
    return financial_cache.read_bundle(root, "600106.SH")


def test_bundle_matches_subjects_detects_legacy_east_cache(tmp_path):
    legacy = _seed(str(tmp_path / "east"), "MONETARYFUNDS")
    current = _seed(str(tmp_path / "ifind"), "ths_currency_fund_stock")

    assert ifind_provider.bundle_matches_subjects(legacy) is False
    assert ifind_provider.bundle_matches_subjects(current) is True
    assert ifind_provider.bundle_matches_subjects(None) is False


# --- service 层切源与渲染契约 ---

def test_service_a_share_uses_ifind_and_renders(tmp_path, monkeypatch):
    from market_data_mcp import service

    all_codes, by_statement = ifind_provider._statement_codes()

    def fake_fetch(root, mc, periods):
        values = {code: None for code in all_codes}
        values["ths_currency_fund_stock"] = 1072245692.17
        values["ths_operating_total_revenue_stock"] = 56316328.4
        values["ths_np_atoopc_stock"] = 5631632.84
        reports, _ = ifind_provider._period_report("2025-06-30", values, by_statement)
        return {
            "ok": True,
            "source": "ifind",
            "periods": {"2025-06-30": reports},
            "failed": [],
            "empty": [],
            "error": None,
            "notes": ["单测注入"],
        }

    monkeypatch.setattr(service.ifind, "probe_latest_report",
                        lambda root, mc: {"ok": True, "report_date": "2025-06-30", "error": None})
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

    def fake_fetch(root, mc, periods):
        values = {code: None for code in all_codes}
        values["ths_currency_fund_stock"] = 1.0
        values["ths_operating_total_revenue_stock"] = 2.0
        reports, _ = ifind_provider._period_report("2025-06-30", values, by_statement)
        return {
            "ok": True,
            "source": "ifind",
            "periods": {"2025-06-30": reports},
            "failed": [],
            "empty": [],
            "error": None,
            "notes": None,
        }

    monkeypatch.setattr(service.ifind, "probe_latest_report",
                        lambda root, mc: {"ok": True, "report_date": "2025-06-30", "error": None})
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

    def fake_fetch(root, mc, periods):
        values = {code: None for code in all_codes}
        values["ths_currency_fund_stock"] = 1.0
        reports, _ = ifind_provider._period_report("2025-06-30", values, by_statement)
        return {
            "ok": True,
            "source": "ifind",
            "periods": {"2025-06-30": reports},
            "failed": [],
            "empty": [],
            "error": None,
            "notes": None,
        }

    monkeypatch.setattr(service.ifind, "probe_latest_report",
                        lambda root, mc: {"ok": True, "report_date": "2025-06-30", "error": None})
    monkeypatch.setattr(service.ifind, "fetch_statements", fake_fetch)
    service.get_financial_statements(str(tmp_path), "600106.SH", amount_basis="cumulative")
    catalog = service.get_data_catalog(str(tmp_path), "600106.SH", statements=["balance"])
    assert catalog["ok"] is True
    names = [item["item_name"] for item in catalog["items"] if item["statement"] == "balance"]
    assert "货币资金" in names
