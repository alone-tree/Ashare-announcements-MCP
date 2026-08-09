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

    def test_main_stdin_stdout(self, monkeypatch, capsys):
        monkeypatch.setattr(service, "get_quote", lambda root, code, **kw: {"ok": True})
        monkeypatch.setattr("sys.stdin", type("S", (), {"read": lambda self: '{"tool": "get_quote_batch", "codes": ["600519.SH"]}'})())
        cli.main()
        out = capsys.readouterr().out
        assert '"ok": true' in out and '"tool": "get_quote_batch"' in out


class TestServer:
    def test_tool_registered_and_strict_schema(self):
        from market_data_mcp.server import create_server
        mcp = create_server()
        tools = list(mcp._tool_manager.list_tools())
        assert [t.name for t in tools] == ["get_quote"]
        schema = tools[0].parameters
        assert schema.get("additionalProperties") is False
        # 参数契约（架构 §2.1）
        props = schema["properties"]
        assert {"code", "vars", "adjust", "start_date", "end_date", "period", "export_path"} <= set(props)
        assert props["adjust"]["default"] == "raw"

    def test_strict_args_rejected(self):
        import asyncio
        from market_data_mcp.server import create_server
        mcp = create_server()
        tool = list(mcp._tool_manager.list_tools())[0]
        with pytest.raises(Exception, match="Extra inputs"):
            asyncio.run(tool.run({"code": "600519.SH", "page": 3}))
