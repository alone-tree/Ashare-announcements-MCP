# -*- coding: utf-8 -*-
"""iFinD 美股 hfq 请求模块测试（mock iFinDPy，不依赖真实登录/网络）。

真实调用已单独验证（2026-08-09）：AAPL 近 5 年 + 单点补全 1303 行无缝衔接、
COHR 覆盖边界 2023-02-23 起前 35 行 NaN 占位。
"""

import json
import os
from types import SimpleNamespace

import pandas as pd
import pytest

from market_data_mcp import cache
from market_data_mcp.providers import ifind
from market_data_mcp.routing import parse_code


def _r(data):
    return SimpleNamespace(errorcode=0, errmsg="", data=data)


def _ds_df(dates, values):
    return pd.DataFrame({"time": dates, "thscode": ["AAPL.O"] * len(dates), "close_price": values})


@pytest.fixture(autouse=True)
def _reset_ifind_state():
    """每个测试重置登录/后缀缓存（模块级状态跨测试泄漏）。"""
    ifind._LOGIN_STATE["done"] = False
    ifind._SUFFIX_CACHE.clear()
    yield
    ifind._LOGIN_STATE["done"] = False
    ifind._SUFFIX_CACHE.clear()


class TestFetchUsHfq:
    def test_ds_segment_writes_cache(self, tmp_path, monkeypatch):
        """THS_DS 段：写 date+close，meta.source=ifind。"""
        monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda a, p: 0)
        monkeypatch.setattr(ifind.ths, "THS_HQ", lambda *a, **k: _r(pd.DataFrame({"time": ["2026-08-07"], "close": [313.33]})))
        monkeypatch.setattr(ifind.ths, "THS_DS", lambda *a, **k: _r(_ds_df(
            ["2026-08-06", "2026-08-07"], [86000.0, 91659.191732833])))
        root = str(tmp_path)
        r = ifind.fetch_us_hfq(root, parse_code("AAPL.US"), start="2026-08-01")
        assert r["ok"] is True
        assert r["source"] == "ifind"
        assert r["date_range"] == {"start": "2026-08-06", "end": "2026-08-07"}
        data = cache.read_cache(root, "AAPL.US", "quote_daily_hfq")
        assert data["meta"]["source"] == "ifind"
        assert data["items"] == [
            {"date": "2026-08-06", "close": 86000.0},
            {"date": "2026-08-07", "close": 91659.191732833},
        ]

    def test_single_point_backfill(self, tmp_path, monkeypatch):
        """5 年前段：交易日历 + THS_BD 单点逐日补全，与 THS_DS 段衔接。"""
        monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda a, p: 0)
        monkeypatch.setattr(ifind.ths, "THS_HQ", lambda *a, **k: _r(pd.DataFrame({"time": ["2026-08-07"], "close": [313.33]})))
        # THS_DS 返回 2021-08-09 起
        monkeypatch.setattr(ifind.ths, "THS_DS", lambda *a, **k: _r(_ds_df(
            ["2021-08-09", "2021-08-10"], [41719.47, 41579.54])))
        # 交易日历：8 月前两周
        monkeypatch.setattr(ifind.ths, "THS_Date_Query",
                            lambda *a, **k: _r("2021-08-02,2021-08-03,2021-08-04,2021-08-05,2021-08-06"))
        # THS_BD 单点：日期越大值越大（模拟序列）
        def fake_bd(code, ind, param):
            d = param.split(",")[0]
            val = {"2021-08-02": 41300.0, "2021-08-03": 41400.0, "2021-08-04": 41500.0,
                   "2021-08-05": 41600.0, "2021-08-06": 41733.75}[d]
            return _r(pd.DataFrame({"thscode": [code], "close_price": [val]}))
        monkeypatch.setattr(ifind.ths, "THS_BD", fake_bd)
        root = str(tmp_path)
        r = ifind.fetch_us_hfq(root, parse_code("AAPL.US"), start="2021-08-01", end="2021-08-10")
        assert r["ok"] is True
        data = cache.read_cache(root, "AAPL.US", "quote_daily_hfq")
        assert [x["date"] for x in data["items"]] == [
            "2021-08-02", "2021-08-03", "2021-08-04", "2021-08-05",
            "2021-08-06", "2021-08-09", "2021-08-10",
        ]
        # 单点与序列衔接（2021-08-06 单点 → 2021-08-09 THS_DS）
        assert data["items"][4]["close"] == 41733.75
        assert data["items"][5]["close"] == 41719.47

    def test_nan_rows_kept_as_none(self, tmp_path, monkeypatch):
        """NaN 行保留为 None（COHR 覆盖边界：更早行占位）。"""
        monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda a, p: 0)
        monkeypatch.setattr(ifind.ths, "THS_HQ", lambda *a, **k: _r(pd.DataFrame({"time": ["2026-08-07"], "close": [1.0]})))
        monkeypatch.setattr(ifind.ths, "THS_DS", lambda *a, **k: _r(_ds_df(
            ["2023-02-22", "2023-02-23"], [float("nan"), 44.62])))
        r = ifind.fetch_us_hfq(str(tmp_path), parse_code("COHR.US"), start="2023-02-01")
        data = cache.read_cache(str(tmp_path), "COHR.US", "quote_daily_hfq")
        assert data["items"][0] == {"date": "2023-02-22", "close": None}
        assert data["items"][1] == {"date": "2023-02-23", "close": 44.62}

    def test_suffix_probe_o_then_n(self, tmp_path, monkeypatch):
        """后缀探测：.O 无数据试 .N。"""
        monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda a, p: 0)
        calls = []
        def fake_hq(code, *a, **k):
            calls.append(code)
            if code.endswith(".O"):
                return SimpleNamespace(errorcode=0, errmsg="", data=None)
            return _r(pd.DataFrame({"time": ["2026-08-07"], "close": [1.0]}))
        monkeypatch.setattr(ifind.ths, "THS_HQ", fake_hq)
        monkeypatch.setattr(ifind.ths, "THS_DS", lambda *a, **k: _r(_ds_df(["2026-08-07"], [1.0])))
        r = ifind.fetch_us_hfq(str(tmp_path), parse_code("TSM.US"), start="2026-08-01")
        assert calls == ["TSM.O", "TSM.N"]
        assert r["ok"] is True

    def test_login_failure_structured(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda a, p: -1)
        r = ifind.fetch_us_hfq(str(tmp_path), parse_code("AAPL.US"))
        assert r["ok"] is False
        assert "登录失败" in r["error"]

    def test_ds_failure_structured(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda a, p: 0)
        monkeypatch.setattr(ifind.ths, "THS_HQ", lambda *a, **k: _r(pd.DataFrame({"time": ["2026-08-07"], "close": [1.0]})))
        monkeypatch.setattr(ifind.ths, "THS_DS", lambda *a, **k: SimpleNamespace(errorcode=-4210, errmsg="bad code", data=None))
        r = ifind.fetch_us_hfq(str(tmp_path), parse_code("AAPL.US"), start="2026-08-01")
        assert r["ok"] is False
        assert "THS_DS" in r["error"]
        # 审计记录失败
        with open(os.path.join(str(tmp_path), "logs", "requests.jsonl"), encoding="utf-8") as f:
            last = json.loads(f.readlines()[-1])
        assert last["ok"] is False and last["api"] == "THS_DS"
