"""market_data_mcp 无网络单元测试：市场识别/参数校验/记录转换。"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, "src")

from market_data_mcp import service


class _FakeDf:
    """模拟 DataFrame 最小接口（to_dict / where / 列判断）。"""

    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    def __iter__(self):
        return iter(self._rows)

    def __getitem__(self, key):
        if key == "REPORT_DATE":
            return _FakeSeries([r.get("REPORT_DATE") for r in self._rows])
        if key == "date":
            return _FakeSeries([r.get("date") for r in self._rows])
        if key == "close_raw":
            return _FakeSeries([r.get("close_raw", r.get("close")) for r in self._rows])
        raise KeyError(key)

    @property
    def iloc(self):
        return _FakeIloc(self._rows)

    @property
    def columns(self):
        return list(self._rows[0].keys()) if self._rows else []

    def to_dict(self, orient: str = "records"):
        return self._rows

    def where(self, cond, other=None):
        return self

    def __getattr__(self, name):
        if name in ("str", "astype", "replace"):
            return lambda *a, **k: self
        raise AttributeError(name)


class _FakeIloc:
    def __init__(self, rows):
        self._rows = rows

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return self._rows[idx]
        raise IndexError(idx)


class _FakeSeries:
    def __init__(self, values):
        self._values = values
        self.str = _FakeStrAccessor(self._values)

    def astype(self, _t):
        return self


class _FakeStrAccessor:
    def __init__(self, values):
        self._values = values

    def startswith(self, prefixes):
        return [str(v).startswith(tuple(prefixes)) for v in self._values]


def test_detect_market_routes():
    assert service._resolve_market("300476") == ("a", "300476")
    assert service._resolve_market("00700") == ("hk", "00700")
    assert service._resolve_market("AAPL") == ("us", "AAPL")
    assert service._resolve_market("US:AAPL") == ("us", "AAPL")
    assert service._resolve_market("HK:00700") == ("hk", "00700")


def test_get_quote_rejects_bad_adjust():
    with pytest.raises(ValueError, match="adjust"):
        service.get_quote("300476", "2026-01-01", "2026-01-31", adjust="bad")


def test_get_financial_statements_rejects_bad_statements():
    with pytest.raises(ValueError, match="statements"):
        service.get_financial_statements("300476", statements=["bad"])


def test_get_company_profile_rejects_bad_sections():
    with pytest.raises(ValueError, match="sections"):
        service.get_company_profile("300476", sections=["bad"])


def test_filter_by_period():
    import pandas as pd

    df = pd.DataFrame(
        {
            "REPORT_DATE": ["2025-12-31", "2025-06-30", "2024-12-31"],
            "v": [1, 2, 3],
        }
    )
    out = service.filter_by_period(df, ["2025"])
    assert len(out) == 2
    assert list(out["v"]) == [1, 2]


def test_df_to_records():
    df = _FakeDf([{"a": 1, "b": None}])
    records = service._df_to_records(df)
    assert records == [{"a": 1, "b": None}]


def test_get_quote_empty_raises():
    with patch("market_data_mcp.service.MARKET_MODULES") as mods:
        mods.__getitem__ = lambda self, k: _EmptyMod()
        with pytest.raises(ValueError, match="未获取到"):
            service.get_quote("300476", "2026-01-01", "2026-01-31")


def test_get_quote_rejects_bad_period():
    with pytest.raises(ValueError, match="period"):
        service.get_quote("300476", "2026-01-01", "2026-01-31", period="yearly")


def test_get_quote_fields_filter_without_network():
    """fields 过滤逻辑：patch 掉 fetch_daily 后验证字段裁剪。"""
    df_rows = [
        {"date": "2026-07-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0, "amount": 150.0, "source": "sina"}
    ]
    fake_df = _FakeDf(df_rows)

    with patch("market_data_mcp.service.MARKET_MODULES") as mods, patch("market_data_mcp.service._fetch_shares", return_value=None):
        mod = _FakeMod(fake_df)
        mods.__getitem__ = lambda self, k: mod
        result = service.get_quote("300476", "2026-07-01", "2026-07-05", fields=["date", "close"])
    assert result["fields"] == ["date", "close"]
    assert list(result["rows"][0].keys()) == ["date", "close"]


def test_get_quote_fields_invalid_reports():
    df_rows = [
        {"date": "2026-07-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0, "amount": 150.0, "source": "sina"}
    ]
    fake_df = _FakeDf(df_rows)
    with patch("market_data_mcp.service.MARKET_MODULES") as mods, patch("market_data_mcp.service._fetch_shares", return_value=None):
        mod = _FakeMod(fake_df)
        mods.__getitem__ = lambda self, k: mod
        with pytest.raises(ValueError, match="不可用字段"):
            service.get_quote("300476", "2026-07-01", "2026-07-05", fields=["bogus"])


class _FakeMod:
    def __init__(self, df):
        self._df = df

    def fetch_daily(self, *a, **k):
        return self._df

    def fetch_raw_close(self, *a, **k):
        return self._df


def test_resample_ohlcv_weekly():
    from market_data_mcp.providers._common import resample_ohlcv
    import pandas as pd

    df = pd.DataFrame(
        {
            "date": ["2026-06-01", "2026-06-02", "2026-06-08", "2026-06-09"],
            "open": [100.0, 102.0, 110.0, 112.0],
            "high": [103.0, 105.0, 113.0, 115.0],
            "low": [99.0, 101.0, 109.0, 111.0],
            "close": [102.0, 104.0, 112.0, 114.0],
            "volume": [1000, 2000, 3000, 4000],
            "amount": [100000.0, 200000.0, 300000.0, 400000.0],
        }
    )
    out = resample_ohlcv(df, "weekly")
    # 6-01 和 6-08 分属不同周（周五为界），应聚合为 2 周
    assert len(out) == 2
    first = out.iloc[0]
    assert first["open"] == 100.0  # 周首日开盘
    assert first["high"] == 105.0  # 周内最高
    assert first["low"] == 99.0  # 周内最低
    assert first["close"] == 104.0  # 周末日收盘
    assert first["volume"] == 3000  # 周累计
    assert first["amount"] == 300000.0


def test_resample_ohlcv_monthly():
    from market_data_mcp.providers._common import resample_ohlcv
    import pandas as pd

    df = pd.DataFrame(
        {
            "date": ["2026-01-05", "2026-01-20", "2026-02-10"],
            "open": [10.0, 11.0, 20.0],
            "high": [12.0, 13.0, 22.0],
            "low": [9.0, 10.0, 19.0],
            "close": [11.0, 12.0, 21.0],
            "volume": [100, 200, 300],
            "amount": [1000.0, 2000.0, 3000.0],
        }
    )
    out = resample_ohlcv(df, "monthly")
    assert len(out) == 2
    assert out.iloc[0]["open"] == 10.0
    assert out.iloc[0]["close"] == 12.0
    assert out.iloc[1]["open"] == 20.0
    assert out.iloc[1]["close"] == 21.0


class _EmptyMod:
    def fetch_daily(self, *a, **k):
        return None
