# -*- coding: utf-8 -*-
"""A股市场模块：行情 + 财报。

数据源与回退（探测记录第二节）：
- 行情：东财 push2his（曾整域限流）→ 失败回退新浪 stock_zh_a_daily
- 三表/指标/股东/主营/分红/预测：东财 datacenter，探测期内稳定
- 基本信息：巨潮 stock_profile_cninfo（含 H 股代码字段）
- 历史市值无现成接口：报告期股本 × 不复权收盘价估算（季度级精度）
"""
import os

import pandas as pd

from ._common import (
    em_symbol_a, resample_ohlcv, save, log,
)

try:
    import akshare as ak
except ImportError:
    ak = None


# ============================================
# 行情
# ============================================

def fetch_daily(code: str, start: str, end: str, adjust: str = "qfq", period: str = "daily") -> pd.DataFrame:
    """日线/周线/月线（复权可选）。东财 → 新浪回退。

    adjust: qfq=前复权 hfq=后复权 ""=不复权
    period: daily/weekly/monthly；新浪回退时周/月线由日线本地聚合。
    """
    try:
        df = ak.stock_zh_a_hist(
            symbol=code, period=period,
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust=adjust,
        )
        df = df.rename(columns={
            "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
            "最低": "low", "成交量": "volume", "成交额": "amount",
            "振幅": "amplitude", "涨跌幅": "quote_change", "涨跌额": "change",
            "换手率": "turnover",
        })
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["source"] = "eastmoney"
        return df
    except Exception as e:
        log(f"东财行情失败({type(e).__name__})，回退新浪: {str(e)[:80]}")
        df = ak.stock_zh_a_daily(
            symbol=("sh" if code.startswith("6") else ("bj" if code.startswith(("4", "8")) else "sz")) + code,
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust=adjust,
        )
        df = df.rename(columns={
            "date": "date", "open": "open", "high": "high",
            "low": "low", "close": "close", "volume": "volume",
            "amount": "amount", "turnover": "turnover",
        })
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["source"] = "sina"
        if period != "daily":
            df = resample_ohlcv(df, period)
        return df


def fetch_raw_close(code: str, start: str, end: str) -> pd.DataFrame:
    """不复权收盘价（市值估算用）。东财 → 新浪回退。"""
    try:
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="",
        )
        return df[["日期", "收盘"]].rename(columns={"日期": "date", "收盘": "close_raw"})
    except Exception as e:
        log(f"东财不复权失败({type(e).__name__})，回退新浪: {str(e)[:80]}")
        df = ak.stock_zh_a_daily(
            symbol=("sh" if code.startswith("6") else ("bj" if code.startswith(("4", "8")) else "sz")) + code,
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="",
        )
        return df[["date", "close"]].rename(columns={"date": "date", "close": "close_raw"})


def fetch_share_capital(code: str) -> pd.DataFrame:
    """资产负债表报告期股本（股）"""
    df = ak.stock_balance_sheet_by_report_em(symbol=em_symbol_a(code))
    out = df[["REPORT_DATE", "SHARE_CAPITAL"]].copy()
    out["REPORT_DATE"] = pd.to_datetime(out["REPORT_DATE"]).dt.strftime("%Y-%m-%d")
    out = out.dropna(subset=["SHARE_CAPITAL"]).sort_values("REPORT_DATE")
    return out


def estimate_market_cap(code: str, start: str, end: str) -> pd.DataFrame:
    """历史总市值估算：报告期股本 × 不复权收盘价（亿元）"""
    raw = fetch_raw_close(code, start, end)
    shares = fetch_share_capital(code)
    if shares.empty:
        raise RuntimeError("未获取到报告期股本数据")
    raw["date"] = pd.to_datetime(raw["date"])
    shares["REPORT_DATE"] = pd.to_datetime(shares["REPORT_DATE"])
    merged = pd.merge_asof(
        raw.sort_values("date"),
        shares.sort_values("REPORT_DATE"),
        left_on="date", right_on="REPORT_DATE", direction="backward",
    )
    merged["market_cap_yi"] = merged["close_raw"] * merged["SHARE_CAPITAL"] / 1e8
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    return merged[["date", "market_cap_yi"]]


def quote(code: str, start: str, end: str, out_dir: str) -> None:
    """行情入口：输出 {code}_行情.csv"""
    os.makedirs(out_dir, exist_ok=True)
    log(f"[A股] 提取行情: {code}  {start} → {end}")
    daily = fetch_daily(code, start, end)
    mcap = estimate_market_cap(code, start, end)
    out = daily.merge(mcap, on="date", how="left")
    path = os.path.join(out_dir, f"{code}_行情.csv")
    out.to_csv(path, index=False, encoding="utf-8-sig")
    log(f"共 {len(out)} 行，保存: {path}")


# ============================================
# 财报
# ============================================

def financial(code: str, out_dir: str) -> None:
    """财报入口：输出 10 类 {code}_*.csv"""
    os.makedirs(out_dir, exist_ok=True)
    em = em_symbol_a(code)
    em_low = em.lower()
    sec_suffix = "SH" if code.startswith("6") else "SZ"
    sec_code = f"{code}.{sec_suffix}"

    tasks = [
        ("公司基本信息", lambda: ak.stock_profile_cninfo(symbol=code), "基本信息"),
        ("IPO 信息", lambda: ak.stock_ipo_info(code), "IPO"),
        ("利润表", lambda: ak.stock_profit_sheet_by_report_em(symbol=em), "利润表"),
        ("资产负债表", lambda: ak.stock_balance_sheet_by_report_em(symbol=em), "资产负债表"),
        ("现金流量表", lambda: ak.stock_cash_flow_sheet_by_report_em(symbol=em), "现金流量表"),
        ("财务指标", lambda: ak.stock_financial_analysis_indicator_em(symbol=sec_code, indicator="按报告期"), "财务指标"),
        ("十大股东", lambda: _top10_em(sec_code, em_low), "十大股东"),
        ("主营构成", lambda: ak.stock_zygc_em(symbol=em), "主营构成"),
        ("分红", lambda: ak.stock_fhps_detail_em(symbol=code), "分红"),
        ("盈利预测", lambda: _profit_forecast(code), "盈利预测"),
    ]
    for i, (label, fn, fname) in enumerate(tasks, 1):
        log(f"[{i}/{len(tasks)}] {label}")
        try:
            df = fn()
            if df is None or len(df) == 0:
                log("  空结果")
                continue
            save(df, os.path.join(out_dir, f"{code}_{fname}.csv"))
        except Exception as e:
            log(f"  FAIL: {type(e).__name__}: {str(e)[:120]}")


def _top10_em(sec_code: str, em_low: str) -> pd.DataFrame:
    """十大股东：报告期自动取财务指标最新期"""
    ind = ak.stock_financial_analysis_indicator_em(symbol=sec_code, indicator="按报告期")
    latest_q = pd.to_datetime(ind["REPORT_DATE"].iloc[0]).strftime("%Y%m%d")
    return ak.stock_gdfx_top_10_em(symbol=em_low, date=latest_q)


def _profit_forecast(code: str) -> pd.DataFrame:
    """一致预期：全市场拉取后按代码筛（探测记录：symbol 参数是行业板块不是代码）"""
    df = ak.stock_profit_forecast_em(symbol="")
    return df[df["代码"] == code]
