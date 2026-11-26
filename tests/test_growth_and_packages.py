# -*- coding: utf-8 -*-
"""2026-11-26 新增：同比环比（公告口径）、衍生指标扩充、三表常用科目组合。"""
import json

import pytest

from ifind_excel_tool.indicators import definitions, fetch, packages
from ifind_excel_tool.formulas import library

T1 = "2026-09-30"


def test_base_period_yoy_qoq():
    """同比取上年同期，环比取上一报告期，一季度环比跨年。"""
    assert fetch._base_period(T1, "yoy") == "2025-09-30"
    assert fetch._base_period(T1, "qoq") == "2026-06-30"
    assert fetch._base_period("2026-03-31", "qoq") == "2025-12-31"
    assert fetch._base_period("2026-12-31", "qoq") == "2026-09-30"


def test_last_n_quarters():
    """扣非PE的TTM铺期：最新披露期起往回4个季末。"""
    assert fetch._last_n_quarters(4, T1) == [
        "2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31"]
    assert fetch._last_n_quarters(4, "2026-03-31") == [
        "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
    with pytest.raises(ValueError):
        fetch._last_n_quarters(4, "2026-11-26")


def test_growth_result_announcement_style():
    """公告口径：分母取基期绝对值；基期为负附标记；基期为0不可用。"""
    ok = fetch._growth_result("营收同比", 2, T1, "2025-09-30", 115, 100)
    assert ok["value"] == 15.0 and "base_negative" not in ok
    turn = fetch._growth_result("x", 2, T1, "2025-09-30", 50, -100)
    assert turn["value"] == 150.0 and turn["base_negative"] is True
    both_neg = fetch._growth_result("x", 2, T1, "2025-09-30", -150, -200)
    assert both_neg["value"] == 25.0 and both_neg["base_negative"] is True
    zero = fetch._growth_result("x", 2, T1, "2025-09-30", 50, 0)
    assert not zero["ok"] and "0" in zero["error"]
    missing = fetch._growth_result("x", 2, T1, "2025-09-30", None, 100)
    assert not missing["ok"]


def test_evaluate_max_whitelist():
    """合同负债取较大值走 max，白名单内合法。"""
    definition = definitions.load_derived()["合同负债"]
    assert fetch.evaluate(definition, {"合同负债": 300.0, "预收款项": 500.0}) == 500.0
    assert fetch.evaluate(definition, {"合同负债": 800.0, "预收款项": 500.0}) == 800.0


def test_resolve_prefers_derived_for_contract_liab():
    """「合同负债」同名时解析到衍生定义（稳健口径）；原始科目仍可用指标码取。"""
    entry = definitions.resolve("合同负债", "600519.SH")
    assert entry["kind"] == "derived"
    raw = definitions.resolve("ths_contract_liab_stock")
    assert raw["indicator"] == "ths_contract_liab_stock"


def test_qoq_scope():
    """环比仅单季与资产负债表科目；累计报提示原文；同比不设限。"""
    assert fetch._qoq_reason(["ths_sq_np_stock"]) is None
    assert fetch._qoq_reason(["ths_total_assets_stock"]) is None
    assert fetch._qoq_reason(["ths_np_stock"]) == "累计报不支持环比计算"
    reason = fetch._qoq_reason(["ths_stock_short_name_stock"])
    assert reason and "累计报" not in reason


def test_new_derived_defs_complete():
    """新增6个衍生科目的依赖全部在公式库，表达式可静态验证。"""
    derived = definitions.load_derived()
    single = library.load_single()
    for name in ("资产负债率", "合并ROE", "归母ROE", "四费合计",
                 "合同负债", "扣非PE"):
        assert name in derived, name
        for dep in derived[name].get("deps") or []:
            assert dep["indicator"] in single, dep["indicator"]
    # 表达式只允许四则与max
    for name in ("资产负债率", "合并ROE", "归母ROE", "四费合计", "合同负债", "扣非PE"):
        fetch._eval_expr(derived[name]["expr"], {
            dep["label"]: 1.0 for dep in derived[name]["deps"]})


def test_growth_derived_defs():
    """3个常用同比科目：growth=yoy，依赖在库。"""
    derived = definitions.load_derived()
    single = library.load_single()
    for name in ("营业收入同比", "归母净利润同比", "扣非净利润同比"):
        assert derived[name].get("growth") == "yoy", name
        dep = derived[name]["deps"][0]
        assert dep["indicator"] in single


def test_new_packages_expandable():
    """现金流量表/资产负债表常用科目的全部字段都能展开成公式矩阵。"""
    expanded = packages.expand("现金流量表常用科目", code="600519.SH",
                               report_date="2026-09-30")
    assert len(expanded["plan"]) == 28
    assert len(expanded["matrix"][0]) == 28
    expanded_b = packages.expand("资产负债表常用科目", code="600519.SH",
                                 report_date="2026-09-30")
    # 50字段，固定资产/在建工程各2候选、合同负债衍生展开2依赖
    assert len(expanded_b["plan"]) == 50
    assert len(expanded_b["matrix"][0]) == 50 + 2 + 1


def test_income_package_extended():
    """利润表常用科目扩到15字段，含四费合计衍生列。"""
    spec = definitions.load_packages()["利润表常用科目"]
    assert len(spec["fields"]) == 15
    expanded = packages.expand("利润表常用科目", code="600519.SH",
                               report_date="2026-09-30")
    # 12个原始单列 + 毛利润2列 + 毛利率2列 + 四费合计4列 = 20列
    assert len(expanded["matrix"][0]) == 20
    labels = [field["label"] for field in spec["fields"]]
    assert labels[:6] == ["营业总收入", "营业总成本", "营业成本",
                          "毛利润", "毛利率", "四费合计"]


def test_growth_switch_off_path_kept(monkeypatch):
    """get 开关 yoy 的递归取值路径：mock 两期取数验证拼装。"""
    entry = {"name": "净利润", "kind": "formula", "indicator": "ths_np_stock",
             "decimals": None}
    responses = iter([
        {"ok": True, "value": 110.0},
        {"ok": True, "value": 100.0},
    ])
    monkeypatch.setattr(fetch, "get",
                        lambda *a, **k: next(responses))
    monkeypatch.setattr(fetch, "probe_latest_report", lambda code: T1)
    result = fetch._growth_value(entry, "600519.SH", "", None, "yoy")
    assert result["ok"] and result["value"] == 10.0
    assert result["base_period"] == "2025-09-30"


def test_qoq_rejects_cumulative_income():
    """对累计利润表科目请求环比返回用户原文提示。"""
    entry = {"name": "净利润", "kind": "formula", "indicator": "ths_np_stock"}
    result = fetch._growth_value(entry, "600519.SH", T1, None, "qoq")
    assert not result["ok"] and result["error"] == "累计报不支持环比计算"
