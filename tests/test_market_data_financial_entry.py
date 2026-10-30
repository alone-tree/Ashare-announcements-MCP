# -*- coding: utf-8 -*-
"""get_financial_data MCP/CLI 双入口测试。"""

import asyncio

import pytest

from market_data_mcp import cli, server


def test_financial_statements_mcp_forwards_contract(monkeypatch):
    calls = []

    def fake_service(root, code, **kwargs):
        calls.append((root, code, kwargs))
        return {"ok": True, "rows": []}

    monkeypatch.setattr(server, "get_financial_data_service", fake_service)
    monkeypatch.setattr(server, "_data_root", lambda: "ROOT")
    mcp = server.create_server()
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert "get_financial_data" in names
    assert "get_financial_statements" not in names
    asyncio.run(
        mcp.call_tool(
            "get_financial_data",
            {
                "code": "600519.SH",
                "amount_basis": "single",
                "statements": ["income"],
                "items": ["营业收入"],
                "periods": ["2025-06-30"],
                "include_versions": True,
                "force_refresh": True,
            },
        )
    )
    assert calls == [(
        "ROOT",
        "600519.SH",
        {
            "amount_basis": "single",
            "statements": ["income"],
            "periods": ["2025-06-30"],
            "items": ["营业收入"],
            "include_versions": True,
            "force_refresh": True,
            "export_path": None,
            "top_n": 5,
        },
    )]


def test_financial_statements_cli_batch_partial_success(monkeypatch):
    def fake_service(root, code, **kwargs):
        if code == "BAD.US":
            return {"ok": False, "error": "失败"}
        return {"ok": True, "amount_basis": kwargs["amount_basis"], "rows": []}

    monkeypatch.setattr(cli.financial_service, "get_financial_data", fake_service)
    monkeypatch.setattr(cli, "_data_root", lambda: "ROOT")

    response = cli.dispatch({
        "tool": "get_financial_data_batch",
        "codes": ["AAPL.US", "BAD.US"],
        "amount_basis": "cumulative",
        "statements": ["income", "cash_flow"],
    })

    assert response["tool"] == "get_financial_data_batch"
    assert response["status"] == "partial_success"
    assert response["requested"] == 2 and response["succeeded"] == 1 and response["failed"] == 1
    assert response["results"][0]["code"] == "AAPL.US"


def test_financial_markdown_renders_variable_by_period_matrix():
    result = {
        "ok": True,
        "code": "301205.SZ",
        "statements": ["income"],
        "amount_basis": "single",
        "rows": [
            {"report_date": "2026-03-31", "statement": "income", "item_name": "营业收入",
             "amount": 213359674.81, "value_basis": "single",
             "report_metadata": {"NOTICE_DATE": "2026-04-29 00:00:00", "CURRENCY": "CNY",
                                  "OPINION_TYPE": None, "UPDATE_DATE": "2026-04-29 00:00:00"}},
            {"report_date": "2026-06-30", "statement": "income", "item_name": "营业收入",
             "amount": 1105675.0499999998, "value_basis": "single",
             "report_metadata": {"NOTICE_DATE": "2026-08-28 00:00:00", "CURRENCY": "CNY",
                                  "OPINION_TYPE": None, "UPDATE_DATE": "2026-08-28 00:00:00"}},
        ],
    }

    rendered = server._render_financial_markdown(result)

    md = rendered["markdown"]
    assert "## 利润表（value_basis=single）" in md
    assert "| 科目 | 2026-03-31 | 2026-06-30 |" in md
    assert "|---|---:|---:|" in md
    assert "| 营业收入 | 213359674.81 | 1105675.05 |" in md
    assert "## 报告期元信息" in md
    assert "| 项目 | 2026-03-31 | 2026-06-30 |" in md
    assert "| 公告日 | 2026-04-29 | 2026-08-28 |" in md
    assert "| 货币 | CNY | CNY |" in md
    assert "rows" not in rendered


def test_financial_markdown_skips_meta_block_when_meta_requested():
    result = {
        "ok": True, "statements": ["income", "meta"], "amount_basis": "cumulative",
        "rows": [
            {"report_date": "2025-12-31", "statement": "income", "item_name": "营业收入",
             "amount": 100.0, "unit": "原币基础单位", "report_metadata": {"CURRENCY": "CNY"}},
            {"report_date": "2025-12-31", "statement": "meta", "item_name": "公告日",
             "amount": "2026-03-20", "unit": "text", "report_metadata": {"CURRENCY": "CNY"}},
        ],
    }

    md = server._render_financial_markdown(result)["markdown"]

    assert "## 报表信息" in md
    assert "## 报告期元信息" not in md


def test_financial_markdown_passthrough_export_and_version_audit():
    exported = server._render_financial_markdown({"ok": True, "path": "x.csv"})
    assert "markdown" not in exported

    versioned = server._render_financial_markdown({
        "ok": True, "statements": ["income"], "amount_basis": "cumulative",
        "include_versions": True,
        "rows": [
            {"report_date": "2025-12-31", "statement": "income", "item_name": "净利润",
             "amount": 100.0, "value_basis": "cumulative", "version_id": "abc",
             "is_latest": True, "version_count": 2, "report_metadata": {}},
        ],
    })

    md = versioned["markdown"]
    assert "| 报告期 | 科目 | 金额 | version_id | is_latest | version_count |" in md
    assert "| 2025-12-31 | 净利润 | 100.00 | abc | True | 2 |" in md


@pytest.mark.parametrize("dimension", ["income by product", "income by industry", "income by region"])
def test_segments_markdown_preserves_main_business_fields(dimension):
    result = {
        "ok": True, "statements": ["segments"], "amount_basis": "cumulative", "rows": [],
        "segments": [{"report_date": "2025-12-31", "dimension": dimension, "rank": 1,
                      "name": "主营项目", "income": 100.0, "income_share": 0.25,
                      "gross_profit": 20.0, "gross_margin": 0.20}],
    }
    rendered = server._render_financial_markdown(result)
    md = rendered["markdown"]
    assert "## 营收结构（累计口径）" in md and "### 主营构成" in md
    assert "| 报告期 | 维度 | 排名 | 名称 | 收入 | 营收占比 | 毛利 | 毛利率 |" in md
    assert f"| 2025-12-31 | {dimension} | 1 | 主营项目 | 100.00 | 25.00% | 20.00 | 20.00% |" in md
    assert "rows" not in rendered and "segments" not in rendered


@pytest.mark.parametrize("dimension,ratio,display", [
    ("income by customer", 0.7598, "75.98%"),
    ("purchase by supplier", 0.515, "51.50%"),
])
def test_segments_markdown_marks_top5_total_without_inventing_name(dimension, ratio, display):
    md = server._render_financial_markdown({
        "ok": True, "statements": ["segments"], "rows": [],
        "segments": [
            {"report_date": "2025-12-31", "dimension": dimension, "rank": 1, "name": "", "ratio": None},
            {"report_date": "2025-12-31", "dimension": dimension, "rank": "top5", "ratio": ratio},
        ],
    })["markdown"]
    assert "### 客户/供应商集中度" in md
    assert "| 报告期 | 维度 | 排名/汇总 | 名称 | 占比 |" in md
    assert f"| 2025-12-31 | {dimension} | 1 |  |  |" in md
    assert f"| 2025-12-31 | {dimension} | 前5大合计 |  | {display} |" in md
    assert "主营构成" not in md and "毛利" not in md


def test_segments_markdown_keeps_default_selection_minimal():
    md = server._render_financial_markdown({
        "ok": True, "statements": ["segments"], "rows": [],
        "segments": [{"report_date": "2025-12-31", "dimension": "income by product",
                      "name": "默认项目", "income": 0}],
    })["markdown"]
    assert "| 报告期 | 维度 | 名称 | 收入 |" in md
    assert "| 默认项目 | 0.00 |" in md
    assert all(label not in md for label in ("排名", "营收占比", "毛利"))


def test_segments_markdown_preserves_zero_negative_large_ratios_and_placeholders():
    md = server._render_financial_markdown({
        "ok": True, "statements": ["segments"], "rows": [],
        "segments": [
            {"report_date": "2025-12-31", "dimension": "income by region", "rank": 1,
             "name": "零比率", "income": 100, "income_share": 0, "gross_profit": 0, "gross_margin": 0},
            {"report_date": "2025-12-31", "dimension": "income by region", "rank": 2,
             "name": "内部抵销", "income": -10, "income_share": -0.017891, "gross_profit": None, "gross_margin": None},
            {"report_date": "2025-12-31", "dimension": "income by region", "rank": 3,
             "name": "国内", "income": 200, "income_share": 1.009445, "gross_profit": "--", "gross_margin": None},
        ],
    })["markdown"]
    assert "| 零比率 | 100.00 | 0.00% | 0.00 | 0.00% |" in md
    assert "| 内部抵销 | -10.00 | -1.79% |  |  |" in md
    assert "| 国内 | 200.00 | 100.94% | -- |  |" in md


def test_data_catalog_mcp_is_registered_and_forwards_company_statements(monkeypatch):
    calls = []

    def fake_service(root, **kwargs):
        calls.append((root, kwargs))
        return {"ok": True, "items": []}

    monkeypatch.setattr(server, "get_market_data_help_service", fake_service)
    monkeypatch.setattr(server, "_data_root", lambda: "ROOT")
    mcp = server.create_server()

    result = asyncio.run(mcp.call_tool(
        "get_market_data_help", {"code": "600519.SH", "topic": "cache"}
    ))

    assert result is not None
    assert calls == [("ROOT", {"tool": None, "market": None, "code": "600519.SH", "topic": "cache"})]


def test_data_catalog_cli_batch_uses_same_service(monkeypatch):
    monkeypatch.setattr(
        cli.market_help,
        "get_market_data_help",
        lambda root, **kwargs: {"ok": True, "items": [{"item_name": kwargs["code"]}]},
        raising=False,
    )
    monkeypatch.setattr(cli, "_data_root", lambda: "ROOT")

    response = cli.dispatch({
        "tool": "get_market_data_help",
        "arguments": {"code": "600519.SH", "topic": "items"},
    })

    assert response["ok"]
    assert response["items"] == [{"item_name": "600519.SH"}]


def test_top_n_forwarded_by_both_entries(monkeypatch):
    calls = []
    def fake(root, code, **kwargs):
        calls.append(kwargs["top_n"])
        return {"ok": True, "rows": []}
    monkeypatch.setattr(server, "get_financial_data_service", fake)
    monkeypatch.setattr(cli.financial_service, "get_financial_data", fake)
    mcp = server.create_server()
    asyncio.run(mcp.call_tool("get_financial_data", {"code": "002586.SZ", "amount_basis": "cumulative", "top_n": 99}))
    cli.dispatch({"tool": "get_financial_data_batch", "codes": ["002586.SZ"], "amount_basis": "cumulative", "top_n": 99})
    assert calls == [99, 99]


@pytest.mark.parametrize("value", [True, 5.0, "5", None])
def test_mcp_top_n_is_strict_integer(monkeypatch, value):
    monkeypatch.setattr(server, "get_financial_data_service", lambda *a, **k: pytest.fail("非法参数不得请求"))
    tool = next(t for t in server.create_server()._tool_manager.list_tools() if t.name == "get_financial_data")
    with pytest.raises(Exception, match="valid integer"):
        asyncio.run(tool.run({"code": "002586.SZ", "amount_basis": "cumulative", "top_n": value}))


def test_cli_explicit_null_top_n_is_not_silently_defaulted(monkeypatch):
    monkeypatch.setattr(cli.financial_service.financial_statements, "fetch_batch", lambda *a: pytest.fail("非法参数不得请求"))
    response = cli.dispatch({"tool": "get_financial_data_batch", "codes": ["002586.SZ"],
                             "amount_basis": "cumulative", "top_n": None})
    assert not response["ok"] and "top_n" in response["results"][0]["error"]
