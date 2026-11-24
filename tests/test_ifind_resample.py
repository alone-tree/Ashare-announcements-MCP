# -*- coding: utf-8 -*-
"""ifind_excel_tool 历史行情周/月线聚合测试：口径手算核对、与 market-data 等价、CLI period 接入。"""

import pandas as pd
import pytest

from ifind_excel_tool import cli, resample, scenes

FIELD_MAP = {
    "open": "开盘价", "high": "最高价", "low": "最低价",
    "close": "收盘价", "volume": "成交量", "amount": "成交额",
}


def _daily(rows):
    """rows: (date, open, high, low, close, volume, amount) → 日线记录（中文键）。"""
    keys = ["date", "开盘价", "最高价", "最低价", "收盘价", "成交量", "成交额"]
    return [dict(zip(keys, r)) for r in rows]


# 两周交易日（2024-01-02 周二 ~ 2024-01-12 周五）加跨月样本。
DAILY = _daily([
    ("2024-01-02", 10, 12, 9, 11, 100, 1000),
    ("2024-01-03", 11, 14, 10, 13, 200, 2600),
    ("2024-01-04", 13, 15, 12, 14, 150, 2100),
    ("2024-01-05", 14, 16, 13, 15, 120, 1800),
    ("2024-01-08", 15, 17, 14, 16, 130, 2080),
    ("2024-01-09", 16, 18, 15, 17, 140, 2380),
    ("2024-01-10", 17, 19, 16, 18, 160, 2880),
    ("2024-01-11", 18, 20, 17, 19, 170, 3230),
    ("2024-01-12", 19, 21, 18, 20, 180, 3600),
    ("2024-01-15", 20, 22, 19, 21, 190, 3990),
    ("2024-01-16", 21, 23, 20, 22, 200, 4400),
    ("2024-01-31", 22, 25, 21, 24, 210, 5040),
    ("2024-02-01", 24, 26, 23, 25, 220, 5500),
    ("2024-02-02", 25, 27, 24, 26, 230, 5980),
])


def test_weekly_ohlcv_hand_computed():
    out = resample.resample_ohlcv(DAILY, "weekly", FIELD_MAP)
    # W-FRI：2024-01-02~05 → 01-05；01-08~12 → 01-12；01-15~16 → 01-19；01-31~02-02 → 02-02
    assert [r["date"] for r in out] == ["2024-01-05", "2024-01-12", "2024-01-19", "2024-02-02"]
    first = out[0]
    assert (first["开盘价"], first["最高价"], first["最低价"], first["收盘价"]) == (10, 16, 9, 15)
    assert first["成交量"] == 570          # 100+200+150+120
    assert first["成交额"] == 7500         # 1000+2600+2100+1800
    assert out[1]["开盘价"] == 15 and out[1]["收盘价"] == 20
    assert out[1]["最高价"] == 21 and out[1]["最低价"] == 14
    assert out[1]["成交量"] == 780         # 130+140+160+170+180
    assert out[3]["开盘价"] == 22 and out[3]["收盘价"] == 26   # 跨月首日/末日
    assert out[3]["成交量"] == 660         # 210+220+230


def test_monthly_ohlcv_hand_computed():
    out = resample.resample_ohlcv(DAILY, "monthly", FIELD_MAP)
    assert [r["date"] for r in out] == ["2024-01-31", "2024-02-29"]
    jan = out[0]
    assert (jan["开盘价"], jan["最高价"], jan["最低价"], jan["收盘价"]) == (10, 25, 9, 24)
    assert jan["成交量"] == 100 + 200 + 150 + 120 + 130 + 140 + 160 + 170 + 180 + 190 + 200 + 210
    assert jan["成交额"] == sum(r["成交额"] for r in DAILY if r["date"].startswith("2024-01"))
    feb = out[1]
    assert (feb["开盘价"], feb["最高价"], feb["最低价"], feb["收盘价"]) == (24, 27, 23, 26)
    assert feb["成交量"] == 220 + 230


def test_daily_and_empty_passthrough():
    assert resample.resample_ohlcv(DAILY, "daily", FIELD_MAP) is DAILY
    assert resample.resample_ohlcv([], "weekly", FIELD_MAP) == []
    with pytest.raises(ValueError, match="不支持的周期"):
        resample.resample_ohlcv(DAILY, "yearly", FIELD_MAP)


def test_extra_columns_take_last_value():
    rows = [dict(r, code="600519.SH", note=f"n{i}") for i, r in enumerate(DAILY)]
    out = resample.resample_ohlcv(rows, "weekly", FIELD_MAP)
    assert out[0]["code"] == "600519.SH"
    assert out[0]["note"] == "n3"   # 第一周最后交易日 01-05 的下标 3


def test_equivalent_to_market_data_resample_ohlcv():
    """与 market-data 的 _common.resample_ohlcv 口径逐字段等价（仅测试侧 import）。"""
    from market_data_mcp.providers._common import resample_ohlcv as md_resample

    ref = md_resample(pd.DataFrame(DAILY).rename(columns={v: k for k, v in FIELD_MAP.items()}), "weekly")
    ref = ref.rename(columns={k: v for k, v in FIELD_MAP.items()})
    mine = pd.DataFrame(resample.resample_ohlcv(DAILY, "weekly", FIELD_MAP))
    pd.testing.assert_frame_equal(
        mine[["date", "开盘价", "最高价", "最低价", "收盘价", "成交量", "成交额"]].reset_index(drop=True),
        ref[["date", "开盘价", "最高价", "最低价", "收盘价", "成交量", "成交额"]].reset_index(drop=True),
        check_dtype=False,
    )


class _FakeEngine:
    """替换 engine.fetch_matrix，返回按日线展开的裸值矩阵。"""

    def __init__(self, values):
        self.values = values
        self.calls = []

    def fetch_matrix(self, matrix, **kwargs):
        self.calls.append(matrix)
        return {"values": self.values}


def test_cli_period_default_daily_and_validation(monkeypatch):
    spec = scenes.load_scene("历史行情")
    # 一行日线的矩阵：hidden判定 + 6字段；值顺序按 fields 定义。
    values = [[1, 11, 10, 12, 9, 100, 1000]]
    fake = _FakeEngine(values)
    monkeypatch.setattr(cli.engine, "fetch_matrix", fake.fetch_matrix)

    daily = cli.fetch_scene({"scene": "历史行情", "code": "600519.SH",
                             "start": "2024-01-02", "end": "2024-01-02"})
    assert daily["ok"] is True and daily["period"] == "daily"
    assert daily["records"][0]["收盘价"] == 11

    bad = cli.fetch_scene({"scene": "历史行情", "code": "600519.SH", "period": "yearly"})
    assert bad["ok"] is False and "不支持的周期" in bad["error"]
    assert len(fake.calls) == 1   # 非法周期不触发取数


def test_cli_weekly_returns_aggregated_records(monkeypatch):
    # 用裸元组构造矩阵：场景字段顺序为 hidden、收盘、开盘、最高、最低、量、额。
    raw = [
        ("2024-01-02", 10, 12, 9, 11, 100, 1000),
        ("2024-01-03", 11, 14, 10, 13, 200, 2600),
        ("2024-01-04", 13, 15, 12, 14, 150, 2100),
        ("2024-01-05", 14, 16, 13, 15, 120, 1800),
    ]
    values = [[1, c, o, h, l, v, a] for _, o, h, l, c, v, a in raw]
    fake = _FakeEngine(values)
    monkeypatch.setattr(cli.engine, "fetch_matrix", fake.fetch_matrix)
    resp = cli.fetch_scene({"scene": "历史行情", "code": "600519.SH", "period": "weekly",
                            "start": "2024-01-02", "end": "2024-01-05"})
    assert resp["ok"] is True and resp["period"] == "weekly" and resp["rows"] == 1
    rec = resp["records"][0]
    assert rec["date"] == "2024-01-05"
    assert (rec["开盘价"], rec["最高价"], rec["最低价"], rec["收盘价"]) == (10, 16, 9, 15)
    assert rec["成交量"] == 570
