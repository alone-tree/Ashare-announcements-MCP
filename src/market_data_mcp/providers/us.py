# -*- coding: utf-8 -*-
"""美股市场模块：行情 + 财报（能力边界内）。

数据源与回退（探测记录第四节）：
- 行情：东财 stock_us_hist（push2his，曾限流）→ 失败回退新浪 stock_us_daily
- 三表：东财 stock_financial_us_report_em（长表，symbol=综合损益表/资产负债表/现金流量表）
- 财务指标：东财 stock_financial_us_analysis_indicator_em（年报多期）
- 无公司概况/IPO/十大股东/主营构成/分红 → 从公告（SEC EDGAR）获取
"""
import os

import pandas as pd

from ._common import (
    resample_ohlcv,
    save, log,
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

    注意：新浪美股接口不支持后复权（hfq），请求 hfq 且回退新浪时自动降级为前复权。
    """
    try:
        df = ak.stock_us_hist(
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
        log(f"东财美股行情失败({type(e).__name__})，回退新浪: {str(e)[:80]}")
        df = ak.stock_us_daily(symbol=code, adjust="qfq" if adjust == "hfq" else adjust)
        df = df.rename(columns={
            "date": "date", "open": "open", "high": "high",
            "low": "low", "close": "close", "volume": "volume",
        })
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["source"] = "sina"
        return df


def fetch_raw_close(code: str, start: str, end: str) -> pd.DataFrame:
    """不复权收盘价（市值估算用）。东财 → 新浪回退。"""
    try:
        df = ak.stock_us_hist(
            symbol=code, period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="",
        )
        return df[["日期", "收盘"]].rename(columns={"日期": "date", "收盘": "close_raw"})
    except Exception as e:
        log(f"东财美股不复权失败({type(e).__name__})，回退新浪: {str(e)[:80]}")
        df = ak.stock_us_daily(symbol=code, adjust="")
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        return df[["date", "close"]].rename(columns={"date": "date", "close": "close_raw"})


def fetch_total_shares(code: str) -> pd.DataFrame:
    """总股本：美股 AKShare 无接口（探测记录），返回空 → 市值估算跳过"""
    return pd.DataFrame()


def quote(code: str, start: str, end: str, out_dir: str) -> None:
    """行情入口：输出 {code}_行情.csv（美股无市值列，仅日线）"""
    os.makedirs(out_dir, exist_ok=True)
    log(f"[美股] 提取行情: {code}  {start} → {end}")
    daily = fetch_daily(code, start, end)
    path = os.path.join(out_dir, f"{code}_行情.csv")
    daily.to_csv(path, index=False, encoding="utf-8-sig")
    log(f"共 {len(daily)} 行，保存: {path}")


# ============================================
# 财报
# ============================================

def financial(code: str, out_dir: str) -> None:
    """财报入口：能力边界内输出 {code}_*.csv"""
    os.makedirs(out_dir, exist_ok=True)

    tasks = [
        ("综合损益表", lambda: ak.stock_financial_us_report_em(stock=code, symbol="综合损益表", indicator="年报"), "利润表"),
        ("资产负债表", lambda: ak.stock_financial_us_report_em(stock=code, symbol="资产负债表", indicator="年报"), "资产负债表"),
        ("现金流量表", lambda: ak.stock_financial_us_report_em(stock=code, symbol="现金流量表", indicator="年报"), "现金流量表"),
        ("财务指标", lambda: ak.stock_financial_us_analysis_indicator_em(symbol=code, indicator="年报"), "财务指标"),
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

    log("注：美股无公司概况/IPO/十大股东/主营构成/分红接口，需从公告（SEC EDGAR）获取")
