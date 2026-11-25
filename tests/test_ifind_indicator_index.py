# -*- coding: utf-8 -*-
"""统一指标索引与取数测试：搜索范围、用法完整度、跨市场择市、派生计算口径。

不触 Excel 的部分在这里覆盖；真实取数验证在交付说明里另记样本。
"""

import pytest

from ifind_excel_tool import indicator_index, indicators


def test_search_covers_every_kind():
    """方案要求：搜索范围不阉割，六类能力都要搜得到。"""
    kinds = set()
    for keyword in ("毛利率", "固定资产", "利润表常用科目", "工商信息",
                    "指数成分股", "最新报告期", "营业总收入"):
        result = indicator_index.search(keyword)
        assert result["ok"]
        kinds |= {hit["kind"] for hit in result["hits"]}
    assert {"derived", "select", "group", "scene", "table", "special",
            "excel"} <= kinds


def test_every_hit_carries_usage():
    """每条命中都要能直接拿来用：命令、参数、返回形状齐全。"""
    for keyword in ("毛利率", "固定资产", "工商信息"):
        for hit in indicator_index.search(keyword)["hits"]:
            assert hit["call"]["cmd"], hit["name"]
            assert hit["returns"], hit["name"]
            assert hit["description"] is not None


def test_table_scene_reachable_by_business_phrase():
    """「沪深300成分股」这类自然说法要能搜到「指数成分股」。"""
    hits = indicator_index.search("沪深300成分股")["hits"]
    assert hits and hits[0]["name"] == "指数成分股"
    assert hits[0]["kind"] == "table"


def test_derived_overrides_same_name_raw():
    """自定义库优先：同名时搜到和取到的都是自定义定义。"""
    hit = indicator_index.search("毛利率")["hits"][0]
    assert hit["kind"] == "derived"
    assert indicator_index.resolve("毛利率")["kind"] == "derived"


def test_market_is_selected_by_code_suffix():
    """同名指标跨市场并存时按代码后缀择市场，A股代码拿到A股那条。"""
    entry = indicator_index.resolve("营业利润", "002796.SZ")
    assert entry["path"].startswith("股票全部指标")
    us = indicator_index.resolve("营业利润", "AAPL.US")
    assert us["path"].startswith("美股全部指标")


def test_market_absent_is_reported_plainly():
    """库里没港股版本时，说明缺哪个市场，不说「多个同名定义」。"""
    with pytest.raises(ValueError) as error:
        indicator_index.resolve("营业利润", "0700.HK")
    assert "没有港股版本" in str(error.value)


def test_ambiguous_without_code_refuses_to_guess():
    """不给代码无法唯一确定时报歧义，不替调用方猜。"""
    with pytest.raises(ValueError) as error:
        indicator_index.resolve("营业利润")
    assert "多个同名定义" in str(error.value)


def test_unknown_indicator_says_how_to_search():
    with pytest.raises(ValueError) as error:
        indicator_index.resolve("完全不存在的指标")
    assert "find" in str(error.value)


@pytest.mark.parametrize("expr,names,expected", [
    ("营业总收入 - 营业成本", {"营业总收入": 100.0, "营业成本": 60.0}, 40.0),
    ("(营业总收入 - 营业成本) / 营业总收入 * 100",
     {"营业总收入": 100.0, "营业成本": 60.0}, 40.0),
    ("-营业总收入", {"营业总收入": 5.0}, -5.0),
])
def test_expr_eval_only_arithmetic(expr, names, expected):
    assert indicators._eval_expr(expr, names) == pytest.approx(expected)


def test_expr_eval_rejects_missing_dependency():
    with pytest.raises(ValueError) as error:
        indicators._eval_expr("营业总收入 - 营业成本", {"营业总收入": 1.0})
    assert "营业成本" in str(error.value)


def test_expr_eval_rejects_non_arithmetic():
    """算式只允许四则运算，不允许调函数或取属性。"""
    with pytest.raises(ValueError):
        indicators._eval_expr("__import__('os').getcwd()", {})


def test_zero_denominator_is_unavailable_not_fallback():
    """分母为零时该值不可用并给原因，不回退成0。"""
    definition = {"name": "毛利率", "expr": "(营业总收入 - 营业成本) / 营业总收入 * 100",
                  "decimals": 2}
    result = indicators._compute_derived(definition, {"营业总收入": 0.0, "营业成本": 10.0})
    assert result["ok"] is False
    assert "分母为零" in result["error"]


def test_derived_rounds_by_decimals():
    definition = {"name": "毛利率", "expr": "(营业总收入 - 营业成本) / 营业总收入 * 100",
                  "decimals": 2}
    result = indicators._compute_derived(
        definition, {"营业总收入": 618654770.48, "营业成本": 584204793.3})
    assert result["ok"] and result["value"] == 5.57


def test_group_members_are_declared_indicators():
    """指标组成员必须都能解析，避免定义写完才发现有成员不存在。"""
    groups = indicators._load_groups()
    assert groups, "指标组库不应为空"
    for name, spec in groups.items():
        for member in spec["members"]:
            indicator_index.resolve(member, "002796.SZ")


def test_probe_skipped_for_excel_kind_quote():
    """行情类单格公式有意留空日期取最新值，不能被财报探测逻辑改写。"""
    date, probed = indicators._probe_if_needed("excel", "600519.SH", "")
    assert date == "" and probed is None


def test_probe_skipped_when_date_given():
    date, probed = indicators._probe_if_needed("derived", "600519.SH", "2026-06-30")
    assert date == "2026-06-30" and probed is None


def test_probe_failure_is_reported_not_silent(monkeypatch):
    """探测拿不到日期时明确报错要求指定，不静默取空导致全0。"""
    from ifind_excel_tool import cli

    monkeypatch.setattr(cli, "_probe_report_date", lambda code: None)
    with pytest.raises(ValueError) as error:
        indicators._probe_if_needed("derived", "600519.SH", "")
    assert "report_date" in str(error.value)


def test_probe_fills_date_for_derived(monkeypatch):
    from ifind_excel_tool import cli

    monkeypatch.setattr(cli, "_probe_report_date", lambda code: "2026-09-30")
    date, probed = indicators._probe_if_needed("derived", "600519.SH", "")
    assert date == "2026-09-30" and probed == "2026-09-30"


# ---------------------------------------------------------------------------
# 三类默认时间口径：财报取最新报告期、行情取最近14个日历日、公司信息取今天
# ---------------------------------------------------------------------------

def test_quote_default_range_is_fourteen_calendar_days():
    from datetime import date, timedelta

    from ifind_excel_tool import scenes

    spec = scenes.load_scene("历史行情")
    assert spec["defaults"]["start"] == "today-13d"
    start = scenes._resolve_date(spec["defaults"]["start"])
    end = scenes._resolve_date("today")
    span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    assert span == 14
    # 14个日历日内含周末，剔除非交易日后行数应少于14
    days = scenes._date_range(spec["defaults"]["start"], "today")
    assert len(days) == 14 and days[-1] == date.today().isoformat()


def test_recent_year_placeholders():
    from datetime import date

    from ifind_excel_tool import scenes

    years = scenes._expand_dim_default("__recent_years:5__")
    assert len(years) == 5 and years[0] == str(date.today().year)
    ends = scenes._expand_dim_default("__recent_year_ends:5__")
    assert len(ends) == 5 and all(e.endswith("-12-31") for e in ends)
    assert all(int(e[:4]) < date.today().year for e in ends)


def test_info_scene_defaults_to_today():
    from ifind_excel_tool import scenes

    for name in ("工商信息", "估值快照", "IPO信息", "盈利预测"):
        spec = scenes.load_scene(name)
        assert spec["defaults"]["date"] == "today", name


def test_scenes_with_hard_dims_have_defaults():
    """分红、历史估值原先不传参数会报错，现在都有默认值可用。"""
    from ifind_excel_tool import scenes

    for name in ("分红", "历史估值"):
        spec = scenes.load_scene(name)
        dims = spec.get("dims") or {}
        assert dims, f"{name} 应有默认维度"
        assert any(isinstance(v, list) and v and str(v[0]).startswith("__")
                   for v in dims.values()), f"{name} 的维度默认值应是占位符"
