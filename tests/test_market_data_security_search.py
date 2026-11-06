"""证券搜索契约：候选保真、标准代码安全转换及MCP/CLI一致性。"""
import asyncio

import pytest
import requests

from market_data_mcp import cli, security_search
from market_data_mcp.routing import parse_code
from market_data_mcp.server import create_server


def candidate(code, kind, type_us="", **extra):
    return {"Code": code, "Name": "样本名称", "SecurityTypeName": kind, "TypeUS": type_us,
            "Classify": "未知分类", **extra}


@pytest.fixture
def upstream(monkeypatch):
    class Session:
        trust_env = True

        def __init__(self):
            self.calls = []
            self.table = {"Status": 0, "Data": [], "TotalCount": 0}
            self.error = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if self.error:
                raise self.error
            return self

        def raise_for_status(self):
            pass

        def json(self):
            return {"QuotationCodeTable": self.table}

    session = Session()
    monkeypatch.setattr(security_search.requests, "Session", lambda: session)
    return session


@pytest.mark.parametrize("code,kind,type_us,expected", [
    ("600519", "沪A", "2", "600519.SH"),
    ("688981", "科创板", "23", "688981.SH"),
    ("300308", "深A", "80", "300308.SZ"),
    ("900901", "沪B", "3", "900901.SH"),
    ("200725", "深B", "7", "200725.SZ"),
    ("920002", "京A", "81", "920002.BJ"),
    ("03308", "港股", "3", "03308.HK"),
    ("700", "港股", "未知", "00700.HK"),
    ("AAPL", "美股", "1", "AAPL.US"),
    ("NIO", "美股", "3", "NIO.US"),
    ("AAPL", "美股", "未知", "AAPL.US"),
    ("000725", "韩股", "0", None),
    ("000725", "基金", "4", None),
    ("15780", "港股", "6", None),
    ("07315", "港股", "1", None),
    ("AAPW", "美股", "5", None),
    ("AAPL22", "美股", "6", None),
    ("BRK.B", "美股", "1", None),
    ("900901", "未知证券", "3", None),
])
def test_converts_only_supported_stock_candidates(upstream, code, kind, type_us, expected):
    upstream.table.update(Data=[candidate(code, kind, type_us)], TotalCount=1)
    item = security_search.search_securities(code)["candidates"][0]
    assert item["standard_code"] == expected
    assert item["code"] == code and item["security_type_name"] == kind
    if expected:
        assert parse_code(expected).code


def test_preserves_candidates_and_searches_only_once(upstream, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://invalid-proxy:9999")
    upstream.table.update(Data=[candidate("000725", "深A", "6", InnerCode="123", JYS="6"),
                               candidate("000725", "韩股", "0")], TotalCount=25)
    result = security_search.search_securities("  000725  ")
    assert result["ok"] and result["keyword"] == "000725"
    assert result["source_total_count"] == 25 and result["returned_count"] == 2
    assert [c["standard_code"] for c in result["candidates"]] == ["000725.SZ", None]
    assert result["candidates"][0]["inner_code"] == "123"
    assert result["candidates"][0]["jys"] == "6"
    assert "hint" in result
    assert len(upstream.calls) == 1
    url, arguments = upstream.calls[0]
    assert url.startswith("https://searchapi.eastmoney.com/")
    assert arguments["params"]["input"] == "000725" and arguments["timeout"] == 20
    assert upstream.trust_env is False
    assert security_search.requests.utils.get_environ_proxies(url)["http"] == "http://invalid-proxy:9999"


def test_empty_search_is_successful_without_truncation_hint(upstream):
    result = security_search.search_securities("无匹配")
    assert result["ok"] and result["candidates"] == [] and result["returned_count"] == 0
    assert "hint" not in result


@pytest.mark.parametrize("keyword", [None, 123, [], "", "  "])
def test_invalid_keyword_does_not_request_network(upstream, keyword):
    with pytest.raises(ValueError, match="非空字符串"):
        security_search.search_securities(keyword)
    assert upstream.calls == []


def test_upstream_error_is_not_an_empty_search(upstream):
    upstream.table.update(Status=1, Message="上游拒绝请求")
    with pytest.raises(RuntimeError, match="上游拒绝请求"):
        security_search.search_securities("样本")


def test_network_error_is_not_an_empty_search(upstream):
    upstream.error = requests.Timeout("上游超时")
    with pytest.raises(requests.Timeout):
        security_search.search_securities("样本")


def test_missing_upstream_data_is_not_an_empty_search(upstream):
    del upstream.table["Data"]
    with pytest.raises(KeyError):
        security_search.search_securities("样本")


def test_mcp_and_cli_share_search_result_and_strict_parameters(upstream):
    upstream.table.update(Data=[candidate("900901", "沪B", "3")], TotalCount=1)
    tool = create_server()._tool_manager.get_tool("search_securities")
    assert tool.parameters["required"] == ["keyword"]
    assert tool.parameters["additionalProperties"] is False
    result = asyncio.run(tool.run({"keyword": "云赛"}))
    cli_result = cli.dispatch({"tool": "search_securities", "keyword": "云赛"})
    assert cli_result.pop("tool") == "search_securities"
    assert result == cli_result
    with pytest.raises(Exception, match="Extra inputs"):
        asyncio.run(tool.run({"keyword": "云赛", "page": 2}))
    with pytest.raises(ValueError, match="未知参数"):
        cli.dispatch({"tool": "search_securities", "keyword": "云赛", "page": 2})


def test_mcp_reports_failure_without_candidates(upstream):
    upstream.error = requests.Timeout("上游超时")
    tool = create_server()._tool_manager.get_tool("search_securities")
    result = asyncio.run(tool.run({"keyword": "样本"}))
    assert result["ok"] is False and "上游超时" in result["error"]
    assert "candidates" not in result
