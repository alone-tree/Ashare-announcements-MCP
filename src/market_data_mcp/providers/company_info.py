# -*- coding: utf-8 -*-
"""公司信息请求模块（源 × 市场 × section）。

架构 docs/market-data架构设计.md §5（2026-08-09 定稿）：
- **无失败回退**：主源失败即结构化报错（可重试），不做第二来源顶替
- **补充源只做字段补全**：主源成功但缺某字段时，从补充源取该字段，不参与失败回退
- 每次上游请求写审计日志 logs/requests.jsonl

模块契约（架构 §1.8）：**结构化返回，不抛异常**——
`{ok, source, section, data, error, notes}`，data 为规范化数据（dict 或 list[dict]）。

数据源（探测依据 字段与数据源支持情况.md §5，2026-08-09 全量重探测）：
- 概况：A/BJ=巨潮 stock_profile_cninfo（26 字段）；港股=东财 company_profile（17 字段）
  + security_profile（14 字段）两接口合并并集；美股无结构化 → 公告
- IPO：A/BJ=巨潮 stock_ipo_summary_cninfo（15 字段）+ 新浪 stock_ipo_info（17 项 key-value）
- 分红：A/BJ=东财 stock_fhps_detail_em（18期19字段最全）+ 同花顺（股利支付率/税前分红率/不分配记录）
  + 巨潮（年度/中期类型）；港股=东财 stock_hk_dividend_payout_em
- 盈利预测：A/BJ=东财 stock_profit_forecast_em（一致预期）+ 同花顺（min/max/行业均值）；
  港股=经济通 stock_hk_profit_forecast_et（分券商明细，**必须直连**，走代理报 SSLError）
- 股东：A/BJ=新浪 stock_main_stock_holder（历史多期序列）
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Callable

import akshare as ak
import pandas as pd

from market_data_mcp import audit
from market_data_mcp.routing import MarketCode

# 全部为国内/免代理源：清代理直连（Hermes 注入的代理对东财/新浪/巨潮/经济通致 ProxyError/SSLError）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)


def _clean_value(v: Any) -> Any:
    """NaN 清理必须显式逐值判断（df.where(pd.notnull()) 对 float NaN 不生效）；
    numpy 标量（int64/float64 等）必须转原生类型（json 序列化需要）。"""
    if v is None or v is pd.NaT:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        return _clean_value(v.item())
    if hasattr(v, "strftime"):
        try:
            return v.strftime("%Y-%m-%d")
        except ValueError:
            return str(v)
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _row_to_dict(row: pd.Series) -> dict[str, Any]:
    return {str(col): _clean_value(row[col]) for col in row.index}


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    return [_row_to_dict(row) for _, row in df.iterrows()]


def _call(
    root: str,
    mc: MarketCode,
    api: str,
    source: str,
    section: str,
    fn: Callable[[], Any],
    shape: str = "records",
) -> dict[str, Any]:
    """统一执行上游请求 + 审计日志 + 异常转结构化返回。

    shape: records=多行 list[dict] / row=单行 dict / kv=两列 key-value → dict
    """
    code = f"{mc.code}.{mc.suffix}"
    started = time.time()
    try:
        result = fn()
        if shape == "row":
            if result is None or (hasattr(result, "empty") and result.empty):
                data: Any = {}
            elif hasattr(result, "iloc"):
                data = _row_to_dict(result.iloc[0])
            else:
                data = dict(result or {})
        elif shape == "kv":
            rows = _df_to_records(result) if hasattr(result, "columns") else (result or [])
            data = {str(r.get("item") or r.get("项目") or r.get("key")): r.get("value") or r.get("数值")
                    for r in rows if r}
        else:
            data = _df_to_records(result) if hasattr(result, "columns") else (result or [])
    except Exception as exc:  # noqa: BLE001
        audit.log_request(
            root, source=source, market=mc.market, code=code, api=api,
            fields=section, ok=False, elapsed=time.time() - started, error=str(exc),
        )
        return {"ok": False, "source": source, "section": section,
                "data": None, "error": str(exc), "notes": None}
    audit.log_request(
        root, source=source, market=mc.market, code=code, api=api,
        fields=section, ok=True, elapsed=time.time() - started,
    )
    return {"ok": True, "source": source, "section": section,
            "data": data, "error": None, "notes": None}


# ---------------------------------------------------------------- profile 概况

def fetch_cninfo_profile(root: str, mc: MarketCode) -> dict[str, Any]:
    """A/BJ 股公司概况（主源）：巨潮 26 字段，1 行。"""
    return _call(
        root, mc, "stock_profile_cninfo", "cninfo", "profile",
        lambda: ak.stock_profile_cninfo(symbol=mc.code), shape="row",
    )


def fetch_hk_company_profile(root: str, mc: MarketCode) -> dict[str, Any]:
    """港股公司概况（主源①）：东财 17 字段（公司级：注册地/董事长/员工/核数师/年结日等）。"""
    return _call(
        root, mc, "stock_hk_company_profile_em", "eastmoney", "profile",
        lambda: ak.stock_hk_company_profile_em(symbol=mc.code), shape="row",
    )


def fetch_hk_security_profile(root: str, mc: MarketCode) -> dict[str, Any]:
    """港股证券资料（主源②，与①字段互补合并）：东财 14 字段（ISIN/每手股数/沪深港通标识等）。"""
    return _call(
        root, mc, "stock_hk_security_profile_em", "eastmoney", "profile",
        lambda: ak.stock_hk_security_profile_em(symbol=mc.code), shape="row",
    )


# ---------------------------------------------------------------- ipo

def fetch_cninfo_ipo(root: str, mc: MarketCode) -> dict[str, Any]:
    """A/BJ 股 IPO 资料（主源）：巨潮 15 字段宽表，1 行。"""
    return _call(
        root, mc, "stock_ipo_summary_cninfo", "cninfo", "ipo",
        lambda: ak.stock_ipo_summary_cninfo(symbol=mc.code), shape="row",
    )


def fetch_sina_ipo(root: str, mc: MarketCode) -> dict[str, Any]:
    """A/BJ 股 IPO 资料（补充源）：新浪 17 项 key-value（发行方式/市盈率/首发前后股本/募资/承销费用等）。"""
    return _call(
        root, mc, "stock_ipo_info", "sina", "ipo",
        lambda: ak.stock_ipo_info(stock=mc.code), shape="kv",
    )


# ---------------------------------------------------------------- dividends 分红

def fetch_em_dividends(root: str, mc: MarketCode) -> dict[str, Any]:
    """A/BJ 股分红（主源）：东财 18 期 × 19 字段（含股息率/EPS/总股本/除权除息日），list。"""
    return _call(
        root, mc, "stock_fhps_detail_em", "eastmoney", "dividends",
        lambda: ak.stock_fhps_detail_em(symbol=mc.code), shape="records",
    )


def fetch_ths_dividends(root: str, mc: MarketCode) -> dict[str, Any]:
    """A/BJ 股分红（补充源）：同花顺 30 期 × 11 字段（独有股利支付率/税前分红率，含不分配记录）。"""
    return _call(
        root, mc, "stock_fhps_detail_ths", "ths", "dividends",
        lambda: ak.stock_fhps_detail_ths(symbol=mc.code), shape="records",
    )


def fetch_cninfo_dividends(root: str, mc: MarketCode) -> dict[str, Any]:
    """A/BJ 股分红（补充源）：巨潮 17 期 × 11 字段（独有分红类型列：年度/中期）。"""
    return _call(
        root, mc, "stock_dividend_cninfo", "cninfo", "dividends",
        lambda: ak.stock_dividend_cninfo(symbol=mc.code), shape="records",
    )


def fetch_hk_dividends(root: str, mc: MarketCode) -> dict[str, Any]:
    """港股分红（主源）：东财 27 期 × 7 字段（财政年度/分红方案/除净日/过户日/发放日）。"""
    return _call(
        root, mc, "stock_hk_dividend_payout_em", "eastmoney", "dividends",
        lambda: ak.stock_hk_dividend_payout_em(symbol=mc.code), shape="records",
    )


# ---------------------------------------------------------------- forecast 盈利预测

def fetch_em_forecast(root: str, mc: MarketCode) -> dict[str, Any]:
    """A/BJ 股盈利预测（主源）：东财一致预期 + 评级分布，1 行。
    注意：接口是全市场拉取后按代码筛选（symbol 参数是行业板块不是代码，探测确认）。"""
    def _fetch() -> pd.DataFrame:
        frame = ak.stock_profit_forecast_em(symbol="")
        if frame is None or frame.empty:
            return frame
        code_col = "代码" if "代码" in frame.columns else str(frame.columns[1])
        return frame[frame[code_col].astype(str).str.zfill(6) == mc.code]
    return _call(
        root, mc, "stock_profit_forecast_em", "eastmoney", "forecast",
        _fetch, shape="row",
    )


def fetch_ths_forecast(root: str, mc: MarketCode) -> dict[str, Any]:
    """A/BJ 股盈利预测（补充源）：同花顺 预测分布（年度/机构数/min/均值/max/行业均值），list。"""
    return _call(
        root, mc, "stock_profit_forecast_ths", "ths", "forecast",
        lambda: ak.stock_profit_forecast_ths(symbol=mc.code, indicator="预测年报每股收益"), shape="records",
    )


def fetch_et_forecast(root: str, mc: MarketCode) -> dict[str, Any]:
    """港股盈利预测（主源）：经济通分券商明细 55 行（财政年度/纯利/EPS/派息/券商/评级/目标价）。
    必须直连（走代理报 SSLError，探测确认）。"""
    return _call(
        root, mc, "stock_hk_profit_forecast_et", "etnet", "forecast",
        lambda: ak.stock_hk_profit_forecast_et(symbol=mc.code), shape="records",
    )


# ---------------------------------------------------------------- holders 股东

def fetch_sina_holders(root: str, mc: MarketCode) -> dict[str, Any]:
    """A/BJ 股股东（主源）：新浪历史多期序列（股东名称/持股数量比例/股本性质/截至日/公告日/股东总数）。"""
    symbol = ("bj" if mc.market == "BJ" else ("sh" if mc.suffix == "SH" else "sz")) + mc.code
    return _call(
        root, mc, "stock_main_stock_holder", "sina", "holders",
        lambda: ak.stock_main_stock_holder(stock=symbol), shape="records",
    )
