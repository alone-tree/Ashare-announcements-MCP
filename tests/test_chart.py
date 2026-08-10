# -*- coding: utf-8 -*-
"""chart MCP 测试：K线/折线绘图、start=all、log_scale 回退、CLI 双入口。

绘图测试不联网：用伪造的行情缓存目录 + monkeypatch get_quote 返回固定 rows。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chart_mcp import service as chart_service
from market_data_mcp import service as md_service

# 固定行情：12 天日线（够画 MA5/10，MA20/60 不足应不绘制）
ROWS = [
    {"date": "2026-01-02", "open": 10.0, "high": 10.8, "low": 9.9, "close": 10.5, "volume": 1000.0},
    {"date": "2026-01-03", "open": 10.5, "high": 11.0, "low": 10.3, "close": 10.9, "volume": 1200.0},
    {"date": "2026-01-06", "open": 10.9, "high": 11.2, "low": 10.6, "close": 10.8, "volume": 900.0},
    {"date": "2026-01-07", "open": 10.8, "high": 11.5, "low": 10.7, "close": 11.4, "volume": 1500.0},
    {"date": "2026-01-08", "open": 11.4, "high": 11.6, "low": 11.0, "close": 11.2, "volume": 1300.0},
    {"date": "2026-01-09", "open": 11.2, "high": 11.3, "low": 10.5, "close": 10.6, "volume": 1100.0},
    {"date": "2026-01-10", "open": 10.6, "high": 10.9, "low": 10.2, "close": 10.4, "volume": 800.0},
    {"date": "2026-01-13", "open": 10.4, "high": 10.7, "low": 10.1, "close": 10.2, "volume": 700.0},
    {"date": "2026-01-14", "open": 10.2, "high": 10.6, "low": 10.0, "close": 10.5, "volume": 950.0},
    {"date": "2026-01-15", "open": 10.5, "high": 11.0, "low": 10.4, "close": 10.9, "volume": 1050.0},
    {"date": "2026-01-16", "open": 10.9, "high": 11.1, "low": 10.6, "close": 10.7, "volume": 880.0},
    {"date": "2026-01-17", "open": 10.7, "high": 11.0, "low": 10.3, "close": 10.4, "volume": 920.0},
]


@pytest.fixture
def fake_root(tmp_path):
    """临时数据根：cache/_charts/ 目录 + 最小 config.yaml 无关项。"""
    charts = tmp_path / "cache" / "_charts"
    charts.mkdir(parents=True)
    return str(tmp_path)


@pytest.fixture(autouse=True)
def _fake_quote(monkeypatch, fake_root):
    """monkeypatch get_quote：返回固定 12 天行情（不联网）。"""
    def fake_get_quote(root, code, vars=None, adjust="raw", start_date=None,
                       end_date=None, period="daily", export_path=None):
        v = vars or ["close"]
        rows = []
        for r in ROWS:
            out = {"date": r["date"]}
            for name in v:
                out[name] = r.get(name)
            rows.append(out)
        if period != "daily":
            # 简单聚合：按周（本例不测周聚合细节，直接返回原 rows）
            pass
        start = start_date or "2026-01-02"
        end = end_date or "2026-01-17"
        return {
            "ok": True, "market": "A", "code": code,
            "start": "all" if start_date == "all" else start,
            "end": end_date or "latest",
            "adjust": adjust, "period": period, "vars": v,
            "source": "fake", "notes": None, "rows": rows,
        }
    monkeypatch.setattr(chart_service, "get_quote_service", fake_get_quote)
    yield


def test_kline_png_generated(fake_root):
    r = chart_service.get_quote_chart(fake_root, "600519.SH")
    assert r["ok"], r
    assert r["chart_type"] == "kline"
    assert r["path"].endswith(".png")
    assert os.path.isfile(r["path"])
    assert os.path.getsize(r["path"]) > 10_000
    assert r["rows"] == 12


def test_kline_fields(fake_root):
    r = chart_service.get_quote_chart(fake_root, "600519.SH")
    assert r["ok"], r
    # K线模式必须请求 open/high/low/close/volume（内部 vars）
    assert "kline" in r["chart_type"]


def test_line_png_generated(fake_root):
    r = chart_service.get_quote_chart(fake_root, "00700.HK", field="close")
    assert r["ok"], r
    assert r["chart_type"] == "line"
    assert r["field"] == "close"
    assert os.path.isfile(r["path"])
    assert os.path.getsize(r["path"]) > 5_000


def test_line_invalid_field(fake_root):
    r = chart_service.get_quote_chart(fake_root, "00700.HK", field="volume")
    # volume 折线本期不做（设计 §三.8），应明确报错
    assert not r["ok"]
    assert "open/high/low/close" in r["error"]


def test_ma_not_drawn_when_insufficient(fake_root):
    """均线数据不足不报错（12 天：MA5/10 可画，MA20/60 不足跳过）。"""
    r = chart_service.get_quote_chart(fake_root, "600519.SH")
    assert r["ok"], r


def test_log_scale_fallback_nonpositive(fake_root, monkeypatch):
    """数据含 0/负值时 log_scale 自动退回普通坐标（不报错）。"""
    import chart_mcp.service as svc

    def fake_get_quote_zero(root, code, vars=None, adjust="raw", start_date=None,
                            end_date=None, period="daily", export_path=None):
        rows = [{"date": "2026-01-02", "open": 0.0, "high": 0.0, "low": 0.0,
                 "close": 0.0, "volume": 0.0}]
        return {"ok": True, "market": "A", "code": code, "start": "all",
                "end": "latest", "adjust": adjust, "period": period,
                "vars": vars or ["close"], "source": "fake", "notes": None,
                "rows": rows}
    monkeypatch.setattr(svc, "get_quote_service", fake_get_quote_zero)
    r = svc.get_quote_chart(fake_root, "600519.SH", log_scale=True)
    assert r["ok"], r
    assert r["notes"] and any("退回" in n for n in r["notes"])


def test_log_scale_positive_data(fake_root):
    """数据全为正时 log_scale 生效（无退回提示）。"""
    r = chart_service.get_quote_chart(fake_root, "600519.SH", log_scale=True)
    assert r["ok"], r
    assert not (r.get("notes") and any("退回" in n for n in r["notes"]))


def test_invalid_code(fake_root, monkeypatch):
    import chart_mcp.service as svc

    def fake_get_quote_err(root, code, **kwargs):
        return {"ok": False, "error": "代码格式错误"}
    monkeypatch.setattr(svc, "get_quote_service", fake_get_quote_err)
    r = svc.get_quote_chart(fake_root, "BAD")
    assert not r["ok"]
    assert "error" in r


def test_cli_line_and_kline(fake_root):
    """CLI 双入口：get_quote_chart_batch 画 K线 + 折线。"""
    import chart_mcp.cli as cli_mod

    req = {"tool": "get_quote_chart_batch", "codes": ["600519.SH", "00700.HK"],
           "field": "close"}
    # 单标的折线：600519 用默认 K线，00700 折线——batch 共用参数，此处验证折线路径
    resp = cli_mod.dispatch(req)
    assert resp["ok"]
    assert resp["status"] == "success"
    assert resp["succeeded"] == 2
    assert all(item["chart_type"] == "line" for item in resp["results"])


def test_cli_unknown_tool():
    import chart_mcp.cli as cli_mod
    with pytest.raises(ValueError):
        cli_mod.dispatch({"tool": "nope"})


def test_cli_main_stdin_stdout(fake_root, monkeypatch, capsys):
    """CLI main()：stdin JSON → stdout JSON。"""
    import chart_mcp.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_data_root", lambda: fake_root)
    monkeypatch.setattr(sys, "stdin", type("S", (), {"read": lambda self: json.dumps(
        {"tool": "get_quote_chart_batch", "codes": ["600519.SH"]})})())
    cli_mod.main()
    out = capsys.readouterr().out
    resp = json.loads(out)
    assert resp["ok"]
    assert resp["tool"] == "get_quote_chart_batch"


def test_get_quote_start_all_semantics():
    """get_quote start_date='all'：返回 start='all'，且 end 空=全部、end 指定=早期数据。"""
    # 直接测 service 层分支：start=all 时内部 start 哨兵、resp_start='all'
    import market_data_mcp.service as md_svc

    # 通过 fake 验证参数透传：monkeypatch _ensure_fields 捕获 start/end
    captured = {}

    orig_ensure = md_svc._ensure_fields

    def fake_ensure(root, mc, fields, start, end):
        captured["start"] = start
        captured["end"] = end
        # 返回空字段 → 无数据路径（不联网）
        return {f: {"ok": True, "items": [], "source": "fake", "notes": None}
                for f in fields}

    md_svc._ensure_fields = fake_ensure
    try:
        r = md_svc.get_quote("tmp", "600519.SH", vars=["close"], start_date="all")
        assert r["ok"]
        assert r["start"] == "all"
        assert captured["start"] == "1990-01-01"
        assert captured["end"] is None
        # end 指定时
        r2 = md_svc.get_quote("tmp", "600519.SH", vars=["close"],
                              start_date="all", end_date="2025-06-30")
        assert r2["ok"]
        assert r2["end"] == "2025-06-30"
        assert captured["end"] == "2025-06-30"
    finally:
        md_svc._ensure_fields = orig_ensure


def test_get_quote_start_all_early_data(fake_root, monkeypatch):
    """start=all + end 指定 = 只取 ≤end 的早期数据（行过滤验证）。"""
    import market_data_mcp.service as md_svc

    orig_ensure = md_svc._ensure_fields
    calls = {}

    def fake_ensure(root, mc, fields, start, end):
        calls["start"] = start
        calls["end"] = end
        items = [{"date": "2025-01-01", "value": 100.0, "source": "fake"},
                 {"date": "2025-06-15", "value": 120.0, "source": "fake"},
                 {"date": "2026-06-15", "value": 130.0, "source": "fake"}]
        return {f: {"ok": True, "items": items, "source": "fake", "notes": None}
                for f in fields}

    md_svc._ensure_fields = fake_ensure
    try:
        r = md_svc.get_quote("tmp", "600519.SH", vars=["close"],
                             start_date="all", end_date="2025-12-31")
        assert r["ok"]
        rows = r.get("rows") or []
        dates = [row["date"] for row in rows]
        assert dates == ["2025-01-01", "2025-06-15"]  # 2026 年被过滤
    finally:
        md_svc._ensure_fields = orig_ensure
