# -*- coding: utf-8 -*-
"""港股市场模块：行情 + 财报（能力边界内）。

数据源与回退（探测记录第三节）：
- 行情：东财 stock_hk_hist（push2his，曾限流）→ 失败回退新浪 stock_hk_daily
- 三表：东财 stock_financial_hk_report_em（长表）
- 财务指标：东财 stock_hk_financial_indicator_em（仅最新 1 行 TTM，无历史）
- 盈利预测：经济通 stock_hk_profit_forecast_et（分券商明细）
- 公司概况：东财 stock_hk_company_profile_em
- 分红：东财 stock_hk_dividend_payout_em
- 无 IPO/十大股东/主营构成 → 从公告原文获取（AGENTS.md 边界）
"""
import os

import pandas as pd

from ._common import (
    em_symbol_hk, save, log,
)

try:
    import akshare as ak
except ImportError:
    ak = None


# ============================================
# 行情
# ============================================

def fetch_daily(code: str, start: str, end: str) -> pd.DataFrame:
    """日线（前复权）。东财 → 新浪回退。"""
    try:
        df = ak.stock_hk_hist(
            symbol=code, period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="qfq",
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
        log(f"东财港股行情失败({type(e).__name__})，回退新浪: {str(e)[:80]}")
        df = ak.stock_hk_daily(symbol=code, adjust="qfq")
        df = df.rename(columns={
            "date": "date", "open": "open", "high": "high",
            "low": "low", "close": "close", "volume": "volume", "amount": "amount",
        })
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        df["source"] = "sina"
        return df


def fetch_raw_close(code: str, start: str, end: str) -> pd.DataFrame:
    """不复权收盘价（市值估算用）。东财 → 新浪回退。"""
    try:
        df = ak.stock_hk_hist(
            symbol=code, period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="",
        )
        return df[["日期", "收盘"]].rename(columns={"日期": "date", "收盘": "close_raw"})
    except Exception as e:
        log(f"东财港股不复权失败({type(e).__name__})，回退新浪: {str(e)[:80]}")
        df = ak.stock_hk_daily(symbol=code, adjust="")
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        return df[["date", "close"]].rename(columns={"date": "date", "close": "close_raw"})


def fetch_share_capital(code: str) -> pd.DataFrame:
    """已发行股本：来自东财港股财务指标（仅最新值，非历史序列）"""
    df = ak.stock_hk_financial_indicator_em(symbol=code)
    # 字段：已发行股本(股)；无报告期列，只有当前值
    cap = df["已发行股本(股)"].iloc[0]
    return pd.DataFrame([{"REPORT_DATE": "1970-01-01", "SHARE_CAPITAL": cap}])


def estimate_market_cap(code: str, start: str, end: str) -> pd.DataFrame:
    """历史总市值估算：当前已发行股本 × 不复权收盘价（亿港元）

    注意：港股无历史股本序列（探测记录），用当前股本近似，历史段会有偏差。
    """
    raw = fetch_raw_close(code, start, end)
    shares = fetch_share_capital(code)
    if shares.empty:
        raise RuntimeError("未获取到已发行股本")
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
    log(f"[港股] 提取行情: {code}  {start} → {end}")
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
    """财报入口：能力边界内输出 {code}_*.csv"""
    os.makedirs(out_dir, exist_ok=True)
    em = em_symbol_hk(code)

    tasks = [
        ("公司概况", lambda: ak.stock_hk_company_profile_em(symbol=code), "公司概况"),
        ("利润表", lambda: ak.stock_financial_hk_report_em(stock=code, symbol="利润表", indicator="年度"), "利润表"),
        ("资产负债表", lambda: ak.stock_financial_hk_report_em(stock=code, symbol="资产负债表", indicator="年度"), "资产负债表"),
        ("现金流量表", lambda: ak.stock_financial_hk_report_em(stock=code, symbol="现金流量表", indicator="年度"), "现金流量表"),
        ("财务指标", lambda: ak.stock_hk_financial_indicator_em(symbol=code), "财务指标"),
        ("分红", lambda: ak.stock_hk_dividend_payout_em(symbol=code), "分红"),
        ("盈利预测", lambda: ak.stock_hk_profit_forecast_et(symbol=code), "盈利预测"),
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

    log("注：港股无 IPO/十大股东/主营构成接口，需从公告原文获取")
