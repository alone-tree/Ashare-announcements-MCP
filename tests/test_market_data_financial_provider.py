# -*- coding: utf-8 -*-
"""东财三市场财报 provider 规范化测试。"""

import pandas as pd
from types import SimpleNamespace

from market_data_mcp.providers import financial_statements
from market_data_mcp.routing import parse_code


def test_normalize_a_wide_preserves_null_and_drops_yoy():
    df = pd.DataFrame([
        {
            "SECUCODE": "600519.SH",
            "SECURITY_CODE": "600519",
            "SECURITY_NAME_ABBR": "贵州茅台",
            "REPORT_DATE": "2025-12-31 00:00:00",
            "REPORT_TYPE": "年报",
            "NOTICE_DATE": "2026-03-31 00:00:00",
            "UPDATE_DATE": "2026-03-31 00:00:00",
            "CURRENCY": "CNY",
            "OPINION_TYPE": "标准无保留意见",
            "REVENUE": 100.0,
            "REVENUE_YOY": 10.0,
            "EMPTY_ITEM": float("nan"),
            "BASIC_EPS": 2.0,
        }
    ])

    reports = financial_statements.normalize_a_wide(df, "income")

    assert len(reports) == 1
    report = reports[0]
    assert report["report_date"] == "2025-12-31"
    assert report["metadata"]["OPINION_TYPE"] == "标准无保留意见"
    assert [item["item_code"] for item in report["items"]] == ["BASIC_EPS", "EMPTY_ITEM", "REVENUE"]
    assert report["items"][1]["amount"] is None
    assert all(not item["item_code"].endswith("_YOY") for item in report["items"])


def test_normalize_hk_long_binds_summary_metadata():
    df = pd.DataFrame([
        {
            "REPORT_DATE": "2025-06-30 00:00:00",
            "STD_ITEM_CODE": "001",
            "STD_ITEM_NAME": "营业收入",
            "AMOUNT": 88.0,
        },
        {
            "REPORT_DATE": "2025-06-30 00:00:00",
            "STD_ITEM_CODE": "002",
            "STD_ITEM_NAME": "空科目",
            "AMOUNT": float("nan"),
        },
    ])
    summary = [
        {
            "REPORT_DATE": "2025-06-30 00:00:00",
            "START_DATE": "2025-01-01 00:00:00",
            "FISCAL_YEAR": "12-31",
            "CURRENCY": "人民币",
            "ACCOUNT_STANDARD": "国际会计准则",
            "REPORT_TYPE": "中报",
        }
    ]

    reports = financial_statements.normalize_long(df, summary, statement="income")

    assert reports[0]["metadata"]["ACCOUNT_STANDARD"] == "国际会计准则"
    assert reports[0]["metadata"]["START_DATE"] == "2025-01-01"
    assert reports[0]["items"] == [
        {"item_code": "001", "item_name": "营业收入", "amount": 88.0, "source": "eastmoney"},
        {"item_code": "002", "item_name": "空科目", "amount": None, "source": "eastmoney"},
    ]


def test_fetch_a_requests_all_three_statements(tmp_path, monkeypatch):
    calls = []

    def frame(name):
        calls.append(name)
        return pd.DataFrame([{
            "REPORT_DATE": "2025-12-31",
            "REPORT_TYPE": "年报",
            "CURRENCY": "CNY",
            "ITEM": 1.0,
        }])

    fake_ak = SimpleNamespace(
        stock_balance_sheet_by_report_em=lambda symbol: frame("balance"),
        stock_profit_sheet_by_report_em=lambda symbol: frame("income"),
        stock_cash_flow_sheet_by_report_em=lambda symbol: frame("cash_flow"),
    )
    monkeypatch.setattr(financial_statements, "ak", fake_ak)

    result = financial_statements.fetch(str(tmp_path), parse_code("600519.SH"))

    assert result["ok"] is True
    assert set(result["statements"]) == {"balance", "income", "cash_flow"}
    assert calls == ["balance", "income", "cash_flow"]


def test_fetch_hk_uses_one_summary_and_three_tables(tmp_path, monkeypatch):
    calls = []
    summary = {
        "REPORT_DATE": "2025-12-31 00:00:00",
        "START_DATE": "2025-01-01 00:00:00",
        "FISCAL_YEAR": "12-31",
        "CURRENCY": "人民币",
        "ACCOUNT_STANDARD": "国际会计准则",
        "REPORT_TYPE": "年报",
    }

    def fake_request(root, mc, api, params, headers=None):
        calls.append(params["reportName"])
        if params["reportName"] == "RPT_CUSTOM_HKSK_APPFN_CASHFLOW_SUMMARY":
            return {"result": {"data": [{"REPORT_LIST": [summary]}]}}
        return {"result": {"data": [{
            "REPORT_DATE": "2025-12-31 00:00:00",
            "STD_ITEM_CODE": "001",
            "STD_ITEM_NAME": "科目",
            "AMOUNT": 1.0,
        }]}}

    monkeypatch.setattr(financial_statements, "_request_json", fake_request, raising=False)

    result = financial_statements.fetch(str(tmp_path), parse_code("00700.HK"))

    assert result["ok"] is True
    assert calls == [
        "RPT_CUSTOM_HKSK_APPFN_CASHFLOW_SUMMARY",
        "RPT_HKF10_FN_BALANCE_PC",
        "RPT_HKF10_FN_INCOME_PC",
        "RPT_HKF10_FN_CASHFLOW_PC",
    ]
    assert result["statements"]["income"][0]["metadata"]["CURRENCY"] == "人民币"


def test_fetch_us_keeps_cumulative_reports_and_q1(tmp_path, monkeypatch):
    detail_filters = []
    summaries = [
        {"REPORT": "2025/FY", "REPORT_DATE": "2025-09-27", "REPORT_TYPE": "年报", "CURRENCY": "美元"},
        {"REPORT": "2026/Q1", "REPORT_DATE": "2025-12-27", "REPORT_TYPE": "单季报", "CURRENCY": "美元"},
        {"REPORT": "2026/Q2", "REPORT_DATE": "2026-03-28", "REPORT_TYPE": "单季报", "CURRENCY": "美元"},
        {"REPORT": "2026/Q6", "REPORT_DATE": "2026-03-28", "REPORT_TYPE": "累计季报", "CURRENCY": "美元"},
    ]

    def fake_request(root, mc, api, params, headers=None):
        report_name = params["reportName"]
        if report_name == "RPT_USF10_INFO_ORGPROFILE":
            return {"result": {"data": [{"SECUCODE": "AAPL.O"}]}}
        if "STD_ITEM_CODE" not in params["columns"]:
            return {"result": {"data": summaries}}
        detail_filters.append((report_name, params["filter"]))
        return {"result": {"data": [{
            "REPORT_DATE": "2025-09-27",
            "STD_ITEM_CODE": "001",
            "ITEM_NAME": "科目",
            "AMOUNT": 1.0,
        }]}}

    monkeypatch.setattr(financial_statements, "_request_json", fake_request)
    monkeypatch.setattr(
        financial_statements,
        "_fetch_sec_filings",
        lambda root, mc, existing: {"cik": "0000320193", "filings": [], "sec_history_complete": True},
        raising=False,
    )

    result = financial_statements.fetch(str(tmp_path), parse_code("AAPL.US"))

    assert result["ok"] is True
    income_filter = next(value for name, value in detail_filters if name == "RPT_USF10_FN_INCOME")
    assert "2025/FY" in income_filter and "2026/Q1" in income_filter and "2026/Q6" in income_filter
    assert "2026/Q2" not in income_filter
    assert result["metadata"]["cik"] == "0000320193"
    assert result["metadata"]["sec_history_complete"] is True


def test_extract_sec_filings_keeps_financial_forms_and_original_dates():
    main = {
        "filings": {
            "recent": {
                "accessionNumber": ["1", "2"],
                "filingDate": ["2026-02-01", "2026-02-02"],
                "reportDate": ["2025-12-31", "2026-01-31"],
                "acceptanceDateTime": ["2026-02-01T12:00:00.000Z", "2026-02-02T12:00:00.000Z"],
                "form": ["10-K", "8-K"],
                "primaryDocument": ["annual.htm", "event.htm"],
            }
        }
    }
    chunk = {
        "accessionNumber": ["3"],
        "filingDate": ["2025-05-01"],
        "reportDate": ["2025-03-31"],
        "acceptanceDateTime": ["2025-05-01T12:00:00.000Z"],
        "form": ["10-Q/A"],
        "primaryDocument": ["quarter.htm"],
    }

    filings = financial_statements.extract_sec_filings(main, [chunk])

    assert [item["accession_number"] for item in filings] == ["1", "3"]
    assert filings[0]["acceptance_datetime"] == "2026-02-01T12:00:00.000Z"
    assert filings[1]["report_date"] == "2025-03-31"


def test_fetch_sec_filings_reads_history_once(tmp_path, monkeypatch):
    calls = []
    main = {
        "filings": {
            "recent": {
                "accessionNumber": ["1"],
                "filingDate": ["2026-02-01"],
                "reportDate": ["2025-12-31"],
                "acceptanceDateTime": ["2026-02-01T12:00:00.000Z"],
                "form": ["10-K"],
                "primaryDocument": ["annual.htm"],
            },
            "files": [{"name": "old.json"}],
        }
    }
    old = {
        "accessionNumber": ["2"],
        "filingDate": ["2025-05-01"],
        "reportDate": ["2025-03-31"],
        "acceptanceDateTime": ["2025-05-01T12:00:00.000Z"],
        "form": ["10-Q"],
        "primaryDocument": ["quarter.htm"],
    }

    def fake_sec(root, mc, api, url):
        calls.append(api)
        if api == "sec_company_tickers":
            return {"0": {"ticker": "AAPL", "cik_str": 320193}}
        if api == "sec_submissions":
            return main
        return old

    monkeypatch.setattr(financial_statements, "_sec_get_json", fake_sec, raising=False)

    first = financial_statements._fetch_sec_filings(str(tmp_path), parse_code("AAPL.US"), None)
    existing = {"cik": first["cik"], "filings": first["filings"], "sec_history_complete": True}
    second = financial_statements._fetch_sec_filings(str(tmp_path), parse_code("AAPL.US"), existing)

    assert [item["accession_number"] for item in first["filings"]] == ["1", "2"]
    assert first["sec_history_complete"] is True
    assert calls.count("sec_history_chunk") == 1
    assert calls.count("sec_company_tickers") == 1
    assert [item["accession_number"] for item in second["filings"]] == ["1", "2"]
