# -*- coding: utf-8 -*-
"""get_financial_data MCP/CLI 双入口测试。"""

import asyncio

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
    assert "| 公告日 | 2026-04-29 | 2026-08-28 |" in md
    assert "| 货币 | CNY | CNY |" in md
    assert "rows" not in rendered


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
