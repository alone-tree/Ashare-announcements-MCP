# -*- coding: utf-8 -*-
"""东方财富三市场财报请求与规范化。"""

from __future__ import annotations

import math
import os
import time
from datetime import date, datetime
from typing import Any

import akshare as ak
import pandas as pd
import requests

from market_data_mcp import audit
from market_data_mcp.routing import MarketCode


for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_key, None)

SOURCE = "eastmoney"
STATEMENTS = ("balance", "income", "cash_flow")
EASTMONEY_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
SEC_FINANCIAL_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "6-K", "6-K/A"}
SEC_HEADERS = {"User-Agent": "market-data-MCP research contact@example.com"}
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

_A_METADATA_COLUMNS = {
    "SECUCODE",
    "SECURITY_CODE",
    "SECURITY_NAME_ABBR",
    "ORG_CODE",
    "ORG_TYPE",
    "REPORT_DATE",
    "REPORT_TYPE",
    "REPORT_DATE_NAME",
    "SECURITY_TYPE_CODE",
    "NOTICE_DATE",
    "UPDATE_DATE",
    "CURRENCY",
    "OPINION_TYPE",
    "OSOPINION_TYPE",
    "LISTING_STATE",
}
_DERIVED_SUFFIXES = ("_YOY", "_QOQ", "_MOM")


def _clean_value(value: Any) -> Any:
    if value is None or value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _date_text(value: Any) -> str:
    cleaned = _clean_value(value)
    if not cleaned:
        raise ValueError("财报 REPORT_DATE 为空")
    return str(cleaned)[:10]


def normalize_a_wide(df: pd.DataFrame, statement: str) -> list[dict[str, Any]]:
    """A/B/BJ 东财宽表转统一报告结构；保留全部原始科目及 null，丢弃派生同比/环比列。"""
    if statement not in STATEMENTS:
        raise ValueError(f"未知报表：{statement}")
    if df is None or df.empty or "REPORT_DATE" not in df.columns:
        raise ValueError(f"东财 {statement} 返回为空或缺少 REPORT_DATE")

    item_columns = sorted(
        str(column)
        for column in df.columns
        if str(column) not in _A_METADATA_COLUMNS
        and not str(column).upper().endswith(_DERIVED_SUFFIXES)
    )
    reports: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        metadata = {
            column: _clean_value(row[column])
            for column in df.columns
            if str(column) in _A_METADATA_COLUMNS and str(column) != "REPORT_DATE"
        }
        items = [
            {
                "item_code": column,
                "item_name": column,
                "amount": _clean_value(row[column]),
                "source": SOURCE,
            }
            for column in item_columns
        ]
        reports.append(
            {
                "report_date": _date_text(row["REPORT_DATE"]),
                "metadata": metadata,
                "items": items,
            }
        )
    reports.sort(key=lambda report: report["report_date"])
    return reports


def _clean_metadata(record: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in record.items():
        item = _clean_value(value)
        if item is not None and str(key).endswith("DATE"):
            item = str(item)[:10]
        cleaned[str(key)] = item
    return cleaned


def normalize_long(
    df: pd.DataFrame,
    summary_records: list[dict[str, Any]],
    *,
    statement: str,
) -> list[dict[str, Any]]:
    """港美股东财长表按报告日聚合，并绑定 summary 中的报告级元信息。"""
    if statement not in STATEMENTS:
        raise ValueError(f"未知报表：{statement}")
    required = {"REPORT_DATE", "STD_ITEM_CODE", "AMOUNT"}
    if df is None or df.empty or not required <= set(df.columns):
        raise ValueError(f"东财 {statement} 长表为空或缺少 {sorted(required)}")
    name_column = "STD_ITEM_NAME" if "STD_ITEM_NAME" in df.columns else "ITEM_NAME"
    if name_column not in df.columns:
        raise ValueError(f"东财 {statement} 长表缺少科目名称")

    summaries: dict[str, list[dict[str, Any]]] = {}
    for record in summary_records:
        report_date = _date_text(record.get("REPORT_DATE"))
        cleaned = _clean_metadata(record)
        if cleaned not in summaries.setdefault(report_date, []):
            summaries[report_date].append(cleaned)

    reports: list[dict[str, Any]] = []
    work = df.copy()
    work["_REPORT_DATE"] = work["REPORT_DATE"].map(_date_text)
    for report_date, group in work.groupby("_REPORT_DATE", sort=True):
        by_code: dict[str, dict[str, Any]] = {}
        for _, row in group.iterrows():
            item = {
                "item_code": str(row["STD_ITEM_CODE"]),
                "item_name": str(row[name_column]),
                "amount": _clean_value(row["AMOUNT"]),
                "source": SOURCE,
            }
            previous = by_code.get(item["item_code"])
            if previous is not None and previous != item:
                raise ValueError(f"{statement} {report_date} 科目 {item['item_code']} 重复且值不一致")
            by_code[item["item_code"]] = item
        matches = summaries.get(report_date) or []
        metadata = dict(matches[0]) if matches else {}
        if len(matches) > 1:
            metadata["SUMMARY_RECORDS"] = matches
        reports.append(
            {
                "report_date": report_date,
                "metadata": metadata,
                "items": sorted(by_code.values(), key=lambda item: (item["item_code"], item["item_name"])),
            }
        )
    return reports


def _fetch_a(root: str, mc: MarketCode) -> dict[str, list[dict[str, Any]]]:
    symbol = f"{mc.suffix}{mc.code}"
    functions = {
        "balance": ak.stock_balance_sheet_by_report_em,
        "income": ak.stock_profit_sheet_by_report_em,
        "cash_flow": ak.stock_cash_flow_sheet_by_report_em,
    }
    statements: dict[str, list[dict[str, Any]]] = {}
    for statement, function in functions.items():
        started = time.time()
        try:
            frame = function(symbol=symbol)
            reports = normalize_a_wide(frame, statement)
        except Exception as exc:
            audit.log_request(
                root,
                source=SOURCE,
                market=mc.market,
                code=f"{mc.code}.{mc.suffix}",
                api=function.__name__,
                fields=statement,
                ok=False,
                elapsed=time.time() - started,
                error=str(exc),
            )
            raise
        audit.log_request(
            root,
            source=SOURCE,
            market=mc.market,
            code=f"{mc.code}.{mc.suffix}",
            api=function.__name__,
            fields=statement,
            ok=True,
            elapsed=time.time() - started,
        )
        statements[statement] = reports
    return statements


def _request_json(
    root: str,
    mc: MarketCode,
    api: str,
    params: dict[str, str],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.time()
    try:
        response = requests.get(EASTMONEY_URL, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        audit.log_request(
            root,
            source=SOURCE,
            market=mc.market,
            code=f"{mc.code}.{mc.suffix}",
            api=api,
            fields=params.get("reportName"),
            ok=False,
            elapsed=time.time() - started,
            error=str(exc),
        )
        raise
    audit.log_request(
        root,
        source=SOURCE,
        market=mc.market,
        code=f"{mc.code}.{mc.suffix}",
        api=api,
        fields=params.get("reportName"),
        ok=True,
        elapsed=time.time() - started,
    )
    return data


def _fetch_hk(root: str, mc: MarketCode) -> dict[str, list[dict[str, Any]]]:
    summary_params = {
        "reportName": "RPT_CUSTOM_HKSK_APPFN_CASHFLOW_SUMMARY",
        "columns": (
            "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,START_DATE,REPORT_DATE,"
            "FISCAL_YEAR,CURRENCY,ACCOUNT_STANDARD,REPORT_TYPE"
        ),
        "quoteColumns": "",
        "filter": f'(SECUCODE="{mc.code}.HK")',
        "source": "F10",
        "client": "PC",
    }
    summary_data = _request_json(root, mc, "hk_financial_summary", summary_params)
    try:
        summary_records = summary_data["result"]["data"][0]["REPORT_LIST"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("港股财报 summary 返回结构不完整") from exc
    if not summary_records:
        raise ValueError("港股财报 summary 为空")
    report_dates = sorted({_date_text(record.get("REPORT_DATE")) for record in summary_records})
    quoted_dates = "'" + "','".join(report_dates) + "'"

    specs = {
        "balance": (
            "RPT_HKF10_FN_BALANCE_PC",
            "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,ORG_CODE,REPORT_DATE,DATE_TYPE_CODE,"
            "FISCAL_YEAR,STD_ITEM_CODE,STD_ITEM_NAME,AMOUNT,STD_REPORT_DATE",
        ),
        "income": (
            "RPT_HKF10_FN_INCOME_PC",
            "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,ORG_CODE,REPORT_DATE,DATE_TYPE_CODE,"
            "FISCAL_YEAR,START_DATE,STD_ITEM_CODE,STD_ITEM_NAME,AMOUNT",
        ),
        "cash_flow": (
            "RPT_HKF10_FN_CASHFLOW_PC",
            "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,ORG_CODE,REPORT_DATE,DATE_TYPE_CODE,"
            "FISCAL_YEAR,START_DATE,STD_ITEM_CODE,STD_ITEM_NAME,AMOUNT",
        ),
    }
    statements: dict[str, list[dict[str, Any]]] = {}
    for statement, (report_name, columns) in specs.items():
        params = {
            "reportName": report_name,
            "columns": columns,
            "quoteColumns": "",
            "filter": f'(SECUCODE="{mc.code}.HK")(REPORT_DATE in ({quoted_dates}))',
            "pageNumber": "1",
            "pageSize": "",
            "sortTypes": "-1,1",
            "sortColumns": "REPORT_DATE,STD_ITEM_CODE",
            "source": "F10",
            "client": "PC",
        }
        data = _request_json(root, mc, f"hk_{statement}", params)
        try:
            frame = pd.DataFrame(data["result"]["data"])
        except (KeyError, TypeError) as exc:
            raise ValueError(f"港股 {statement} 返回结构不完整") from exc
        statements[statement] = normalize_long(frame, summary_records, statement=statement)
    return statements


def _unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        cleaned = _clean_metadata(record)
        key = str(sorted(cleaned.items()))
        unique[key] = cleaned
    return list(unique.values())


def extract_sec_filings(
    main: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """从 SEC submissions 主文件和历史分片提取财报相关提交元信息。"""
    sources = [main.get("filings", {}).get("recent", {}) or main]
    sources.extend(chunk.get("filings", {}).get("recent", {}) or chunk for chunk in chunks)
    filings: dict[str, dict[str, Any]] = {}
    fields = {
        "filing_date": "filingDate",
        "report_date": "reportDate",
        "acceptance_datetime": "acceptanceDateTime",
        "form": "form",
        "primary_document": "primaryDocument",
    }
    for source in sources:
        forms = source.get("form") or []
        accessions = source.get("accessionNumber") or []
        for index, form in enumerate(forms):
            if str(form) not in SEC_FINANCIAL_FORMS or index >= len(accessions):
                continue
            item: dict[str, Any] = {"accession_number": str(accessions[index])}
            for target, upstream in fields.items():
                values = source.get(upstream) or []
                item[target] = str(values[index]) if index < len(values) and values[index] is not None else ""
            filings[item["accession_number"]] = item
    return sorted(
        filings.values(),
        key=lambda item: (item["filing_date"], item["accession_number"]),
        reverse=True,
    )


def _sec_get_json(root: str, mc: MarketCode, api: str, url: str) -> dict[str, Any]:
    started = time.time()
    try:
        response = requests.get(url, headers=SEC_HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        audit.log_request(
            root,
            source="sec",
            market=mc.market,
            code=f"{mc.code}.{mc.suffix}",
            api=api,
            ok=False,
            elapsed=time.time() - started,
            error=str(exc),
        )
        raise
    audit.log_request(
        root,
        source="sec",
        market=mc.market,
        code=f"{mc.code}.{mc.suffix}",
        api=api,
        ok=True,
        elapsed=time.time() - started,
    )
    return data


def _fetch_sec_filings(
    root: str,
    mc: MarketCode,
    existing_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    existing = existing_metadata or {}
    cik = existing.get("cik")
    if not cik:
        tickers = _sec_get_json(root, mc, "sec_company_tickers", SEC_TICKERS_URL)
        match = next(
            (record for record in tickers.values() if str(record.get("ticker") or "").upper() == mc.code),
            None,
        )
        if match is None:
            raise ValueError(f"SEC 未找到该美股代码：{mc.code}")
        cik = str(match["cik_str"]).zfill(10)
    else:
        cik = str(cik).zfill(10)

    main = _sec_get_json(root, mc, "sec_submissions", SEC_SUBMISSIONS_URL.format(cik=cik))
    chunks: list[dict[str, Any]] = []
    history_complete = bool(existing.get("sec_history_complete"))
    if not history_complete:
        for file_info in main.get("filings", {}).get("files") or []:
            name = file_info.get("name")
            if name:
                chunks.append(
                    _sec_get_json(
                        root,
                        mc,
                        "sec_history_chunk",
                        f"https://data.sec.gov/submissions/{name}",
                    )
                )
        history_complete = True

    merged = {item["accession_number"]: item for item in existing.get("filings") or []}
    for item in extract_sec_filings(main, chunks):
        merged[item["accession_number"]] = item
    filings = sorted(
        merged.values(),
        key=lambda item: (item["filing_date"], item["accession_number"]),
        reverse=True,
    )
    return {"cik": cik, "filings": filings, "sec_history_complete": history_complete}


def _fetch_us(root: str, mc: MarketCode) -> dict[str, list[dict[str, Any]]]:
    profile_params = {
        "reportName": "RPT_USF10_INFO_ORGPROFILE",
        "columns": (
            "SECUCODE,SECURITY_CODE,ORG_CODE,SECURITY_INNER_CODE,ORG_NAME,ORG_EN_ABBR,"
            "BELONG_INDUSTRY,FOUND_DATE"
        ),
        "quoteColumns": "",
        "filter": f'(SECURITY_CODE="{mc.code}")',
        "pageNumber": "1",
        "pageSize": "200",
        "source": "SECURITIES",
        "client": "PC",
    }
    profile = _request_json(root, mc, "us_market_lookup", profile_params)
    try:
        secucode = str(profile["result"]["data"][0]["SECUCODE"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("美股市场代码查询返回结构不完整") from exc

    specs = {
        "balance": "RPT_USF10_FN_BALANCE",
        "income": "RPT_USF10_FN_INCOME",
        "cash_flow": "RPT_USSK_FN_CASHFLOW",
    }
    statements: dict[str, list[dict[str, Any]]] = {}
    for statement, report_name in specs.items():
        summary_params = {
            "reportName": report_name,
            "columns": (
                "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORT,REPORT_DATE,FISCAL_YEAR,"
                "CURRENCY,ACCOUNT_STANDARD,REPORT_TYPE,DATE_TYPE_CODE"
            ),
            "quoteColumns": "",
            "filter": f'(SECUCODE="{secucode}")',
            "pageNumber": "",
            "pageSize": "",
            "sortTypes": "-1",
            "sortColumns": "REPORT_DATE",
            "source": "SECURITIES",
            "client": "PC",
        }
        summary_data = _request_json(root, mc, f"us_{statement}_summary", summary_params)
        try:
            all_summary = _unique_records(summary_data["result"]["data"])
        except (KeyError, TypeError) as exc:
            raise ValueError(f"美股 {statement} summary 返回结构不完整") from exc
        if statement == "balance":
            selected = all_summary
        else:
            selected = [
                record
                for record in all_summary
                if record.get("REPORT_TYPE") in ("年报", "累计季报")
                or str(record.get("REPORT") or "").endswith("/Q1")
            ]
        report_ids = sorted({str(record.get("REPORT")) for record in selected if record.get("REPORT")})
        if not report_ids:
            raise ValueError(f"美股 {statement} 无累计报告期")
        quoted_reports = ','.join(f'"{value}"' for value in report_ids)
        detail_params = {
            "reportName": report_name,
            "columns": (
                "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,REPORT_TYPE,REPORT,"
                "STD_ITEM_CODE,AMOUNT,ITEM_NAME"
            ),
            "quoteColumns": "",
            "filter": f'(SECUCODE="{secucode}")(REPORT in ({quoted_reports}))',
            "pageNumber": "",
            "pageSize": "",
            "sortTypes": "1,-1",
            "sortColumns": "STD_ITEM_CODE,REPORT_DATE",
            "source": "SECURITIES",
            "client": "PC",
        }
        detail_data = _request_json(root, mc, f"us_{statement}", detail_params)
        try:
            frame = pd.DataFrame(detail_data["result"]["data"])
        except (KeyError, TypeError) as exc:
            raise ValueError(f"美股 {statement} 返回结构不完整") from exc
        statements[statement] = normalize_long(frame, selected, statement=statement)
    return statements


def fetch(
    root: str,
    mc: MarketCode,
    existing_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """获取同一公司的三表全历史；任何组成部分失败都返回 ok=false，不写缓存。"""
    try:
        if mc.market in ("A", "BJ"):
            statements = _fetch_a(root, mc)
            metadata = {
                "code": f"{mc.code}.{mc.suffix}",
                "market": mc.market,
                "sources": {"statements": SOURCE},
                "filings": [],
            }
        elif mc.market == "HK":
            statements = _fetch_hk(root, mc)
            metadata = {
                "code": f"{mc.code}.{mc.suffix}",
                "market": mc.market,
                "sources": {"statements": SOURCE},
                "filings": [],
            }
        elif mc.market == "US":
            statements = _fetch_us(root, mc)
            sec = _fetch_sec_filings(root, mc, existing_metadata)
            metadata = {
                "code": f"{mc.code}.{mc.suffix}",
                "market": mc.market,
                "sources": {"statements": SOURCE, "filings": "sec"},
                "cik": sec["cik"],
                "filings": sec["filings"],
                "sec_history_complete": sec["sec_history_complete"],
            }
        else:
            raise ValueError(f"财报 provider 尚未实现市场：{mc.market}")
    except Exception as exc:
        return {
            "ok": False,
            "source": SOURCE,
            "statements": None,
            "metadata": None,
            "error": f"财报三表刷新失败：{exc}",
            "notes": None,
        }
    return {
        "ok": True,
        "source": SOURCE,
        "statements": statements,
        "metadata": metadata,
        "error": None,
        "notes": None,
    }
