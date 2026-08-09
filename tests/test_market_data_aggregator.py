# -*- coding: utf-8 -*-
"""字段聚合器测试：字段级 ensure、缓存覆盖判定、字段链补拉、全链失败。"""

from market_data_mcp import aggregator, cache
from market_data_mcp.routing import parse_code


def _write_field(root, code, field, rows, start, end, source="sina"):
    cache.write_cache(root, code, field,
                      meta={"code": code, "market": "A", "field": field,
                            "source": source, "date_range": {"start": start, "end": end}},
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
        _write_field(root, "600519.SH", "close", [{"date": "2026-08-01", "value": 1.0, "source": "sina"}],
                     "2026-01-01", "2026-12-31")
        f = _fetcher({"ok": True, "source": "sina", "fields": {}})
        r = aggregator.ensure(root, parse_code("600519.SH"), "close", [f],
                              start="2026-03-01", end="2026-06-30")
        assert r["ok"] is True and r["source"] == "sina"
        assert f.calls == []  # 未触发补拉

    def test_end_gap_within_7_days_no_fetch(self, tmp_path):
        """末尾 ≤7 天缺口（周末）视为覆盖，不补拉。"""
        root = str(tmp_path)
        _write_field(root, "600519.SH", "close", [{"date": "2026-08-07", "value": 1.0, "source": "sina"}],
                     "2026-08-03", "2026-08-07")
        f = _fetcher({"ok": True, "source": "sina", "fields": {}})
        r = aggregator.ensure(root, parse_code("600519.SH"), "close", [f],
                              start="2026-08-03", end="2026-08-09")
        assert f.calls == []

    def test_chain_tries_next_source(self, tmp_path):
        """第一源失败（或不覆盖字段）→ 尝试第二源。"""
        root = str(tmp_path)
        bad = _fetcher({"ok": False, "source": "sina", "fields": {}, "error": "新浪请求失败"})
        good = _fetcher({"ok": True, "source": "ifind", "fields": {"amount": None}})
        r = aggregator.ensure(root, parse_code("AAPL.US"), "amount", [bad, good],
                              start="2026-08-01")
        # good 声明更新 amount 但没写缓存 → 读不到 → 继续，最终无缓存 → ok=False
        assert bad.calls and good.calls

    def test_fetcher_updates_field_confirmed(self, tmp_path, monkeypatch):
        """fetcher 声明更新字段且缓存可读 → 成功返回。"""
        root = str(tmp_path)
        def good(root, mc, start=None, end=None):
            cache.write_cache(root, "600519.SH", "close",
                              meta={"code": "600519.SH", "market": "A", "field": "close",
                                    "source": "sina", "date_range": {"start": "2026-08-06", "end": "2026-08-07"}},
                              items=[{"date": "2026-08-06", "value": 1.0, "source": "sina"}])
            return {"ok": True, "source": "sina", "fields": {"close": {"start": "2026-08-06", "end": "2026-08-07"}}}
        r = aggregator.ensure(root, parse_code("600519.SH"), "close", [good],
                              start="2026-08-06", end="2026-08-07")
        assert r["ok"] is True and r["source"] == "sina"
        assert r["items"][0]["value"] == 1.0

    def test_all_fail_structured(self, tmp_path):
        root = str(tmp_path)
        bad1 = _fetcher({"ok": False, "source": "sina", "fields": {}, "error": "连接超时"})
        bad2 = _fetcher({"ok": False, "source": "ifind", "fields": {}, "error": "登录失败"})
        r = aggregator.ensure(root, parse_code("AAPL.US"), "close_hfq", [bad1, bad2],
                              start="2026-08-01")
        assert r["ok"] is False
        assert "登录失败" in r["error"]
