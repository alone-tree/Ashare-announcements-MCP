# -*- coding: utf-8 -*-
"""统一科目体系测试：检索范围、用法完整度、跨市场择市、衍生计算口径、默认时间口径。

不触 Excel 的部分在这里覆盖；真实取数样本见交付说明。
"""

import pytest

from ifind_excel_tool.indicators import definitions, fetch, packages
from ifind_excel_tool.interface import search


def test_index_covers_every_kind():
    """方案要求：检索范围不阉割，五类科目都要搜得到。"""
    kinds = {e["kind"] for e in definitions.build_index()}
    assert {"formula", "derived", "package", "batch", "special"} <= kinds
    assert "select" in kinds, "固定资产这类多候选取值要作为独立科目暴露"


def test_every_hit_carries_usage():
    """每条命中都要能直接拿来用：命令、返回形状齐全。"""
    for keyword in ("毛利率", "固定资产", "工商信息"):
        for hit in search.search(keyword)["hits"]:
            assert hit["call"]["cmd"], hit["name"]
            assert hit["returns"], hit["name"]
            assert hit["description"] is not None


def test_batch_scene_reachable_by_business_phrase():
    """「沪深300成分股」这类自然说法要能搜到「指数成分股」。"""
    hits = search.search("沪深300成分股")["hits"]
    assert hits and hits[0]["name"] == "指数成分股"
    assert hits[0]["kind"] == "batch"


def test_derived_overrides_same_name_raw():
    """自定义库优先：搜到和取到的都是自定义定义。"""
    hit = search.search("毛利率")["hits"][0]
    assert hit["kind"] == "derived"
    assert definitions.resolve("毛利率")["kind"] == "derived"


def test_display_name_prefers_chinese_alias():
    """展示名用中文别名；英文别名只参与检索，不拿来展示。"""
    for entry in definitions.build_index():
        if entry.get("aliases"):
            assert search.display_name(entry) != entry["aliases"][0] or \
                any("\u4e00" <= ch <= "\u9fff" for ch in entry["aliases"][0])
    assert search.display_name({"name": "毛利率", "aliases": ["gross_margin"]}) == "毛利率"


def test_market_is_selected_by_code_suffix():
    """同名科目跨市场并存时按代码后缀择市场，A股代码拿到A股那条。"""
    entry = definitions.resolve("营业利润", "002796.SZ")
    assert entry["path"].startswith("股票全部指标")
    us = definitions.resolve("营业利润", "AAPL.US")
    assert us["path"].startswith("美股全部指标")


def test_market_absent_is_reported_plainly():
    """库里没港股版本时，说明缺哪个市场，不说「多个同名定义」。"""
    with pytest.raises(ValueError) as error:
        definitions.resolve("营业利润", "0700.HK")
    assert "没有港股版本" in str(error.value)


def test_ambiguous_without_code_refuses_to_guess():
    with pytest.raises(ValueError) as error:
        definitions.resolve("营业利润")
    assert "多个同名定义" in str(error.value)


def test_unknown_indicator_says_how_to_search():
    with pytest.raises(ValueError) as error:
        definitions.resolve("完全不存在的指标")
    assert "find" in str(error.value)


# ---------------------------------------------------------------------------
# 衍生科目算式：只走四则运算白名单
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expr,names,expected", [
    ("营业总收入 - 营业成本", {"营业总收入": 100.0, "营业成本": 60.0}, 40.0),
    ("(营业总收入 - 营业成本) / 营业总收入 * 100",
     {"营业总收入": 100.0, "营业成本": 60.0}, 40.0),
    ("-营业总收入", {"营业总收入": 5.0}, -5.0),
])
def test_expr_eval_only_arithmetic(expr, names, expected):
    assert fetch._eval_expr(expr, names) == pytest.approx(expected)


def test_expr_eval_rejects_missing_dependency():
    with pytest.raises(ValueError) as error:
        fetch._eval_expr("营业总收入 - 营业成本", {"营业总收入": 1.0})
    assert "营业成本" in str(error.value)


def test_expr_eval_rejects_non_arithmetic():
    with pytest.raises(ValueError):
        fetch._eval_expr("__import__('os').getcwd()", {})


def test_zero_denominator_is_unavailable_not_fallback():
    """分母为零得到 None，不回退成 0。"""
    definition = {"name": "毛利率", "expr": "(营业总收入 - 营业成本) / 营业总收入 * 100",
                  "decimals": 2,
                  "deps": [{"label": "营业总收入"}, {"label": "营业成本"}]}
    assert fetch.evaluate(definition, {"营业总收入": 0.0, "营业成本": 10.0}) is None


def test_derived_rounds_by_decimals():
    definition = {"name": "毛利率", "expr": "(营业总收入 - 营业成本) / 营业总收入 * 100",
                  "decimals": 2,
                  "deps": [{"label": "营业总收入"}, {"label": "营业成本"}]}
    value = fetch.evaluate(definition,
                           {"营业总收入": 618654770.48, "营业成本": 584204793.3})
    assert value == 5.57


# ---------------------------------------------------------------------------
# 科目组合
# ---------------------------------------------------------------------------

def test_package_members_all_declared():
    """组合内每个字段引用的科目都必须存在，写完就能发现笔误。"""
    single = __import__("ifind_excel_tool.formulas.library", fromlist=["x"]).load_single()
    derived = definitions.load_derived()
    for name, spec in definitions.load_packages().items():
        for field in spec.get("fields") or []:
            if field.get("derived"):
                assert field["derived"] in derived, f"{name}:{field['label']}"
                continue
            for code in (field.get("candidates") or [field.get("indicator")]):
                assert code in single, f"{name}:{field['label']} -> {code}"


def test_default_time_windows():
    """三类默认时间口径：财报取最新报告期、行情取最近14个日历日、公司信息取今天。"""
    packages_ = definitions.load_packages()
    assert packages_["历史行情"]["defaults"]["start"] == "today-13d"
    from datetime import date

    start = packages.resolve_date("today-13d")
    span = (date.fromisoformat(packages.resolve_date("today")) - date.fromisoformat(start)).days + 1
    assert span == 14
    for name in ("工商信息", "估值快照", "IPO信息", "盈利预测"):
        assert packages_[name]["defaults"]["date"] == "today", name
    assert packages_["分红"]["dims"]["year"][0].startswith("__recent_years")
    assert packages_["历史估值"]["dims"]["date"][0].startswith("__recent_year_ends")


def test_prompt_style_aliases():
    """别名长度要短于原名，否则失去「常用称呼」的意义。"""
    for entry in definitions.build_index():
        for alias in entry.get("aliases") or []:
            if any("\u4e00" <= ch <= "\u9fff" for ch in alias):
                assert len(alias) <= len(entry["name"]), (alias, entry["name"])
