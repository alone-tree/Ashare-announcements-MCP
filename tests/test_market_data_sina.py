# -*- coding: utf-8 -*-
"""新浪 raw 请求模块测试（mock akshare，不依赖网络）。

真实调用已单独验证（600519.SH/00700.HK/AAPL.US/920002.BJ，2026-08-09）。
"""

import json
import math
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


def _read(root, code):
    return cache.read_cache(root, code, "quote_daily_raw")


class TestFetchRaw:
    def test_a_share_writes_full_columns(self, tmp_path, monkeypatch):
        """A 股宽写全部列 + NaN 清理 + date 字符串化。"""
        df = _df(["2026-08-06", "2026-08-07"], {
            "open": [10.0, float("nan")],
            "high": [11.0, 12.0],
            "low": [9.0, 9.5],
            "close": [10.5, 11.5],
            "volume": [1000, 2000],
            "amount": [10000.0, 20000.0],
            "outstanding_share": [1000000, 1000000],
            "turnover": [0.01, 0.02],
        })
        monkeypatch.setattr("akshare.stock_zh_a_daily", lambda **kw: df)
        root = str(tmp_path)
        r = sina.fetch_raw(root, parse_code("600519.SH"), start="2026-08-01")
        assert r["ok"] is True
        assert r["source"] == "sina"
        assert r["new_items"] == 2
        assert r["date_range"] == {"start": "2026-08-06", "end": "2026-08-07"}
        data = _read(root, "600519.SH")
        assert data["meta"]["source"] == "sina"
        assert data["meta"]["market"] == "A"
        assert data["meta"]["date_range"] == {"start": "2026-08-06", "end": "2026-08-07"}
        row = data["items"][1]
        assert row["date"] == "2026-08-07"
        assert row["open"] is None  # NaN → None
        assert row["close"] == 11.5

    def test_merge_dedup_by_date(self, tmp_path, monkeypatch):
        """第二次拉重叠段合并去重，不重复。"""
        df1 = _df(["2026-08-03", "2026-08-04", "2026-08-05"], {"close": [1.0, 2.0, 3.0]})
        df2 = _df(["2026-08-05", "2026-08-06"], {"close": [3.5, 4.0]})
        monkeypatch.setattr("akshare.stock_zh_a_daily", lambda **kw: df1)
        root = str(tmp_path)
        sina.fetch_raw(root, parse_code("600519.SH"))
        monkeypatch.setattr("akshare.stock_zh_a_daily", lambda **kw: df2)
        r = sina.fetch_raw(root, parse_code("600519.SH"))
        assert r["new_items"] == 2
        data = _read(root, "600519.SH")
        assert [x["date"] for x in data["items"]] == ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"]
        assert data["items"][2]["close"] == 3.5  # 新数据覆盖同日期

    def test_hk_fetch_all_filter_locally(self, tmp_path, monkeypatch):
        """港股无 start/end，拉全量后本地过滤。"""
        df = _df(["2026-07-31", "2026-08-03", "2026-08-04", "2026-08-05"],
                 {"close": [1.0, 2.0, 3.0, 4.0], "volume": [1, 2, 3, 4]})
        monkeypatch.setattr("akshare.stock_hk_daily", lambda **kw: df)
        root = str(tmp_path)
        r = sina.fetch_raw(root, parse_code("00700.HK"), start="2026-08-03")
        assert r["new_items"] == 3
        assert r["date_range"] == {"start": "2026-08-03", "end": "2026-08-05"}

    def test_failure_returns_structured(self, tmp_path, monkeypatch):
        """上游异常 → ok=False + 可读错误 + 审计记录失败。"""
        def boom(**kw):
            raise RuntimeError("connect timeout")
        monkeypatch.setattr("akshare.stock_us_daily", boom)
        root = str(tmp_path)
        r = sina.fetch_raw(root, parse_code("AAPL.US"), start="2026-08-01")
        assert r["ok"] is False
        assert r["error"] and "新浪" in r["error"] and "connect timeout" in r["error"]
        assert r["path"] is None
        with open(os.path.join(root, "logs", "requests.jsonl"), encoding="utf-8") as f:
            last = json.loads(f.readlines()[-1])
        assert last["ok"] is False and last["source"] == "sina"

    def test_bj_uses_a_interface(self, tmp_path, monkeypatch):
        df = _df(["2026-08-07"], {"close": [56.6]})
        captured = {}
        def fake(symbol=None, **kw):
            captured["symbol"] = symbol
            return df
        monkeypatch.setattr("akshare.stock_zh_a_daily", fake)
        r = sina.fetch_raw(str(tmp_path), parse_code("920002.BJ"), start="2026-08-01")
        assert captured["symbol"] == "bj920002"
        assert r["ok"] is True
