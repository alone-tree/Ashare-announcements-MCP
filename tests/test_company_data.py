from pathlib import Path

import pytest

from market_data_mcp import company_cache, company_ifind_service as cs, company_service, data_store
from market_data_mcp.providers import company_ifind as ci
from market_data_mcp.routing import parse_code


def test_annual_year_follows_template_n8_rule():
    # 模板 N8 口径：最新报告期是年报则取该年，否则取其上一年
    assert ci._annual_year("2025-12-31") == 2025
    assert ci._annual_year("2026-06-30") == 2025
    assert ci._annual_year("2026-09-30") == 2025


def test_forecast_years_required_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(cs.company_ifind, "section", lambda *a, **k: pytest.fail("不应请求"))
    result = company_service.get_company_profile(str(tmp_path), "600519.SH", sections=["forecast"])
    assert not result["ok"]
    assert "years" in result["sections"]["forecast"]["error"]


def test_time_scope_cache_and_partial_failure(tmp_path, monkeypatch):
    calls = []
    def section(root, mc, name, **kwargs):
        year = kwargs["years"][0]
        calls.append(year)
        if year == 2028:
            raise RuntimeError("失败")
        return [{"year": year, "营收均值": None}]
    monkeypatch.setattr(cs.company_ifind, "section", section)
    args = dict(sections=["forecast"], years=[2026, 2027, 2028])
    a = company_service.get_company_profile(str(tmp_path), "600519.SH", **args)
    assert a["ok"] and a["status"] == "partial_success"
    b = company_service.get_company_profile(str(tmp_path), "600519.SH", **args)
    assert calls == [2026, 2027, 2028, 2028]  # 已检查空值也复用；失败可重试
    company_service.get_company_profile(str(tmp_path), "600519.SH", sections=["forecast"], years=[2025])
    assert calls[-1] == 2025


def test_holders_default_latest_and_historical_scope(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cs.company_ifind, "latest_report", lambda *a: "2025-09-30")
    def section(root, mc, name, **kwargs):
        calls.append(kwargs["periods"])
        return [{"report_date": kwargs["periods"][0], "名称": "股东"}]
    monkeypatch.setattr(cs.company_ifind, "section", section)
    for _ in range(2):
        r = company_service.get_company_profile(str(tmp_path), "600519.SH", sections=["holders"])
    assert calls == [["2025-09-30"]]
    assert r["sections"]["holders"]["data"][0]["report_date"] == "2025-09-30"
    company_service.get_company_profile(str(tmp_path), "600519.SH", sections=["holders"], periods=["2024-06-30"])
    assert calls[-1] == ["2024-06-30"]


def test_holders_cli_keeps_companies_separate_and_ignores_legacy_cache(tmp_path, monkeypatch):
    from market_data_mcp import cli

    codes = ["688498.SH", "300308.SZ", "920002.BJ"]
    period = "2026-06-30"
    old_files = []
    for code in codes:
        old_file = company_cache.write_section(
            str(tmp_path), code, "holders", market=parse_code(code).market,
            source="sina", data=[{"股东名称": "错误公司股东"}],
        )
        old_file = Path(old_file)
        old_files.append((old_file, old_file.read_bytes()))
    calls = []

    def section(root, mc, name, **kwargs):
        assert name == "holders" and kwargs["periods"] == [period]
        code = f"{mc.code}.{mc.suffix}"
        calls.append(code)
        return [{"report_date": period, "rank": 1, "名称": f"股东-{code}"}]

    monkeypatch.setenv("MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(ci, "section", section)
    monkeypatch.setattr(company_service, "_legacy_get_company_profile",
                        lambda *a, **k: pytest.fail("A股/北交所不得进入旧通道"))
    request = {"tool": "get_company_profile_batch", "codes": codes,
               "sections": ["holders"], "periods": [period]}
    for cached in (False, True):
        response = cli.dispatch(request)
        assert response["ok"] and response["status"] == "success"
        for code, result in zip(codes, response["results"]):
            holders = result["sections"]["holders"]
            assert result["code"] == code and holders["source"] == "ifind"
            assert holders["cached"] is cached
            assert holders["data"] == [{"report_date": period, "rank": 1, "名称": f"股东-{code}"}]
    assert calls == codes
    assert all(path.read_bytes() == original for path, original in old_files)


@pytest.mark.parametrize("code", ["688498.SH", "300308.SZ", "920002.BJ"])
def test_holders_fetch_failure_never_falls_back_to_legacy_cache(tmp_path, monkeypatch, code):
    old_file = Path(company_cache.write_section(
        str(tmp_path), code, "holders", market=parse_code(code).market,
        source="sina", data=[{"股东名称": "错误公司股东"}],
    ))
    original = old_file.read_bytes()

    def unavailable(*args, **kwargs):
        raise RuntimeError("本次iFinD请求失败")

    monkeypatch.setattr(ci, "section", unavailable)
    monkeypatch.setattr(company_service, "_legacy_get_company_profile",
                        lambda *a, **k: pytest.fail("不能回退到旧股东缓存"))
    result = company_service.get_company_profile(
        str(tmp_path), code, sections=["holders"], periods=["2026-06-30"],
    )
    assert not result["ok"] and result["status"] == "failed"
    holders = result["sections"]["holders"]
    assert not holders["ok"] and holders["data"] == [] and holders["checks"] == []
    assert holders["failed"][0]["reason"] == "本次iFinD请求失败"
    assert not data_store.path(str(tmp_path), code, "company_data", "holders").exists()
    assert old_file.read_bytes() == original


def test_dividends_write_failure_keeps_old_value_and_check_time(tmp_path, monkeypatch):
    requests = []

    def section(root, mc, name, **kwargs):
        requests.append(kwargs["years"])
        return [{"year": 2023, "现金分红": len(requests)}]

    monkeypatch.setattr(ci, "section", section)
    args = {"sections": ["dividends"], "years": [2023]}
    before = company_service.get_company_profile(str(tmp_path), "600106.SH", **args)
    target = data_store.path(str(tmp_path), "600106.SH", "company_data", "dividends")
    original = target.read_bytes()
    error = PermissionError("模拟持续拒绝访问")
    error.winerror = 5

    def denied(*args):
        raise error

    monkeypatch.setattr(data_store.os, "replace", denied)
    monkeypatch.setattr(data_store.time, "sleep", lambda _: None)
    after = company_service.get_company_profile(str(tmp_path), "600106.SH", force_refresh=True, **args)
    result = after["sections"]["dividends"]
    assert after["status"] == "partial_success" and result["stale"]
    assert result["data"] == before["sections"]["dividends"]["data"]
    assert result["checks"] == before["sections"]["dividends"]["checks"]
    assert result["failed"][0]["reason"] == str(error)
    assert requests == [[2023], [2023]]  # 重试落盘，不重复请求上游。
    assert target.read_bytes() == original and not list(target.parent.glob("*.tmp"))


def test_sina_fetch_has_no_business_writes(tmp_path, monkeypatch):
    import pandas as pd
    from market_data_mcp.providers import sina
    monkeypatch.setattr(sina.ak, "stock_zh_a_daily", lambda **kw: pd.DataFrame({"date": ["2025-09-30"], "close": [1]}))
    result = sina.fetch_raw(str(tmp_path), parse_code("600519.SH"))
    assert result["ok"] and result["data"]["close"][0]["value"] == 1
    assert not (tmp_path / "cache").exists()
