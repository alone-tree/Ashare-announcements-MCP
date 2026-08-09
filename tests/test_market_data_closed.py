# -*- coding: utf-8 -*-
"""市场收盘时间判断测试：周末/工作日收盘前后/美股夏令时。"""

from datetime import date, datetime, time, timedelta, timezone

from market_data_mcp.routing import _us_dst, is_market_closed


def _bj(y, m, d, hh, mm):
    """北京时间 datetime（naive，视为 UTC+8 语义输入，函数内部按 UTC+8 换算）。"""
    return datetime(y, m, d, hh, mm)


def _utc(y, m, d, hh, mm):
    """UTC datetime（带时区），用于美股场景。"""
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


class TestIsMarketClosed:
    def test_weekend_always_closed(self):
        # 2026-08-09 周日
        assert is_market_closed("A", _bj(2026, 8, 9, 10, 0)) is True
        assert is_market_closed("US", _bj(2026, 8, 9, 10, 0)) is True
        assert is_market_closed("HK", _bj(2026, 8, 9, 10, 0)) is True

    def test_a_share_close_boundary(self):
        assert is_market_closed("A", _bj(2026, 8, 7, 14, 59)) is False  # 周五 14:59 未收盘
        assert is_market_closed("A", _bj(2026, 8, 7, 15, 0)) is True     # 15:00 收盘
        assert is_market_closed("BJ", _bj(2026, 8, 7, 15, 0)) is True

    def test_hk_close_boundary(self):
        assert is_market_closed("HK", _bj(2026, 8, 7, 15, 59)) is False
        assert is_market_closed("HK", _bj(2026, 8, 7, 16, 0)) is True

    def test_us_close_edt(self):
        """夏令时（EDT=UTC-4）：美东 16:00 = 北京时间次日 04:00（2026-08 EDT 期间）。"""
        # 2026-08-07 美东 15:59 = UTC 19:59 = 北京 08-08 03:59
        assert is_market_closed("US", _utc(2026, 8, 7, 19, 59)) is False
        # 美东 16:00 = UTC 20:00 = 北京 08-08 04:00
        assert is_market_closed("US", _utc(2026, 8, 7, 20, 0)) is True

    def test_us_close_est(self):
        """冬令时（EST=UTC-5）：美东 16:00 = UTC 21:00（2026-12 不在 EDT 期间）。"""
        assert is_market_closed("US", _utc(2026, 12, 4, 20, 59)) is False
        assert is_market_closed("US", _utc(2026, 12, 4, 21, 0)) is True

    def test_us_dst_rules(self):
        # 2026 年：EDT 3/8 ~ 11/1
        assert _us_dst(date(2026, 3, 8)) is True
        assert _us_dst(date(2026, 3, 7)) is False
        assert _us_dst(date(2026, 11, 1)) is False
        assert _us_dst(date(2026, 10, 31)) is True
        assert _us_dst(date(2026, 7, 15)) is True
        assert _us_dst(date(2026, 1, 15)) is False
