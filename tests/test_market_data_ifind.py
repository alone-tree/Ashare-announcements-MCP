# -*- coding: utf-8 -*-
"""iFinD 请求模块测试（mock iFinDPy，不依赖真实登录/网络）。

真实调用已单独验证（2026-08-09）：AAPL 美股 hfq/amount 1303 行单点衔接、
COHR 覆盖边界、600519/0700/920002 股本与文档实测一致。
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


def _ds_df(dates, values, col="close_price"):
    return pd.DataFrame({"time": dates, "thscode": ["AAPL.O"] * len(dates), col: values})


@pytest.fixture(autouse=True)
def _reset_ifind_state():
    """每个测试重置登录/后缀缓存（模块级状态跨测试泄漏）。"""
    ifind._LOGIN_STATE["done"] = False
    ifind._SUFFIX_CACHE.clear()
    yield
    ifind._LOGIN_STATE["done"] = False
    ifind._SUFFIX_CACHE.clear()


def _login_and_probe(monkeypatch):
    monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda a, p: 0)
    monkeypatch.setattr(ifind.ths, "THS_HQ",
                        lambda *a, **k: _r(pd.DataFrame({"time": ["2026-08-07"], "close": [313.33]})))


class TestFetchUsHfq:
    def test_writes_close_hfq(self, tmp_path, monkeypatch):
        _login_and_probe(monkeypatch)
        monkeypatch.setattr(ifind.ths, "THS_DS", lambda *a, **k: _r(_ds_df(
            ["2026-08-06", "2026-08-07"], [86000.0, 91659.19])))
        root = str(tmp_path)
        r = ifind.fetch_us_hfq(root, parse_code("AAPL.US"), start="2026-08-01")
        assert r["ok"] is True and r["source"] == "ifind"
        assert r["fields"] == {"close_hfq": {"start": "2026-08-06", "end": "2026-08-07"}}
        data = cache.read_cache(root, "AAPL.US", "close_hfq")
        assert data["meta"]["source"] == "ifind"
        assert data["items"] == [
            {"date": "2026-08-06", "value": 86000.0, "source": "ifind"},
            {"date": "2026-08-07", "value": 91659.19, "source": "ifind"},
        ]

    def test_nan_rows_kept(self, tmp_path, monkeypatch):
        _login_and_probe(monkeypatch)
        monkeypatch.setattr(ifind.ths, "THS_DS", lambda *a, **k: _r(_ds_df(
            ["2023-02-22", "2023-02-23"], [float("nan"), 44.62])))
        ifind.fetch_us_hfq(str(tmp_path), parse_code("COHR.US"), start="2023-02-01")
        data = cache.read_cache(str(tmp_path), "COHR.US", "close_hfq")
        assert data["items"][0]["value"] is None
        assert data["items"][1]["value"] == 44.62

    def test_suffix_probe_o_then_n(self, tmp_path, monkeypatch):
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

    def test_failure_structured(self, tmp_path, monkeypatch):
        _login_and_probe(monkeypatch)
        monkeypatch.setattr(ifind.ths, "THS_DS",
                            lambda *a, **k: SimpleNamespace(errorcode=-4210, errmsg="bad code", data=None))
        r = ifind.fetch_us_hfq(str(tmp_path), parse_code("AAPL.US"), start="2026-08-01")
        assert r["ok"] is False and "THS_DS" in r["error"]
        with open(os.path.join(str(tmp_path), "logs", "requests.jsonl"), encoding="utf-8") as f:
            assert json.loads(f.readlines()[-1])["ok"] is False


class TestFetchUsAmount:
    def test_writes_amount_field(self, tmp_path, monkeypatch):
        _login_and_probe(monkeypatch)
        captured = {}
        def fake_ds(code, ind, param, *a, **k):
            captured["ind"], captured["param"] = ind, param
            return _r(_ds_df(["2026-08-06", "2026-08-07"], [1.44e10, 1.08e10], col="amt"))
        monkeypatch.setattr(ifind.ths, "THS_DS", fake_ds)
        root = str(tmp_path)
        r = ifind.fetch_us_amount(root, parse_code("AAPL.US"), start="2026-08-01")
        assert r["ok"] is True
        assert captured["ind"] == "amt" and captured["param"] == "OC"
        data = cache.read_cache(root, "AAPL.US", "amount")
        assert data["meta"]["source"] == "ifind"
        assert data["items"][0] == {"date": "2026-08-06", "value": 1.44e10, "source": "ifind"}
        # 不污染 close
        assert cache.read_cache(root, "AAPL.US", "close") is None

    def test_backfill_uses_trade_days(self, tmp_path, monkeypatch):
        _login_and_probe(monkeypatch)
        monkeypatch.setattr(ifind.ths, "THS_DS", lambda *a, **k: _r(_ds_df(
            ["2021-08-09"], [7.14e9], col="amt")))
        monkeypatch.setattr(ifind.ths, "THS_Date_Query", lambda *a, **k: _r("2021-08-06"))
        def fake_bd(code, ind, param):
            assert param == "2021-08-06,OC"
            return _r(pd.DataFrame({"thscode": [code], "amt": [7.91e9]}))
        monkeypatch.setattr(ifind.ths, "THS_BD", fake_bd)
        ifind.fetch_us_amount(str(tmp_path), parse_code("AAPL.US"), start="2021-08-01", end="2021-08-10")
        data = cache.read_cache(str(tmp_path), "AAPL.US", "amount")
        assert data["items"][0]["date"] == "2021-08-06"
        assert data["items"][0]["value"] == 7.91e9
        assert data["items"][-1]["date"] == "2021-08-09"


class TestFetchShares:
    def test_a_share_writes_total_shares_only(self, tmp_path, monkeypatch):
        """A 股股本：只写 total_shares（floating_shares 唯一归属=新浪，避免双写）。"""
        monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda a, p: 0)
        df = pd.DataFrame({"time": ["2026-08-06", "2026-08-07"],
                           "thscode": ["600519.SH"] * 2,
                           "total_shares": [1250081601.0, 1250081601.0],
                           "floating_shares": [1250081601.0, 1250081601.0]})
        monkeypatch.setattr(ifind.ths, "THS_DS", lambda *a, **k: _r(df))
        root = str(tmp_path)
        r = ifind.fetch_shares(root, parse_code("600519.SH"), start="2026-08-01")
        assert r["ok"] is True
        assert r["fields"] == {"total_shares": {"start": "2026-08-06", "end": "2026-08-07"}}
        ts = cache.read_cache(root, "600519.SH", "total_shares")
        assert ts["meta"]["source"] == "ifind"
        assert ts["items"][0] == {"date": "2026-08-06", "value": 1250081601.0, "source": "ifind"}
        # A 股 floating_shares 不写（唯一源=新浪 outstanding_share）
        assert cache.read_cache(root, "600519.SH", "floating_shares") is None

    def test_hk_us_writes_both_share_fields(self, tmp_path, monkeypatch):
        """港美股股本：写 total_shares + floating_shares（唯一源 iFinD）。"""
        monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda a, p: 0)
        monkeypatch.setattr(ifind.ths, "THS_HQ",
                            lambda *a, **k: _r(pd.DataFrame({"time": ["2026-08-07"], "close": [1.0]})))
        df = pd.DataFrame({"time": ["2026-08-07"], "thscode": ["AAPL.O"],
                           "total_shares": [1.459418e10], "floating_shares": [1.4e10]})
        monkeypatch.setattr(ifind.ths, "THS_DS", lambda *a, **k: _r(df))
        root = str(tmp_path)
        r = ifind.fetch_shares(root, parse_code("AAPL.US"), start="2026-08-01")
        assert set(r["fields"]) == {"total_shares", "floating_shares"}
        assert cache.read_cache(root, "AAPL.US", "floating_shares")["meta"]["source"] == "ifind"

    def test_hk_code_format(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda a, p: 0)
        captured = {}
        def fake_ds(code, *a, **k):
            captured["code"] = code
            return _r(pd.DataFrame({"time": ["2026-08-07"], "thscode": [code],
                                    "total_shares": [1.0], "floating_shares": [1.0]}))
        monkeypatch.setattr(ifind.ths, "THS_DS", fake_ds)
        r = ifind.fetch_shares(str(tmp_path), parse_code("00700.HK"), start="2026-08-01")
        assert r["ok"] is True
        assert captured["code"] == "0700.HK"
