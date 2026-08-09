# -*- coding: utf-8 -*-
"""缓存模块测试：读写往返、meta 自动字段、覆盖判定。"""

import json
import os

from market_data_mcp import cache


def _read_raw(root: str, code: str, data_type: str):
    with open(cache.cache_path(root, code, data_type), encoding="utf-8") as f:
        return json.load(f)


class TestCacheReadWrite:
    def test_write_read_roundtrip(self, tmp_path):
        root = str(tmp_path)
        path = cache.write_cache(
            root, "600519.SH", "quote_daily_raw",
            meta={"code": "600519.SH", "market": "A", "data_type": "quote_daily_raw", "source": "sina"},
            items=[{"date": "2026-08-01", "close": 1.0}],
        )
        assert path == cache.cache_path(root, "600519.SH", "quote_daily_raw")
        raw = _read_raw(root, "600519.SH", "quote_daily_raw")
        assert raw["items"][0]["close"] == 1.0
        # meta 自动字段
        assert raw["meta"]["updated_at"]
        assert raw["meta"]["date_range"] is None
        assert raw["meta"]["shape"] == {"rows": 1}
        # read_cache 往返
        got = cache.read_cache(root, "600519.SH", "quote_daily_raw")
        assert got is not None and got["meta"]["source"] == "sina"

    def test_unknown_data_type(self, tmp_path):
        with __import__("pytest").raises(ValueError):
            cache.cache_path(str(tmp_path), "600519.SH", "nope")

    def test_read_missing_returns_none(self, tmp_path):
        assert cache.read_cache(str(tmp_path), "600519.SH", "quote_daily_raw") is None

    def test_data_root_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MARKET_DATA_ROOT", str(tmp_path))
        assert cache.data_root() == str(tmp_path)
        monkeypatch.delenv("MARKET_DATA_ROOT")
        assert cache.data_root("/x") == "/x"


class TestCoverage:
    """覆盖判定：c_start ≤ start 且 c_end ≥ end 才算够（完整覆盖）。"""

    def _meta(self, start=None, end=None):
        return {"date_range": {"start": start, "end": end}}

    def test_full_cover(self):
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), "2026-03-01", "2026-06-30")

    def test_missing_end(self):
        assert not cache.coverage(self._meta("2026-01-01", "2026-06-30"), "2026-03-01", "2026-07-01")

    def test_missing_start(self):
        assert not cache.coverage(self._meta("2026-03-01", "2026-12-31"), "2026-01-01", "2026-06-30")

    def test_both_missing(self):
        assert not cache.coverage(self._meta("2026-03-01", "2026-06-30"), "2026-01-01", "2026-12-31")

    def test_exact_boundary_ok(self):
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), "2026-01-01", "2026-12-31")

    def test_none_bounds_unconstrained(self):
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), None, None)
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), "2026-06-01", None)
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), None, "2026-06-30")

    def test_no_date_range(self):
        assert not cache.coverage({"source": "sina"}, "2026-01-01", "2026-12-31")
