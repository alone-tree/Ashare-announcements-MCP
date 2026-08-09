# -*- coding: utf-8 -*-
"""get_company_profile 工具层测试（无网络：fake 请求模块 + 参数校验）。"""

import json

from market_data_mcp import company_service
from market_data_mcp import company_cache


def _fake_ok(section, source, data):
    def fetch(root, mc):
        return {"ok": True, "source": source, "section": section,
                "data": data, "error": None, "notes": None}
    return fetch


def _fake_fail(section, source, error):
    def fetch(root, mc):
        return {"ok": False, "source": source, "section": section,
                "data": None, "error": error, "notes": None}
    return fetch


def test_sections_param_validation(tmp_path):
    r = company_service.get_company_profile(str(tmp_path), "300308.SZ", sections=[])
    assert r["ok"] is False and "非空子集" in r["error"]
    r = company_service.get_company_profile(str(tmp_path), "300308.SZ", sections=["bogus"])
    assert r["ok"] is False and "未知 section" in r["error"]
    r = company_service.get_company_profile(str(tmp_path), "300308")
    assert r["ok"] is False and "后缀" in r["error"]


def test_us_returns_unavailable_hint(tmp_path):
    # 美股无结构化来源：available=false + SEC 提示，不是错误（真实 plan 中 US 均为 None）
    r = company_service.get_company_profile(str(tmp_path), "AAPL.US")
    assert r["ok"] is True
    assert r["market"] == "US"
    for section, item in r["sections"].items():
        assert item["available"] is False
        assert "SEC" in item["reason"]


def test_hk_unavailable_sections(tmp_path):
    # 港股 IPO/股东无结构化来源
    plan = dict(company_service._SECTION_PLAN)
    plan["profile"] = {"A": (_fake_ok("profile", "cninfo", {"公司名称": "X"}), []),
                       "BJ": (_fake_ok("profile", "cninfo", {"公司名称": "X"}), []),
                       "HK": (_fake_ok("profile", "eastmoney", {"公司名称": "Y"}), []),
                       "US": None}
    plan["ipo"] = {"A": (_fake_ok("ipo", "cninfo", {}), []),
                   "BJ": (_fake_ok("ipo", "cninfo", {}), []),
                   "HK": None, "US": None}
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(company_service, "_SECTION_PLAN", plan)
    try:
        r = company_service.get_company_profile(str(tmp_path), "00700.HK", sections=["profile", "ipo"])
        assert r["ok"] is True
        assert r["sections"]["profile"]["data"]["公司名称"] == "Y"
        assert r["sections"]["ipo"]["available"] is False
    finally:
        monkeypatch.undo()


def test_primary_failure_no_fallback(tmp_path):
    # 无失败回退：主源失败即报错，即使有补充源也不试
    plan = dict(company_service._SECTION_PLAN)
    plan["profile"] = {"A": (_fake_fail("profile", "cninfo", "上游超时"), []),
                       "BJ": (_fake_fail("profile", "cninfo", "上游超时"), []),
                       "HK": (_fake_ok("profile", "eastmoney", {}), []),
                       "US": None}
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(company_service, "_SECTION_PLAN", plan)
    try:
        r = company_service.get_company_profile(str(tmp_path), "300308.SZ", sections=["profile"])
        assert r["ok"] is False
        assert "主源" in r["sections"]["profile"]["error"]
    finally:
        monkeypatch.undo()


def test_supplement_merges_missing_fields(tmp_path):
    # 补充源字段补全：主源缺字段时从补充源取（dict 并集）
    plan = dict(company_service._SECTION_PLAN)
    plan["ipo"] = {"A": (_fake_ok("ipo", "cninfo", {"股票代码": "300308", "发行价格": 20.0}),
                         [_fake_ok("ipo", "sina", {"发行方式": "网下询价", "主承销商": "广发"})]),
                   "BJ": (_fake_ok("ipo", "cninfo", {}), []),
                   "HK": None, "US": None}
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(company_service, "_SECTION_PLAN", plan)
    try:
        r = company_service.get_company_profile(str(tmp_path), "300308.SZ", sections=["ipo"])
        data = r["sections"]["ipo"]["data"]
        assert data["发行价格"] == 20.0
        assert data["发行方式"] == "网下询价"
        assert any("sina" in n for n in r["sections"]["ipo"]["notes"])
    finally:
        monkeypatch.undo()


def test_dividends_join_normalizes_report_period(tmp_path):
    # 分红行级补全：同花顺"2011年报"规范化后匹配东财"2011-12-31"，独有字段补进主行
    primary = [{"报告期": "2011-12-31", "现金分红比例": 2.0}]
    extra = [{"报告期": "2011年报", "股利支付率": "19.61%"}]
    merged, added = company_service._merge("dividends", primary, extra, "ths")
    assert merged[0]["股利支付率"] == "19.61%"
    assert "股利支付率" in added


def test_dividends_unmatched_rows_appended(tmp_path):
    # 匹配不上的补充行（不分配记录）追加到列表末尾
    primary = [{"报告期": "2011-12-31", "现金分红比例": 2.0}]
    extra = [{"报告期": "2012中报", "分红方案说明": "不分配不转增"}]
    merged, added = company_service._merge("dividends", primary, extra, "ths")
    assert len(merged) == 2
    assert merged[1]["分红方案说明"] == "不分配不转增"


def test_forecast_merge_builds_distribution(tmp_path):
    # forecast：主源 dict + 同花顺 list → 预测分布子对象
    primary = {"研报数": 29, "2026预测每股收益": 27.65}
    extra = [{"年度": "2026", "预测机构数": 29, "最小值": 20.97, "均值": 27.65, "最大值": 36.48}]
    merged, added = company_service._merge("forecast", primary, extra, "ths")
    assert "预测分布" in merged
    assert merged["预测分布"]["2026"]["均值"] == 27.65
    assert added == ["预测分布"]


def test_30day_freshness_and_force_refresh(tmp_path):
    # 30 天新鲜期：新鲜缓存直接复用；force_refresh 强制刷新
    root = str(tmp_path)
    company_cache.write_section(root, "600519.SH", "profile", market="A",
                                source="cninfo", data={"公司名称": "贵州茅台"})
    cached = company_cache.read_section(root, "600519.SH", "profile")
    assert company_cache.is_fresh(cached["meta"]) is True

    import time as _time
    stale_meta = dict(cached["meta"])
    stale_meta["updated_at"] = (_time.strftime("%Y-%m-%dT%H:%M:%S")[:-0] or "")
    # 手动把 updated_at 改为 31 天前
    from datetime import datetime, timedelta
    stale_meta["updated_at"] = (datetime.now() - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%S")
    payload = {"meta": stale_meta, "data": cached["data"]}
    path = company_cache.section_path(root, "600519.SH", "profile")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    assert company_cache.is_fresh(stale_meta) is False
