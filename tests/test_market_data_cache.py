# -*- coding: utf-8 -*-
"""缓存模块测试：9 字段文件、items [{date,value,source}]、merge 多源并存、覆盖判定。"""

import json
from datetime import datetime

from market_data_mcp import cache


def _read_raw(root: str, code: str, field: str):
    with open(cache.cache_path(root, code, field), encoding="utf-8") as f:
        return json.load(f)


class TestCacheFiles:
    def test_field_files(self):
        """9 个字段级 json（2026-08-09 用户拍板）。"""
        assert set(cache.DATA_FILES) == {
            "open", "high", "low", "close", "close_hfq",
            "volume", "amount", "total_shares", "floating_shares",
        }

    def test_write_read_roundtrip(self, tmp_path):
        root = str(tmp_path)
        path = cache.write_cache(
            root, "600519.SH", "close",
            meta={"code": "600519.SH", "market": "A", "field": "close", "source": "sina"},
            items=[{"date": "2026-08-01", "value": 1.0, "source": "sina"}],
        )
        assert path == cache.cache_path(root, "600519.SH", "close")
        raw = _read_raw(root, "600519.SH", "close")
        assert raw["items"][0] == {"date": "2026-08-01", "value": 1.0, "source": "sina"}
        assert raw["meta"]["shape"] == {"rows": 1}
        got = cache.read_cache(root, "600519.SH", "close")
        assert got is not None and got["meta"]["source"] == "sina"

    def test_unknown_field(self, tmp_path):
        with __import__("pytest").raises(ValueError):
            cache.cache_path(str(tmp_path), "600519.SH", "nope")


class TestMergeItems:
    def test_same_source_overwrites_same_date(self):
        """同 date 同 source：新数据覆盖。"""
        existing = [{"date": "2026-08-01", "value": 1.0, "source": "sina"}]
        fresh = [{"date": "2026-08-01", "value": 2.0, "source": "sina"}]
        merged = cache.merge_items(existing, fresh)
        assert merged == [{"date": "2026-08-01", "value": 2.0, "source": "sina"}]

    def test_multi_source_coexist(self):
        """同 date 异 source：并存（便于追踪/后期加源）。"""
        existing = [{"date": "2026-08-01", "value": 1.0, "source": "sina"}]
        fresh = [{"date": "2026-08-01", "value": 1.1, "source": "ifind"}]
        merged = cache.merge_items(existing, fresh)
        assert len(merged) == 2
        assert merged[0]["source"] == "ifind"  # 排序 (date, source)

    def test_sorted_by_date_then_source(self):
        existing = [{"date": "2026-08-03", "value": 3.0, "source": "sina"}]
        fresh = [{"date": "2026-08-01", "value": 1.0, "source": "ifind"}]
        merged = cache.merge_items(existing, fresh)
        assert [x["date"] for x in merged] == ["2026-08-01", "2026-08-03"]


class TestCoverage:
    """覆盖判定：实际数据范围优先；终点不足时按 updated_at 短期复用 10 分钟。"""

    def _meta(self, start=None, end=None, updated_at=None):
        meta = {"date_range": {"start": start, "end": end}}
        if updated_at is not None:
            meta["updated_at"] = updated_at
        return meta

    def test_full_cover(self):
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), "2026-03-01", "2026-06-30")

    def test_missing_start_never_uses_retry_window(self):
        meta = self._meta("2026-03-01", "2026-12-31", "2026-08-25T10:00:00")
        assert not cache.coverage(meta, "2026-01-01", "2026-06-30",
                                  now=datetime(2026, 8, 25, 10, 5))

    def test_exact_boundary_ok(self):
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), "2026-01-01", "2026-12-31")

    def test_none_bounds_unconstrained(self):
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), None, None)
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), "2026-06-01", None)
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), None, "2026-06-30")

    def test_incomplete_end_reuses_cache_within_ten_minutes(self):
        meta = self._meta("2026-01-01", "2026-08-24", "2026-08-25T10:00:00")
        assert cache.coverage(meta, "2026-03-01", "2026-08-25",
                              now=datetime(2026, 8, 25, 10, 9, 59))

    def test_incomplete_end_retries_at_ten_minutes(self):
        meta = self._meta("2026-01-01", "2026-08-24", "2026-08-25T10:00:00")
        assert not cache.coverage(meta, "2026-03-01", "2026-08-25",
                                  now=datetime(2026, 8, 25, 10, 10))

    def test_future_updated_at_retries(self):
        """系统时钟回拨或异常未来时间不能无限复用不完整缓存。"""
        meta = self._meta("2026-01-01", "2026-08-24", "2026-08-25T10:01:00")
        assert not cache.coverage(meta, "2026-03-01", "2026-08-25",
                                  now=datetime(2026, 8, 25, 10, 0))

    def test_incomplete_without_updated_at_retries(self):
        assert not cache.coverage(self._meta("2026-01-01", "2026-08-24"),
                                  "2026-03-01", "2026-08-25")

    def test_legacy_probe_fields_are_ignored(self):
        meta = self._meta("2026-01-01", "2026-08-24", "2026-08-25T09:00:00")
        meta.update({"verified_until": "2026-08-25",
                     "last_probe": {"state": "closed", "date": "2026-08-25"}})
        assert not cache.coverage(meta, "2026-03-01", "2026-08-25",
                                  now=datetime(2026, 8, 25, 10, 0))

    def test_no_date_range(self):
        assert not cache.coverage({"x": 1}, "2026-01-01", "2026-06-30")
