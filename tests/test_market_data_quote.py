# -*- coding: utf-8 -*-
"""get_quote 工具层测试（mock 聚合层，不依赖网络）。

真实调用已单独验证（2026-08-09）：A 股 raw/hfq/qfq、美股 amount+市值 4.57 万亿、
周线聚合、超长自动导出（247 行 CSV）。
"""

import os

import pytest

from market_data_mcp import service
from market_data_mcp.routing import parse_code


def _raw_rows(n=2, start="2026-08-06"):
    from datetime import date, timedelta
    base = date.fromisoformat(start)
    out = []
    for i in range(n):
        d = (base + timedelta(days=i)).isoformat()
        out.append({"date": d, "open": 10.0 + i, "high": 12.0 + i, "low": 9.0 + i,
                    "close": 11.0 + i, "volume": 1000 + i, "amount": 10000.0 + i,
                    "turnover": 0.01, "outstanding_share": 1000000.0})
    return out


def _hfq_rows():
    # 与 raw 同日期的 hfq close（因子 ≈ 5）
    return [{"date": "2026-08-06", "close": 55.0}, {"date": "2026-08-07", "close": 60.0}]


class TestGetQuote:
    def _ok(self, items=None, source="sina", notes=None):
        return {"ok": True, "items": items, "meta": None, "source": source, "notes": notes}

    def test_basic_close(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service, "_ensure_raw",
                            lambda root, mc, start, end: self._ok(_raw_rows()))
        r = service.get_quote(str(tmp_path), "600519.SH", start_date="2026-08-06", end_date="2026-08-07")
        assert r["ok"] is True
        assert r["market"] == "A" and r["code"] == "600519.SH"
        assert r["rows"] == [{"date": "2026-08-06", "close": 11.0},
                             {"date": "2026-08-07", "close": 12.0}]
        assert r["source"] == "sina"

    def test_vars_filter(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service, "_ensure_raw",
                            lambda root, mc, start, end: self._ok(_raw_rows()))
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["close", "volume"],
                              start_date="2026-08-06", end_date="2026-08-07")
        assert r["rows"][0] == {"date": "2026-08-06", "close": 11.0, "volume": 1000}
        assert "amount" not in r["rows"][0]

    def test_invalid_adjust(self, tmp_path):
        r = service.get_quote(str(tmp_path), "600519.SH", adjust="xxx")
        assert r["ok"] is False and "复权方式" in r["error"]

    def test_invalid_period(self, tmp_path):
        r = service.get_quote(str(tmp_path), "600519.SH", period="hourly")
        assert r["ok"] is False and "周期" in r["error"]

    def test_invalid_vars(self, tmp_path):
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["pe"])
        assert r["ok"] is False and "未知字段" in r["error"]

    def test_bad_code(self, tmp_path):
        r = service.get_quote(str(tmp_path), "600519")
        assert r["ok"] is False and "后缀" in r["error"]

    def test_market_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service, "_ensure_raw",
                            lambda root, mc, start, end: self._ok(_raw_rows()))
        monkeypatch.setattr(service, "_ensure_shares", lambda root, mc, start, end: self._ok(
            [{"date": "2026-08-06", "total_shares": 1000000.0, "floating_shares": 800000.0},
             {"date": "2026-08-07", "total_shares": 1000000.0, "floating_shares": 800000.0}]))
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["close", "total_market_cap", "float_market_cap"],
                              start_date="2026-08-06", end_date="2026-08-07")
        assert r["rows"][0]["total_market_cap"] == 11.0 * 1000000.0
        # A 股流通股本 = 新浪 outstanding_share（架构 §2.4），非 iFinD floating_shares
        assert r["rows"][0]["float_market_cap"] == 11.0 * 1000000.0
        assert any("估算" in n for n in r["notes"])

    def test_qfq_local(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service, "_ensure_raw",
                            lambda root, mc, start, end: self._ok(_raw_rows()))
        monkeypatch.setattr(service, "_ensure_hfq",
                            lambda root, mc, start, end: self._ok(_hfq_rows()))
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["open", "high", "low", "close"],
                              adjust="qfq", start_date="2026-08-06", end_date="2026-08-07")
        # 最新日 qfq = raw（scale = raw_latest/hfq_latest = 12/60 = 0.2；因子 F=hfq/raw）
        # 08-07: F=60/12=5, scale=0.2 → qfq = raw × 5 × 0.2 = raw
        assert r["rows"][1]["close"] == 12.0
        # 08-06: F=55/11=5 → qfq close = 11 × 5 × 0.2 = 11
        assert r["rows"][0]["close"] == 11.0

    def test_us_amount(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service, "_ensure_raw",
                            lambda root, mc, start, end: self._ok(
                                [{"date": "2026-08-06", "close": 313.33, "volume": 1000}]))
        monkeypatch.setattr(service, "_ensure_amount", lambda root, mc, start, end: self._ok(
            [{"date": "2026-08-06", "amt": 1.08e10}]))
        r = service.get_quote(str(tmp_path), "AAPL.US", vars=["close", "amount"],
                              start_date="2026-08-06", end_date="2026-08-06")
        assert r["rows"][0]["amount"] == 1.08e10
        assert "ifind" in r["source"]

    def test_auto_export_over_200(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service, "_ensure_raw",
                            lambda root, mc, start, end: self._ok(_raw_rows(250, "2025-01-01")))
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["close"],
                              start_date="2025-01-01", end_date="2026-01-01")
        assert r["ok"] is True and r.get("auto_exported") is True
        assert os.path.exists(r["path"]) and "auto_export" in r["path"]
        assert r["total_items"] == 250

    def test_export_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(service, "_ensure_raw",
                            lambda root, mc, start, end: self._ok(_raw_rows()))
        target = os.path.join(str(tmp_path), "out", "q.csv")
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["close", "volume"],
                              start_date="2026-08-06", end_date="2026-08-07", export_path=target)
        assert r["ok"] is True and r["path"] == target
        assert r["total_items"] == 2 and "rows" not in r
        with open(target, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        assert lines[0] == "date,close,volume"
        assert lines[1] == "2026-08-06,11.0,1000"

    def test_weekly_aggregation(self, tmp_path, monkeypatch):
        # 2026-06-01(周一) ~ 2026-06-05(周五) 同一周
        rows = []
        for i, d in enumerate(["2026-06-01", "2026-06-03", "2026-06-05"]):
            rows.append({"date": d, "open": 10.0 + i, "high": 15.0 + i, "low": 9.0 + i,
                         "close": 11.0 + i, "volume": 100 + i})
        monkeypatch.setattr(service, "_ensure_raw",
                            lambda root, mc, start, end: self._ok(rows))
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["open", "high", "low", "close", "volume"],
                              period="weekly", start_date="2026-06-01", end_date="2026-06-05")
        assert len(r["rows"]) == 1
        w = r["rows"][0]
        assert w["open"] == 10.0 and w["close"] == 13.0  # 首日 open、末日 close
        assert w["high"] == 17.0 and w["low"] == 9.0
        assert w["volume"] == 303
        assert w["date"] == "2026-06-05"  # W-FRI
