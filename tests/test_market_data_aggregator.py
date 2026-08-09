# -*- coding: utf-8 -*-
"""字段聚合器测试：缓存覆盖判定、字段链补拉、全链失败。"""

from market_data_mcp import aggregator, cache
from market_data_mcp.routing import parse_code


def _write_raw(root, code, rows, start, end):
    cache.write_cache(root, code, "quote_daily_raw",
                      meta={"code": code, "market": "A", "data_type": "quote_daily_raw",
                            "source": "sina", "date_range": {"start": start, "end": end}},
                      items=rows)


def _fetcher(result):
    """构造一个记录调用并返回指定结果的 fetcher。"""
    calls = []

    def f(root, mc, start=None, end=None):
        calls.append((start, end))
        return result
    f.calls = calls
    return f


class TestEnsure:
    def test_cache_full_cover_no_fetch(self, tmp_path):
        root = str(tmp_path)
        _write_raw(root, "600519.SH", [{"date": "2026-08-01", "close": 1.0}],
                   "2026-01-01", "2026-12-31")
        f = _fetcher({"ok": True, "path": None, "source": "sina"})
        r = aggregator.ensure(root, parse_code("600519.SH"), "quote_daily_raw",
                              [f], start="2026-03-01", end="2026-06-30")
        assert r["ok"] is True and r["source"] == "sina"
        assert f.calls == []  # 未触发补拉

    def test_partial_cover_triggers_fetch(self, tmp_path):
        root = str(tmp_path)
        _write_raw(root, "600519.SH", [{"date": "2026-08-01", "close": 1.0}],
                   "2026-01-01", "2026-06-30")
        r = aggregator.ensure(root, parse_code("600519.SH"), "quote_daily_raw",
                              [_fetcher({"ok": True, "source": "sina", "path": "/x"})],
                              start="2026-03-01", end="2026-12-31")
        # 缓存部分覆盖：返回已有缓存 + notes 标注缺失（不假装完整）
        assert r["ok"] is True
        assert any("覆盖不完整" in n for n in r["notes"])

    def test_chain_tries_next_source(self, tmp_path):
        root = str(tmp_path)
        bad = _fetcher({"ok": False, "source": "sina", "error": "新浪请求失败"})
        good = _fetcher({"ok": True, "source": "ifind", "path": None, "new_items": 0})
        # 直接返回成功（无缓存时 path=None 且 ok=True 视为"无新数据"）
        r = aggregator.ensure(root, parse_code("AAPL.US"), "quote_daily_hfq",
                              [bad, good], start="2026-08-01")
        assert bad.calls and good.calls  # 第一源失败后尝试第二源

    def test_all_fail_structured(self, tmp_path):
        root = str(tmp_path)
        bad1 = _fetcher({"ok": False, "source": "sina", "error": "连接超时"})
        bad2 = _fetcher({"ok": False, "source": "ifind", "error": "登录失败"})
        r = aggregator.ensure(root, parse_code("AAPL.US"), "quote_daily_hfq",
                              [bad1, bad2], start="2026-08-01")
        assert r["ok"] is False
        assert "登录失败" in r["error"]

    def test_no_date_range_no_cover(self, tmp_path):
        root = str(tmp_path)
        cache.write_cache(root, "600519.SH", "quote_daily_raw",
                          meta={"code": "600519.SH", "market": "A", "data_type": "quote_daily_raw",
                                "source": "sina", "date_range": None},
                          items=[{"date": "2026-08-01", "close": 1.0}])
        f = _fetcher({"ok": True, "source": "sina", "path": None})
        r = aggregator.ensure(root, parse_code("600519.SH"), "quote_daily_raw",
                              [f], start="2026-08-01")
        assert f.calls  # date_range 缺失视为不覆盖，触发补拉
