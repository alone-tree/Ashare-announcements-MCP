# -*- coding: utf-8 -*-
"""新浪行情请求模块测试（mock akshare，不依赖网络）。

真实调用已单独验证（2026-08-09）：600519/00700/AAPL/920002 四市场 raw、
A/港 hfq、美股 hfq 结构化提示走 iFinD。
"""

import json
import os
from datetime import date

import pandas as pd
import pytest

from market_data_mcp import cache
from market_data_mcp.providers import sina
from market_data_mcp.routing import parse_code


def _df(dates, cols: dict):
    data = {"date": [date.fromisoformat(d) for d in dates]}
    data.update(cols)
    return pd.DataFrame(data)


class TestFetchRaw:
    def test_a_share_writes_field_files(self, tmp_path, monkeypatch):
        """A 股宽拉：7 个字段 json（含 floating_shares=outstanding_share），items 带 source。"""
        df = _df(["2026-08-06", "2026-08-07"], {
            "open": [10.0, float("nan")], "high": [11.0, 12.0], "low": [9.0, 9.5],
            "close": [10.5, 11.5], "volume": [1000, 2000], "amount": [10000.0, 20000.0],
            "outstanding_share": [1000000, 1000000], "turnover": [0.01, 0.02],
        })
        monkeypatch.setattr("akshare.stock_zh_a_daily", lambda **kw: df)
        root = str(tmp_path)
        r = sina.fetch_raw(root, parse_code("600519.SH"), start="2026-08-01")
        assert r["ok"] is True
        assert set(r["fields"]) == {"open", "high", "low", "close", "volume", "amount", "floating_shares"}
        data = cache.read_cache(root, "600519.SH", "close")
        assert data["meta"]["source"] == "sina"
        assert data["items"] == [{"date": "2026-08-06", "value": 10.5, "source": "sina"},
                                 {"date": "2026-08-07", "value": 11.5, "source": "sina"}]
        # NaN → None
        assert cache.read_cache(root, "600519.SH", "open")["items"][1]["value"] is None
        # outstanding_share → floating_shares（A 股流通股本口径）
        fs = cache.read_cache(root, "600519.SH", "floating_shares")
        assert fs["items"][0]["value"] == 1000000
        # 不写 total_shares（新浪无此列）
        assert cache.read_cache(root, "600519.SH", "total_shares") is None

    def test_us_writes_5_fields_no_amount(self, tmp_path, monkeypatch):
        """美股 raw 只有 OHLCV（无 amount）。"""
        df = _df(["2026-08-07"], {"open": [1.0], "high": [2.0], "low": [0.5],
                                  "close": [1.5], "volume": [100]})
        monkeypatch.setattr("akshare.stock_us_daily", lambda **kw: df)
        r = sina.fetch_raw(str(tmp_path), parse_code("AAPL.US"), start="2026-08-01")
        assert set(r["fields"]) == {"open", "high", "low", "close", "volume"}
        assert cache.read_cache(str(tmp_path), "AAPL.US", "amount") is None

    def test_hk_fetch_all_filter_locally(self, tmp_path, monkeypatch):
        df = _df(["2026-07-31", "2026-08-03", "2026-08-04"],
                 {"close": [1.0, 2.0, 3.0], "volume": [1, 2, 3]})
        monkeypatch.setattr("akshare.stock_hk_daily", lambda **kw: df)
        r = sina.fetch_raw(str(tmp_path), parse_code("00700.HK"), start="2026-08-03")
        assert r["ok"] is True
        assert r["fields"]["close"] == {"start": "2026-08-03", "end": "2026-08-04"}

    def test_failure_structured(self, tmp_path, monkeypatch):
        def boom(**kw):
            raise RuntimeError("connect timeout")
        monkeypatch.setattr("akshare.stock_us_daily", boom)
        r = sina.fetch_raw(str(tmp_path), parse_code("AAPL.US"), start="2026-08-01")
        assert r["ok"] is False
        assert "新浪" in r["error"] and "connect timeout" in r["error"]
        with open(os.path.join(str(tmp_path), "logs", "requests.jsonl"), encoding="utf-8") as f:
            last = json.loads(f.readlines()[-1])
        assert last["ok"] is False and last["source"] == "sina"


class TestFetchHfq:
    def test_a_share_writes_close_hfq(self, tmp_path, monkeypatch):
        """hfq 只写 close_hfq 字段。"""
        df = _df(["2026-08-06", "2026-08-07"],
                 {"open": [10.0, 11.0], "high": [11.0, 12.0], "low": [9.0, 9.5],
                  "close": [120.0, 121.5], "volume": [1000, 2000], "amount": [1, 2]})
        captured = {}
        def fake(symbol=None, adjust=None, **kw):
            captured["adjust"] = adjust
            return df
        monkeypatch.setattr("akshare.stock_zh_a_daily", fake)
        root = str(tmp_path)
        r = sina.fetch_hfq(root, parse_code("600519.SH"), start="2026-08-01")
        assert r["ok"] is True and captured["adjust"] == "hfq"
        assert r["fields"] == {"close_hfq": {"start": "2026-08-06", "end": "2026-08-07"}}
        data = cache.read_cache(root, "600519.SH", "close_hfq")
        assert data["items"][0] == {"date": "2026-08-06", "value": 120.0, "source": "sina"}
        # 不写 close（hfq 与 raw 分离）
        assert cache.read_cache(root, "600519.SH", "close") is None

    def test_us_hfq_structured_failure(self, tmp_path):
        r = sina.fetch_hfq(str(tmp_path), parse_code("AAPL.US"), start="2026-08-01")
        assert r["ok"] is False
        assert "iFinD" in r["error"]
