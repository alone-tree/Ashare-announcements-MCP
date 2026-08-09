# -*- coding: utf-8 -*-
"""get_financial_statements MCP/CLI 双入口测试。"""

import asyncio

from market_data_mcp import cli, server


def test_financial_statements_mcp_forwards_contract(monkeypatch):
    calls = []

    def fake_service(root, code, **kwargs):
        calls.append((root, code, kwargs))
        return {"ok": True, "rows": []}

    monkeypatch.setattr(server, "get_financial_statements_service", fake_service, raising=False)
    monkeypatch.setattr(server, "_data_root", lambda: "ROOT")
    mcp = server.create_server()
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert "get_financial_statements" in names
    asyncio.run(
        mcp.call_tool(
            "get_financial_statements",
            {
                "code": "600519.SH",
                "amount_basis": "single",
                "statements": ["income"],
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
            "start_date": None,
            "end_date": None,
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

    monkeypatch.setattr(cli.service, "get_financial_statements", fake_service)
    monkeypatch.setattr(cli, "_data_root", lambda: "ROOT")

    response = cli.dispatch({
        "tool": "get_financial_statements_batch",
        "codes": ["AAPL.US", "BAD.US"],
        "amount_basis": "cumulative",
        "statements": ["income", "cash_flow"],
    })

    assert response["tool"] == "get_financial_statements_batch"
    assert response["status"] == "partial_success"
    assert response["requested"] == 2 and response["succeeded"] == 1 and response["failed"] == 1
    assert response["results"][0]["code"] == "AAPL.US"
