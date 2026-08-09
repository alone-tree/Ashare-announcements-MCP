# -*- coding: utf-8 -*-
"""yfinance 股本回退模块测试（mock yfinance，不依赖网络/代理）。"""

import os

import pytest

from market_data_mcp import cache
from market_data_mcp.providers import yfinance
from market_data_mcp.routing import parse_code


class TestFetchShares:
    def test_hk_writes_cache(self, tmp_path, monkeypatch):
        """港股：0700.HK ticker，写 shares.json（total_shares 逐日）。"""
        import pandas as pd
        s = pd.Series([9461780480.0, 9461780480.0],
                      index=pd.to_datetime(["2024-01-03", "2024-01-04"]))
        captured = {}
        def fake_shares(start, end):
            captured["start"] = start
            return s
        class FakeTicker:
            def __init__(self, t):
                captured["ticker"] = t
            def get_shares_full(self, start=None, end=None):
                return fake_shares(start, end)
        monkeypatch.setattr("market_data_mcp.providers.yfinance.yf.Ticker", FakeTicker)
        root = str(tmp_path)
        r = yfinance.fetch_shares(root, parse_code("00700.HK"), start="2024-01-01", end="2024-06-30")
        assert r["ok"] is True
        assert captured["ticker"] == "0700.HK"
        assert captured["start"] == "2024-01-01"
        data = cache.read_cache(root, "00700.HK", "shares")
        assert data["meta"]["source"] == "yfinance"
        assert data["items"] == [
            {"date": "2024-01-03", "total_shares": 9461780480.0},
            {"date": "2024-01-04", "total_shares": 9461780480.0},
        ]

    def test_proxy_set_during_call(self, tmp_path, monkeypatch):
        """调用期间设置代理 17891，调用后清除（不与其他源互踩）。"""
        import pandas as pd
        s = pd.Series([1.0], index=pd.to_datetime(["2024-01-03"]))
        seen = {}
        def fake_get_shares_full(self, start=None, end=None):
            seen["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            return s
        class FakeTicker:
            def __init__(self, t):
                pass
            def get_shares_full(self, start=None, end=None):
                return fake_get_shares_full(start, end)
        monkeypatch.setattr("market_data_mcp.providers.yfinance.yf.Ticker", FakeTicker)
        # 模拟调用前无代理
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(k, None)
        yfinance.fetch_shares(str(tmp_path), parse_code("00700.HK"), start="2024-01-01")
        assert seen["HTTP_PROXY"] == "http://127.0.0.1:17891"
        assert "HTTP_PROXY" not in os.environ  # 调用后恢复

    def test_cross_source_cache_not_overwritten(self, tmp_path, monkeypatch):
        """缓存已有 iFinD 数据时不落盘覆盖（回退通道语义）。"""
        import pandas as pd
        # 先写一个 ifind 源的缓存
        cache.write_cache(str(tmp_path), "AAPL.US", "shares",
                          meta={"code": "AAPL.US", "market": "US", "data_type": "shares",
                                "source": "ifind", "date_range": {"start": "2021-08-09", "end": "2021-08-10"}},
                          items=[{"date": "2021-08-09", "total_shares": 16530166000.0}])
        s = pd.Series([15552799744.0], index=pd.to_datetime(["2024-01-03"]))
        class FakeTicker:
            def __init__(self, t):
                pass
            def get_shares_full(self, start=None, end=None):
                return s
        monkeypatch.setattr("market_data_mcp.providers.yfinance.yf.Ticker", FakeTicker)
        r = yfinance.fetch_shares(str(tmp_path), parse_code("AAPL.US"), start="2024-01-01")
        assert r["ok"] is True and r["path"] is None
        assert "ifind" in r["notes"]
        data = cache.read_cache(str(tmp_path), "AAPL.US", "shares")
        assert data["meta"]["source"] == "ifind"  # 未被覆盖
        assert data["items"][0]["date"] == "2021-08-09"

    def test_a_share_not_supported(self, tmp_path):
        r = yfinance.fetch_shares(str(tmp_path), parse_code("600519.SH"))
        assert r["ok"] is False
        assert "仅支持港美股" in r["error"]
