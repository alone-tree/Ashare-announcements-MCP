# -*- coding: utf-8 -*-
"""get_quote 工具层测试（mock 字段聚合层，不依赖网络）。

真实调用已单独验证（2026-08-09 字段级重构）：A 股全字段、hfq 因子还原、
qfq、美股 amount+市值、周线、自动导出、纯缓存复用 0.002s 零请求。
"""

import os
from datetime import date, timedelta

import pytest

from market_data_mcp import service


def _field_items(n=2, start="2026-08-06", base=10.0, source="sina"):
    """构造字段缓存 items：date 递增，value = base+i。"""
    d0 = date.fromisoformat(start)
    return [{"date": (d0 + timedelta(days=i)).isoformat(), "value": base + i, "source": source}
            for i in range(n)]


class _FakeEnsure:
    """mock aggregator.ensure：按字段返回预置数据。"""

    def __init__(self, data=None):
        self.data = data or {}
        self.calls = []

    def __call__(self, root, mc, field, chain, start=None, end=None):
        self.calls.append(field)
        if field in self.data:
            items, source = self.data[field]
            return {"ok": True, "items": items, "source": source, "notes": None}
        return {"ok": True, "items": [], "source": None, "notes": None}


def _default_data():
    """默认字段数据：raw 两日（open/high/low/close/volume/amount/floating_shares），股本 iFinD。"""
    n = 2
    return {
        "open": (_field_items(n, base=10.0), "sina"),
        "high": (_field_items(n, base=12.0), "sina"),
        "low": (_field_items(n, base=9.0), "sina"),
        "close": (_field_items(n, base=11.0), "sina"),
        "volume": (_field_items(n, base=1000.0), "sina"),
        "amount": (_field_items(n, base=10000.0), "sina"),
        "floating_shares": (_field_items(n, base=1000000.0), "sina"),
        "total_shares": (_field_items(n, base=1000000.0, source="ifind"), "ifind"),
        "close_hfq": (_field_items(n, base=55.0), "sina"),
    }


class TestGetQuote:
    def test_basic_close(self, tmp_path, monkeypatch):
        fake = _FakeEnsure(_default_data())
        monkeypatch.setattr(service, "aggregator", type("A", (), {"ensure": fake})())
        r = service.get_quote(str(tmp_path), "600519.SH", start_date="2026-08-06", end_date="2026-08-07")
        assert r["ok"] is True and r["code"] == "600519.SH"
        assert r["rows"] == [{"date": "2026-08-06", "close": 11.0},
                             {"date": "2026-08-07", "close": 12.0}]

    def test_vars_filter(self, tmp_path, monkeypatch):
        fake = _FakeEnsure(_default_data())
        monkeypatch.setattr(service, "aggregator", type("A", (), {"ensure": fake})())
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["close", "volume"],
                              start_date="2026-08-06", end_date="2026-08-07")
        assert r["rows"][0] == {"date": "2026-08-06", "close": 11.0, "volume": 1000}

    def test_market_cap_and_turnover(self, tmp_path, monkeypatch):
        fake = _FakeEnsure(_default_data())
        monkeypatch.setattr(service, "aggregator", type("A", (), {"ensure": fake})())
        r = service.get_quote(str(tmp_path), "600519.SH",
                              vars=["close", "volume", "turnover", "outstanding_share",
                                    "total_market_cap", "float_market_cap"],
                              start_date="2026-08-06", end_date="2026-08-07")
        row = r["rows"][0]
        assert row["close"] == 11.0
        assert row["turnover"] == pytest.approx(1000.0 / 1000000.0)  # volume/流通股本
        assert row["outstanding_share"] == 1000000.0
        assert row["total_market_cap"] == 11.0 * 1000000.0
        assert row["float_market_cap"] == 11.0 * 1000000.0
        assert any("估算" in n for n in r["notes"])

    def test_hfq_ohl_restore(self, tmp_path, monkeypatch):
        data = _default_data()
        data["close_hfq"] = (_field_items(2, base=55.0), "sina")
        monkeypatch.setattr(service, "aggregator", type("A", (), {"ensure": _FakeEnsure(data)})())
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["open", "close"],
                              adjust="hfq", start_date="2026-08-06", end_date="2026-08-07")
        # 因子 F = hfq/raw = 55/11 = 5 → open = 10×5 = 50，close = hfq = 55
        assert r["rows"][0]["open"] == 50.0
        assert r["rows"][0]["close"] == 55.0

    def test_qfq_local(self, tmp_path, monkeypatch):
        data = _default_data()
        data["close_hfq"] = (_field_items(2, base=55.0), "sina")  # hfq = [55, 56]
        monkeypatch.setattr(service, "aggregator", type("A", (), {"ensure": _FakeEnsure(data)})())
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["close"],
                              adjust="qfq", start_date="2026-08-06", end_date="2026-08-07")
        # scale = 最新raw/最新hfq = 12/56 → qfq = hfq×scale
        assert r["rows"][1]["close"] == pytest.approx(12.0)  # 最新日 qfq = raw
        assert r["rows"][0]["close"] == pytest.approx(55.0 * 12.0 / 56.0, abs=1e-3)  # 4 位小数舍入

    def test_us_amount(self, tmp_path, monkeypatch):
        data = _default_data()
        data["amount"] = (_field_items(1, base=1.08e10), "ifind")
        data["close"] = (_field_items(1, base=313.33), "sina")
        monkeypatch.setattr(service, "aggregator", type("A", (), {"ensure": _FakeEnsure(data)})())
        r = service.get_quote(str(tmp_path), "AAPL.US", vars=["close", "amount"],
                              start_date="2026-08-06", end_date="2026-08-06")
        assert r["rows"][0]["amount"] == 1.08e10
        assert "ifind" in r["source"]

    def test_partial_field_failure(self, tmp_path, monkeypatch):
        """字段级失败→部分成功：失败字段无数据+notes 标注，其余字段照常返回。"""
        data = _default_data()
        data["close"] = (_field_items(2, base=11.0), "sina")

        def failing(root, mc, field, chain, start, end):
            if field == "amount":
                return {"ok": False, "items": [], "source": None,
                        "error": "上游无该市场成交额数据", "notes": None}
            return _FakeEnsure(data)(root, mc, field, chain, start, end)

        from types import SimpleNamespace
        monkeypatch.setattr(service, "aggregator", SimpleNamespace(ensure=failing))
        r = service.get_quote(str(tmp_path), "AAPL.US", vars=["close", "amount"],
                              start_date="2026-08-06", end_date="2026-08-07")
        assert r["ok"] is True
        assert r["rows"][0]["close"] == 11.0
        assert r["rows"][0]["amount"] is None
        assert any("amount" in n and "获取失败" in n for n in r["notes"])

    def test_all_fields_fail(self, tmp_path, monkeypatch):
        def failing(root, mc, field, chain, start, end):
            return {"ok": False, "items": [], "source": None, "error": "全挂", "notes": None}
        from types import SimpleNamespace
        monkeypatch.setattr(service, "aggregator", SimpleNamespace(ensure=failing))
        r = service.get_quote(str(tmp_path), "AAPL.US", vars=["close"],
                              start_date="2026-08-06", end_date="2026-08-07")
        assert r["ok"] is False and "字段获取失败" in r["error"]

    def test_data_start_hint(self, tmp_path, monkeypatch):
        """请求起点早于数据起点（新股/上游范围）→ notes 通用提示。"""
        items = [{"date": "2026-07-27", "value": 49.0, "source": "sina"}]
        monkeypatch.setattr(service, "aggregator",
                            type("A", (), {"ensure": _FakeEnsure({"close": (items, "sina")})})())
        r = service.get_quote(str(tmp_path), "688825.SH", vars=["close"],
                              start_date="2026-07-01", end_date="2026-07-31")
        assert r["ok"] is True
        assert any("2026-07-27" in n and "数据自" in n for n in r["notes"])

    def test_invalid_params(self, tmp_path, monkeypatch):
        fake = _FakeEnsure(_default_data())
        monkeypatch.setattr(service, "aggregator", type("A", (), {"ensure": fake})())
        assert service.get_quote(str(tmp_path), "600519.SH", adjust="xxx")["ok"] is False
        assert service.get_quote(str(tmp_path), "600519.SH", period="hourly")["ok"] is False
        assert service.get_quote(str(tmp_path), "600519.SH", vars=["pe"])["ok"] is False
        assert service.get_quote(str(tmp_path), "600519")["ok"] is False

    def test_auto_export_over_200(self, tmp_path, monkeypatch):
        items = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                  "value": 10.0 + i, "source": "sina"} for i in range(250)]
        fake = _FakeEnsure({"close": (items, "sina")})
        monkeypatch.setattr(service, "aggregator", type("A", (), {"ensure": fake})())
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["close"],
                              start_date="2025-01-01", end_date="2025-12-31")
        assert r.get("auto_exported") is True
        assert os.path.exists(r["path"]) and "auto_export" in r["path"]
        assert r["total_items"] == 250

    def test_export_path(self, tmp_path, monkeypatch):
        fake = _FakeEnsure(_default_data())
        monkeypatch.setattr(service, "aggregator", type("A", (), {"ensure": fake})())
        target = os.path.join(str(tmp_path), "out", "q.csv")
        r = service.get_quote(str(tmp_path), "600519.SH", vars=["close", "volume"],
                              start_date="2026-08-06", end_date="2026-08-07", export_path=target)
        assert r["ok"] is True and r["path"] == target and "rows" not in r
        with open(target, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        assert lines[0] == "date,close,volume"
        assert lines[1] == "2026-08-06,11.0,1000.0"

    def test_weekly_aggregation(self, tmp_path, monkeypatch):
        items = [{"date": d, "value": v, "source": "sina"}
                 for d, v in [("2026-06-01", 10.0), ("2026-06-03", 11.0), ("2026-06-05", 13.0)]]
        data = {"close": (items, "sina"),
                "open": ([{"date": "2026-06-01", "value": 9.0, "source": "sina"}], "sina"),
                "high": ([{"date": "2026-06-01", "value": 14.0, "source": "sina"},
                          {"date": "2026-06-05", "value": 15.0, "source": "sina"}], "sina"),
                "low": ([{"date": "2026-06-01", "value": 8.0, "source": "sina"}], "sina"),
                "volume": (items, "sina")}
        monkeypatch.setattr(service, "aggregator", type("A", (), {"ensure": _FakeEnsure(data)})())
        r = service.get_quote(str(tmp_path), "600519.SH",
                              vars=["open", "high", "low", "close", "volume"],
                              period="weekly", start_date="2026-06-01", end_date="2026-06-05")
        assert len(r["rows"]) == 1
        w = r["rows"][0]
        assert w["date"] == "2026-06-05"  # W-FRI
        assert w["close"] == 13.0 and w["volume"] == 34.0
