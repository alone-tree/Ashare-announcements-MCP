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
    """覆盖判定：c_start ≤ start 且 c_end ≥ end（末尾容忍 ≤7 天缺口）。"""

    def _meta(self, start=None, end=None):
        return {"date_range": {"start": start, "end": end}}

    def test_full_cover(self):
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), "2026-03-01", "2026-06-30")

    def test_missing_start(self):
        assert not cache.coverage(self._meta("2026-03-01", "2026-12-31"), "2026-01-01", "2026-06-30")

    def test_exact_boundary_ok(self):
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), "2026-01-01", "2026-12-31")

    def test_none_bounds_unconstrained(self):
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), None, None)
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), "2026-06-01", None)
        assert cache.coverage(self._meta("2026-01-01", "2026-12-31"), None, "2026-06-30")

    def test_verified_until_covers_end(self):
        """探测验证：verified_until ≥ end → 视为覆盖（周末场景零请求）。"""
        meta = self._meta("2026-01-01", "2026-08-07")
        meta["verified_until"] = "2026-08-09"
        meta["verified_at"] = "2026-08-09T10:00:00"
        assert cache.coverage(meta, "2026-03-01", "2026-08-09")

    def test_verified_until_not_enough(self):
        meta = self._meta("2026-01-01", "2026-08-07")
        meta["verified_until"] = "2026-08-09"
        assert not cache.coverage(meta, "2026-03-01", "2026-08-10")  # 超出验证范围 → 补拉

    def test_verified_without_meta_field(self):
        assert not cache.coverage(self._meta("2026-01-01", "2026-08-07"), "2026-03-01", "2026-08-09")

    def test_no_date_range(self):
        assert not cache.coverage({"x": 1}, "2026-01-01", "2026-06-30")


class TestSetVerified:
    def _write(self, root, code="600519.SH"):
        cache.write_cache(root, code, "close",
                          meta={"code": code, "market": "A", "field": "close", "source": "sina",
                                "date_range": {"start": "2026-08-06", "end": "2026-08-07"}},
                          items=[{"date": "2026-08-06", "value": 1.0, "source": "sina"}])

    def test_friday_probe_extends_to_sunday(self, tmp_path):
        """周五收盘后探测 → verified_until 延伸到周日（周末确定无数据）。"""
        root = str(tmp_path)
        self._write(root)
        cache.set_verified(root, "600519.SH", "close", "2026-08-07",
                           now=datetime(2026, 8, 7, 15, 30))
        meta = cache.read_cache(root, "600519.SH", "close")["meta"]
        assert meta["verified_until"] == "2026-08-09"
        assert meta["verified_at"] == "2026-08-07T15:30:00"
        # 周六/周日请求命中（零请求）；周一不命中 → 补拉
        assert cache.coverage(meta, "2026-08-06", "2026-08-08") is True
        assert cache.coverage(meta, "2026-08-06", "2026-08-09") is True
        assert cache.coverage(meta, "2026-08-06", "2026-08-10") is False

    def test_monday_probe_no_extension(self, tmp_path):
        """周一~周四不延伸（次日可能出数据）。"""
        root = str(tmp_path)
        self._write(root)
        cache.set_verified(root, "600519.SH", "close", "2026-08-10",
                           now=datetime(2026, 8, 10, 15, 30))
        meta = cache.read_cache(root, "600519.SH", "close")["meta"]
        assert meta["verified_until"] == "2026-08-10"
        assert cache.coverage(meta, "2026-08-06", "2026-08-10") is True
        assert cache.coverage(meta, "2026-08-06", "2026-08-11") is False

    def test_preserves_items(self, tmp_path):
        root = str(tmp_path)
        self._write(root)
        cache.set_verified(root, "600519.SH", "close", "2026-08-09",
                           now=datetime(2026, 8, 9, 12, 0))
        data = cache.read_cache(root, "600519.SH", "close")
        assert data["items"] == [{"date": "2026-08-06", "value": 1.0, "source": "sina"}]
