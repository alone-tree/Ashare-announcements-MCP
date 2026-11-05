# -*- coding: utf-8 -*-
"""market-data CLI/MCP 双入口测试（mock service，不依赖网络）。"""

import pytest

from market_data_mcp import cli
from market_data_mcp import service


class TestCli:
    def test_unknown_tool(self):
        with pytest.raises(ValueError, match="未知 tool"):
            cli.dispatch({"tool": "nope"})

    def test_get_quote_batch(self, monkeypatch):
        monkeypatch.setattr(service, "get_quote", lambda root, code, **kw: {
            "ok": True, "code": code, "rows": [{"date": "2026-08-07", "close": 1.0}]})
        r = cli.dispatch({"tool": "get_quote_batch", "codes": ["600519.SH", "AAPL.US"],
                          "vars": ["close"]})
        assert r["ok"] is True and r["tool"] == "get_quote_batch"
        assert r["status"] == "success" and r["succeeded"] == 2
        assert [x["code"] for x in r["results"]] == ["600519.SH", "AAPL.US"]

    def test_get_quote_batch_partial_failure(self, monkeypatch):
        def fake(root, code, **kw):
            if code == "BAD":
                raise RuntimeError("boom")
            return {"ok": True, "code": code, "rows": []}
        monkeypatch.setattr(service, "get_quote", fake)
        r = cli.dispatch({"tool": "get_quote_batch", "codes": ["600519.SH", "BAD"]})
        assert r["ok"] is False and r["status"] == "partial_success"
        assert r["succeeded"] == 1 and r["failed"] == 1
        assert r["results"][1]["ok"] is False and "boom" in r["results"][1]["error"]

    def test_missing_codes(self):
        with pytest.raises(ValueError, match="非空数组"):
            cli.dispatch({"tool": "get_quote_batch"})

    @pytest.mark.parametrize("items,status,batch_ok,succeeded,failed", [
        ([{"ok": True, "status": "success"}], "success", True, 1, 0),
        ([{"ok": True}], "success", True, 1, 0),
        ([{"ok": True, "status": "partial_success"}], "partial_success", True, 1, 0),
        ([{"ok": True, "status": "success"}, {"ok": True, "status": "partial_success"}], "partial_success", True, 2, 0),
        ([{"ok": True, "status": "success", "stale": True}], "partial_success", True, 1, 0),
        ([{"ok": True}, {"ok": False, "status": "failed"}], "partial_success", False, 1, 1),
        ([{"ok": False, "status": "failed"}], "failed", False, 0, 1),
        ([{"ok": False}, {"ok": False}], "failed", False, 0, 2),
    ])
    def test_batch_status_preserves_child_completeness_and_existing_counts(
        self, items, status, batch_ok, succeeded, failed,
    ):
        result = cli._batch_response("example", items, "results")
        assert result["status"] == status and result["ok"] is batch_ok
        assert result["requested"] == len(items)
        assert result["succeeded"] == succeeded and result["failed"] == failed
        assert result["results"] == items

    def test_company_batch_does_not_promote_partial_success(self, monkeypatch):
        child = {"ok": True, "status": "partial_success", "information_type": "forecast",
                 "data": [{"year": 2027, "营收均值": 100}],
                 "failed": [{"scope": 2028, "reason": "上游超时"}]}
        monkeypatch.setattr(cli.company_service, "get_company_profile", lambda *a, **k: child)
        result = cli.dispatch({"tool": "get_company_profile_batch", "codes": ["600106.SH"],
                               "information_type": "forecast"})
        assert result["status"] == result["results"][0]["status"] == "partial_success"
        assert result["ok"] and result["succeeded"] == 1 and result["failed"] == 0
        assert result["results"][0]["failed"][0]["scope"] == 2028

    def test_main_stdin_stdout(self, monkeypatch, capsys):
        monkeypatch.setattr(service, "get_quote", lambda root, code, **kw: {"ok": True})
        monkeypatch.setattr("sys.stdin", type("S", (), {"read": lambda self: '{"tool": "get_quote_batch", "codes": ["600519.SH"]}'})())
        cli.main()
        out = capsys.readouterr().out
        assert '"ok": true' in out and '"tool": "get_quote_batch"' in out


class TestServer:
    def test_package_entry_starts_its_own_server(self, monkeypatch):
        import runpy
        from market_data_mcp import server
        calls = []
        monkeypatch.setattr(server, "main", lambda: calls.append("market-data"))
        runpy.run_module("market_data_mcp", run_name="__main__")
        assert calls == ["market-data"]

    def test_tool_registered_and_strict_schema(self):
        from market_data_mcp.server import create_server
        mcp = create_server()
        tools = list(mcp._tool_manager.list_tools())
        assert [t.name for t in tools] == [
            "get_quote", "get_financial_data", "get_market_data_help", "get_company_profile",
            "get_quote_chart",
            "close_ifind_excel",
        ]
        quote_schema = tools[0].parameters
        assert quote_schema.get("additionalProperties") is False
        # 参数契约（架构 §2.1）
        props = quote_schema["properties"]
        assert {"code", "vars", "adjust", "start_date", "end_date", "period", "export_path"} <= set(props)
        assert props["adjust"]["default"] == "raw"

        financial_schema = tools[1].parameters
        assert financial_schema.get("additionalProperties") is False
        assert set(financial_schema["required"]) == {"code", "amount_basis"}
        assert {
            "code", "amount_basis", "statements", "periods", "items",
            "include_versions", "force_refresh", "export_path",
        } <= set(financial_schema["properties"])
        assert "start_date" not in financial_schema["properties"]
        assert "report_types" not in financial_schema["properties"]
        from market_data_mcp.market_help import TOOLS
        for tool in tools:
            assert set(TOOLS[tool.name]["parameters"]) == set(tool.parameters["properties"])

    def test_strict_args_rejected(self):
        import asyncio
        from market_data_mcp.server import create_server
        mcp = create_server()
        tool = list(mcp._tool_manager.list_tools())[0]
        with pytest.raises(Exception, match="Extra inputs"):
            asyncio.run(tool.run({"code": "600519.SH", "page": 3}))
