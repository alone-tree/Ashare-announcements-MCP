"""公司信息简化契约：条件不可被静默忽略，双入口保留完整数据。"""
import asyncio
from datetime import date

import pytest

from market_data_mcp import cli, company_ifind_service, company_service
from market_data_mcp.server import _render_company_markdown, create_server


@pytest.mark.parametrize("kind,extra,key", [
    ("dividends", {"years": [2020]}, "years"),
    ("profile", {"dividend_years": [2020]}, "dividend_years"),
    ("dividends", {"dividend_years": []}, "dividend_years"),
    ("dividends", {"dividend_years": [True]}, "dividend_years"),
    ("forecast", {"forecast_years": ["2027"]}, "forecast_years"),
    ("holders", {"shareholder_report_dates": "2024-12-31"}, "shareholder_report_dates"),
    ("holders", {"shareholder_report_dates": ["2024-02-30"]}, "shareholder_report_dates"),
    ("holders", {"shareholder_report_dates": ["9999-12-31"]}, "shareholder_report_dates"),
    ("forecast", {"forecast_as_of_date": 20240601}, "forecast_as_of_date"),
    ("forecast", {"forecast_as_of_date": "2024-6-1"}, "forecast_as_of_date"),
    ("forecast", {"forecast_as_of_date": None}, "forecast_as_of_date"),
])
def test_invalid_extra_never_fetches(tmp_path, monkeypatch, kind, extra, key):
    monkeypatch.setattr(company_ifind_service, "get_section", lambda *a: pytest.fail("条件无效不得取数"))
    result = company_service.get_company_profile(str(tmp_path), "600519.SH", kind, extra_parameters=extra)
    assert not result["ok"] and key in result["error"]
    if kind != "profile":
        assert result["extra_parameter_help"]


@pytest.mark.parametrize("extra", [[], "dividend_years=2020", False])
def test_extra_is_object_not_command(tmp_path, extra):
    result = company_service.get_company_profile(str(tmp_path), "600519.SH", "dividends", extra_parameters=extra)
    assert not result["ok"] and "JSON对象" in result["error"]


@pytest.mark.parametrize("code", ["00700.HK", "AAPL.US"])
def test_unsupported_market_filters_are_not_ignored(tmp_path, monkeypatch, code):
    monkeypatch.setattr(company_service, "_legacy_get_company_profile", lambda *a: pytest.fail("不得忽略条件"))
    result = company_service.get_company_profile(str(tmp_path), code, "forecast", extra_parameters={"forecast_years": [2027]})
    assert not result["ok"] and "不支持" in result["error"]
    assert "extra_parameter_help" not in result


def test_forecast_dates_and_years_are_independent_cache_scopes(tmp_path, monkeypatch):
    calls = []
    def section(root, mc, name, **kwargs):
        calls.append((kwargs["years"], kwargs["as_of_date"]))
        return [{"year": kwargs["years"][0], "as_of_date": kwargs["as_of_date"], "营收均值": 0}]
    monkeypatch.setattr(company_ifind_service.company_ifind, "section", section)
    params = {"forecast_years": [2027], "forecast_as_of_date": "2024-06-01"}
    a = company_service.get_company_profile(str(tmp_path), "600519.SH", "forecast", extra_parameters=params)
    b = company_service.get_company_profile(str(tmp_path), "600519.SH", "forecast", extra_parameters=params)
    c = company_service.get_company_profile(str(tmp_path), "600519.SH", "forecast", extra_parameters={**params, "forecast_as_of_date": "2024-06-02"})
    d = company_service.get_company_profile(str(tmp_path), "600519.SH", "forecast", True, params)
    assert calls == [([2027], "2024-06-01"), ([2027], "2024-06-02"), ([2027], "2024-06-01")]
    assert a["data"] == b["data"] == d["data"] and b["cached"]
    assert c["data"][0]["as_of_date"] == "2024-06-02" and a["query"] == params


def test_latest_forecast_resolves_date_before_cache_lookup(tmp_path, monkeypatch):
    calls = []
    class Clock(date):
        current = date(2026, 11, 2)
        @classmethod
        def today(cls):
            return cls.current
    monkeypatch.setattr(company_service, "date", Clock)
    def section(*args, **kwargs):
        calls.append(kwargs["as_of_date"])
        return [{"year": kwargs["years"][0], "as_of_date": kwargs["as_of_date"]}]
    monkeypatch.setattr(company_ifind_service.company_ifind, "section", section)
    company_service.get_company_profile(str(tmp_path), "600519.SH", "forecast")
    Clock.current = date(2026, 11, 3)
    result = company_service.get_company_profile(str(tmp_path), "600519.SH", "forecast")
    assert calls == ["2026-11-02"] * 3 + ["2026-11-03"] * 3
    assert result["query"] == {"forecast_years": [2027, 2028, 2029], "forecast_as_of_date": "2026-11-03"}


def test_dividend_defaults_and_type_specific_help(tmp_path, monkeypatch):
    def section(*args, **kwargs):
        return [{"year": kwargs["years"][0], "现金分红": 0, "回购": None}]
    monkeypatch.setattr(company_ifind_service.company_ifind, "section", section)
    result = company_service.get_company_profile(str(tmp_path), "900901.SH", "dividends")
    assert result["query"]["dividend_years"] == list(range(date.today().year - 4, date.today().year + 1))
    assert len(result["data"]) == 5 and result["data"][0]["现金分红"] == 0
    assert set(result["extra_parameter_help"]) == {"dividend_years"}
    example = result["extra_parameter_help"]["dividend_years"]["example"]
    queried = company_service.get_company_profile(str(tmp_path), **example)
    assert queried["query"]["dividend_years"] == [2020, 2021]


def test_mcp_and_cli_use_same_request_and_preserve_all_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_DATA_ROOT", str(tmp_path))
    value = {"发行价格": 0, "发行费用": None, "发行后市净率": None, "上市日期": "20040716", "机构": "甲|乙\n丙", "其他": {"变量": [1, 2]}}
    monkeypatch.setattr(company_ifind_service.company_ifind, "section", lambda *a, **k: value)
    tool = next(t for t in create_server()._tool_manager.list_tools() if t.name == "get_company_profile")
    assert set(tool.parameters["properties"]) == {"code", "information_type", "force_refresh", "extra_parameters"}
    assert set(tool.parameters["required"]) == {"code", "information_type"}
    mcp = asyncio.run(tool.run({"code": "600519.SH", "information_type": "ipo"}))
    raw = cli.dispatch({"tool": "get_company_profile_batch", "codes": ["600519.SH"], "information_type": "ipo"})["results"][0]
    assert raw["data"] == value and "sections" not in raw
    assert all(key in mcp["markdown"] for key in value)
    assert "&#124;" in mcp["markdown"] and "<br>" in mcp["markdown"]
    assert mcp["source"] == raw["source"] == "ifind" and mcp["checks"] == raw["checks"]
    assert "data" not in mcp and "extra_parameter_help" not in mcp
    with pytest.raises(Exception, match="Extra inputs"):
        asyncio.run(tool.run({"code": "600519.SH", "information_type": "ipo", "years": [2020]}))
    with pytest.raises(ValueError, match="未知参数"):
        cli.dispatch({"tool": "get_company_profile_batch", "codes": ["600519.SH"], "sections": ["ipo"]})
    with pytest.raises(Exception):
        asyncio.run(tool.run({"code": "600519.SH", "information_type": "ipo", "force_refresh": "false"}))
    wrong_bool = cli.dispatch({"tool": "get_company_profile_batch", "codes": ["600519.SH"], "information_type": "ipo", "force_refresh": "false"})
    assert not wrong_bool["ok"] and "布尔" in wrong_bool["results"][0]["error"]


def test_table_keeps_union_of_fields_and_nested_values():
    result = _render_company_markdown({"information_type": "forecast", "data": [{"year": 2027, "均值": 0}, {"year": 2028, "原始字段": {"value": None}}]})
    assert "预测业绩所属年度" in result["markdown"] and "原始字段" in result["markdown"]
    assert '"value": null' in result["markdown"] and "| 2027 | 0 |" in result["markdown"]


def test_latest_holder_probe_failure_marks_old_period_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(company_ifind_service.company_ifind, "latest_report", lambda *a: "2025-12-31")
    monkeypatch.setattr(company_ifind_service.company_ifind, "section", lambda *a, **k: [{"report_date": "2025-12-31", "rank": 1, "名称": "甲"}])
    company_service.get_company_profile(str(tmp_path), "600519.SH", "holders")
    def failed(*args):
        raise RuntimeError("最新报告期查询失败")
    monkeypatch.setattr(company_ifind_service.company_ifind, "latest_report", failed)
    result = company_service.get_company_profile(str(tmp_path), "600519.SH", "holders", True)
    assert result["ok"] and result["status"] == "partial_success" and result["stale"]
    assert result["query"]["shareholder_report_dates"] == ["2025-12-31"]
    assert result["failed"][0]["reason"] == "最新报告期查询失败"
