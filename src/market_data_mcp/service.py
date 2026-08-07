# -*- coding: utf-8 -*-
"""market_data_mcp 数据服务层：三市场行情/财报/指标/公司信息。

复用 providers/（自包含，从 A股数据基础设施 AKShare 脚本复制）：
- a_share.py / hk.py / us.py：各市场行情与财报接口（含东财→新浪回退）
- _common.py：市场识别 / 代码规范化

所有接口统一：自动识别市场（6位数字=A股、5位数字=港股、字母=美股），
可加 A:/HK:/US: 前缀强制市场。
"""

from __future__ import annotations

import math
import os
from typing import Any

import akshare as ak
import pandas as pd

from market_data_mcp.providers import _common, a_share, hk, us

MARKET_MODULES = {"a": a_share, "hk": hk, "us": us}
MARKET_NAMES = {"a": "A股", "hk": "港股", "us": "美股"}

# 清理代理环境变量（Hermes 终端注入的代理对数据接口反而致 ProxyError/SSLError）
def _clear_proxy_env() -> None:
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)


_clear_proxy_env()

# 报表范围 → 各市场数据获取函数
STATEMENT_FUNCS: dict[str, dict[str, Any]] = {
    "income": {
        "label": "利润表",
        "a": lambda code, em: ak.stock_profit_sheet_by_report_em(symbol=em),
        "hk": lambda code, em: ak.stock_financial_hk_report_em(stock=code, symbol="利润表", indicator="年度"),
        "us": lambda code, em: ak.stock_financial_us_report_em(stock=code, symbol="综合损益表", indicator="年报"),
    },
    "balance": {
        "label": "资产负债表",
        "a": lambda code, em: ak.stock_balance_sheet_by_report_em(symbol=em),
        "hk": lambda code, em: ak.stock_financial_hk_report_em(stock=code, symbol="资产负债表", indicator="年度"),
        "us": lambda code, em: ak.stock_financial_us_report_em(stock=code, symbol="资产负债表", indicator="年报"),
    },
    "cash_flow": {
        "label": "现金流量表",
        "a": lambda code, em: ak.stock_cash_flow_sheet_by_report_em(symbol=em),
        "hk": lambda code, em: ak.stock_financial_hk_report_em(stock=code, symbol="现金流量表", indicator="年度"),
        "us": lambda code, em: ak.stock_financial_us_report_em(stock=code, symbol="现金流量表", indicator="年报"),
    },
}

VALID_STATEMENTS = ("income", "balance", "cash_flow")
VALID_ADJUSTS = ("qfq", "hfq", "")
VALID_PERIODS = ("daily", "weekly", "monthly")


def _resolve_market(code: str) -> tuple[str, str]:
    """识别市场并返回规范化代码。返回 (market, code)。"""
    market = _common.detect_market(code)
    code = _common.strip_market_prefix(code)
    return market, code


def _market_name(market: str) -> str:
    return MARKET_NAMES.get(market, market)


def _em_symbol(market: str, code: str) -> str:
    if market == "a":
        return _common.em_symbol_a(code)
    if market == "hk":
        return _common.em_symbol_hk(code)
    return code


def _df_to_records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    """DataFrame → 记录列表（MCP JSON 友好）。NaN/NaT 转 None。"""
    if df is None or len(df) == 0:
        return []
    records = df.to_dict(orient="records")
    cleaned = []
    for record in records:
        item: dict[str, Any] = {}
        for key, value in record.items():
            if value is None:
                item[key] = None
            elif isinstance(value, float) and math.isnan(value):
                item[key] = None
            elif value is pd.NaT:
                item[key] = None
            else:
                item[key] = value
        cleaned.append(item)
    if limit:
        cleaned = cleaned[:limit]
    return cleaned


def get_quote(
    code: str,
    start: str,
    end: str,
    adjust: str = "qfq",
    period: str = "daily",
) -> dict[str, Any]:
    """获取日线/周线/月线行情（前复权/后复权/不复权），含成交量/额/流通股本。

    返回 {ok, market, code, name, start, end, adjust, period, source, notes, rows: [...]}
    notes 说明实际返回口径（如美股新浪回退时 hfq 降级为 qfq、周/月线由日线聚合）。
    """
    if adjust not in VALID_ADJUSTS:
        raise ValueError(f"adjust 必须是 {VALID_ADJUSTS} 之一（qfq=前复权 hfq=后复权 空=不复权）")
    if period not in VALID_PERIODS:
        raise ValueError(f"period 必须是 {VALID_PERIODS} 之一（daily/weekly/monthly）")
    market, c = _resolve_market(code)
    mod = MARKET_MODULES[market]
    df = mod.fetch_daily(c, start, end, adjust=adjust, period=period)
    if df is None or len(df) == 0:
        raise ValueError(f"未获取到 {c} 的行情数据（{start}~{end}）")
    notes: list[str] = []
    source = str(df.iloc[0].get("source", ""))
    if source == "sina" and period != "daily":
        notes.append(f"新浪接口仅提供日线，{period} 由日线本地聚合")
    if source == "sina" and market == "us" and adjust == "hfq":
        notes.append("新浪美股接口不支持后复权，已返回前复权数据")
    return {
        "ok": True,
        "market": _market_name(market),
        "code": c,
        "start": start,
        "end": end,
        "adjust": adjust or "none",
        "period": period,
        "source": source,
        "notes": notes,
        "rows": _df_to_records(df),
    }


def get_financial_statements(
    code: str,
    periods: list[str] | None = None,
    statements: list[str] | None = None,
) -> dict[str, Any]:
    """获取原始财务报表（三表，按报告期）。

    periods: 报告期年份列表（如 ["2025", "2024"]）；None=全部报告期。
    statements: 报表范围 ["income","balance","cash_flow"]；None=全部三表。
    返回 {ok, market, code, statements: {income: {label, rows}, ...}}
    """
    if statements is None:
        statements = list(VALID_STATEMENTS)
    invalid = [s for s in statements if s not in VALID_STATEMENTS]
    if invalid:
        raise ValueError(f"statements 只支持 {list(VALID_STATEMENTS)}（income/balance/cash_flow），收到 {invalid}")

    market, c = _resolve_market(code)
    em = _em_symbol(market, c)
    result: dict[str, Any] = {"ok": True, "market": _market_name(market), "code": c, "statements": {}}

    for stmt in statements:
        func = STATEMENT_FUNCS[stmt]["a" if market == "a" else ("hk" if market == "hk" else "us")]
        try:
            df = func(c, em)
            if df is None or len(df) == 0:
                result["statements"][stmt] = {"label": STATEMENT_FUNCS[stmt]["label"], "rows": [], "note": "无数据"}
                continue
            if periods:
                df = filter_by_period(df, periods)
            result["statements"][stmt] = {
                "label": STATEMENT_FUNCS[stmt]["label"],
                "rows": _df_to_records(df),
            }
        except Exception as e:
            result["statements"][stmt] = {
                "label": STATEMENT_FUNCS[stmt]["label"],
                "rows": [],
                "note": f"获取失败：{type(e).__name__}: {str(e)[:120]}",
            }
    return result


def _period_column(df: pd.DataFrame) -> str | None:
    """找到报告期列（REPORT_DATE / REPORT_DATE_NAME 等）。"""
    for col in ("REPORT_DATE", "REPORT_DATE_NAME", "报告期", "日期"):
        if col in df.columns:
            return col
    return None


def filter_by_period(df: pd.DataFrame, periods: list[str]) -> pd.DataFrame:
    """按报告期年份过滤（匹配 '2025' 前缀的任意季度报告期）。"""
    col = _period_column(df)
    if col is None:
        return df
    dates = df[col].astype(str)
    mask = dates.str.startswith(tuple(periods))
    return df[mask]


def get_financial_ratios(code: str, periods: list[str] | None = None) -> dict[str, Any]:
    """获取财务衍生指标（原始，来自东财指标接口）。

    A股：按报告期多期；港股：仅最新；美股：年报多期。
    返回 {ok, market, code, rows: [...]}
    """
    market, c = _resolve_market(code)
    try:
        if market == "a":
            sec_code = f"{c}.{'SH' if c.startswith('6') else 'SZ'}"
            df = ak.stock_financial_analysis_indicator_em(symbol=sec_code, indicator="按报告期")
        elif market == "hk":
            df = ak.stock_hk_financial_indicator_em(symbol=c)
        else:
            df = ak.stock_financial_us_analysis_indicator_em(symbol=c, indicator="年报")
    except Exception as e:
        raise ValueError(f"{_market_name(market)} 财务指标获取失败：{type(e).__name__}: {str(e)[:120]}")

    if df is None or len(df) == 0:
        return {"ok": True, "market": _market_name(market), "code": c, "rows": []}
    if periods:
        df = filter_by_period(df, periods)
    return {"ok": True, "market": _market_name(market), "code": c, "rows": _df_to_records(df)}


def get_company_profile(
    code: str,
    sections: list[str] | None = None,
) -> dict[str, Any]:
    """获取公司基本信息：profile 概况 / dividends 分红 / forecast 盈利预测。

    sections: ["profile","dividends","forecast"]；None=全部。
    港股/美股缺失的类别返回 note 说明（需从公告获取）。
    返回 {ok, market, code, profile: {...}, dividends: [...], forecast: [...]}
    """
    valid = ("profile", "dividends", "forecast")
    if sections is None:
        sections = list(valid)
    invalid = [s for s in sections if s not in valid]
    if invalid:
        raise ValueError(f"sections 只支持 {list(valid)}（profile/dividends/forecast），收到 {invalid}")

    market, c = _resolve_market(code)
    em = _em_symbol(market, c)
    result: dict[str, Any] = {"ok": True, "market": _market_name(market), "code": c}

    if "profile" in sections:
        result["profile"] = _fetch_profile(market, c, em)
    if "dividends" in sections:
        result["dividends"] = _fetch_dividends(market, c)
    if "forecast" in sections:
        result["forecast"] = _fetch_forecast(market, c)
    return result


def _fetch_profile(market: str, code: str, em: str) -> dict[str, Any]:
    try:
        if market == "a":
            df = ak.stock_profile_cninfo(symbol=code)
        elif market == "hk":
            df = ak.stock_hk_company_profile_em(symbol=code)
        else:
            return {"note": "美股无公司概况接口，可从 SEC EDGAR 公告获取"}
        rows = _df_to_records(df, limit=1)
        return {"rows": rows} if rows else {"note": "无数据"}
    except Exception as e:
        return {"note": f"获取失败：{type(e).__name__}: {str(e)[:120]}"}


def _fetch_dividends(market: str, code: str) -> dict[str, Any]:
    try:
        if market == "a":
            df = ak.stock_fhps_detail_em(symbol=code)
        elif market == "hk":
            df = ak.stock_hk_dividend_payout_em(symbol=code)
        else:
            return {"note": "美股无分红历史接口，可从 SEC EDGAR 公告获取"}
        rows = _df_to_records(df)
        return {"rows": rows} if rows else {"note": "无数据"}
    except Exception as e:
        return {"note": f"获取失败：{type(e).__name__}: {str(e)[:120]}"}


def _fetch_forecast(market: str, code: str) -> dict[str, Any]:
    try:
        if market == "a":
            df = ak.stock_profit_forecast_em(symbol="")
            if df is not None and len(df) > 0 and "代码" in df.columns:
                df = df[df["代码"] == code]
        elif market == "hk":
            df = ak.stock_hk_profit_forecast_et(symbol=code)
        else:
            return {"note": "美股无盈利预测接口，可从券商研报获取"}
        rows = _df_to_records(df)
        return {"rows": rows} if rows else {"note": "无数据"}
    except Exception as e:
        return {"note": f"获取失败：{type(e).__name__}: {str(e)[:120]}"}
