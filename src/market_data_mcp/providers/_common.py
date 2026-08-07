# -*- coding: utf-8 -*-
"""三市场共用工具：代码规范化、市场识别、CSV 保存。

只放真正三市场共用的逻辑；各市场的接口调用与回退策略在各自模块内部。
"""
import os
import sys

import pandas as pd


def detect_market(code: str) -> str:
    """识别市场：纯数字→A股/港股，字母→美股。

    规则（探测记录第五节）：
    - 纯 6 位数字 → A股（如 300476）
    - 纯 5 位数字 → 港股（如 00700）
    - 字母开头 → 美股（如 AAPL）
    - 显式前缀 HK:/US:/A: 可强制指定
    """
    c = str(code).strip().upper()
    if c.startswith(("HK:", "US:", "A:")):
        return {"HK:": "hk", "US:": "us", "A:": "a"}[c[:3]]
    if c.isdigit():
        return "a" if len(c) == 6 else "hk"
    return "us"


def strip_market_prefix(code: str) -> str:
    """去掉显式前缀，返回裸代码"""
    c = str(code).strip().upper()
    for p in ("HK:", "US:", "A:"):
        if c.startswith(p):
            return c[3:]
    return c


def normalize_a_code(code: str) -> str:
    """A股代码规范化：去 .SZ/.SH/.bj 后缀"""
    code = str(code).strip().lower()
    for suffix in (".sz", ".sh", ".bj"):
        if code.endswith(suffix):
            code = code[: -len(suffix)]
            break
    return code


def em_symbol_a(code: str) -> str:
    """东财 A股报表接口代码：SH/SZ/BJ 前缀（探测记录：6开头=沪、900开头=沪B、4/8开头=京、其余=深含200深B）"""
    if code.startswith("6") or code.startswith("900"):
        return f"SH{code}"
    if code.startswith(("4", "8")):
        return f"BJ{code}"
    return f"SZ{code}"


def em_symbol_hk(code: str) -> str:
    """东财港股报表接口代码：SH 前缀"""
    return f"SH{code}"


def sina_symbol_hk(code: str) -> str:
    """新浪港股代码：sh00700"""
    return f"sh{code}"


def save(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  {os.path.basename(path)}: {len(df)} 行 × {len(df.columns)} 列")


def log(msg: str) -> None:
    print(msg, flush=True)


def resample_ohlcv(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """把日线聚合为周线/月线（OHLCV 标准重采样）。

    period: weekly / monthly。
    open=周期首日开盘、high=周期最高、low=周期最低、close=周期末日收盘、
    volume/amount=周期累计；其他列（如换手率）取周期末值。
    仅用于新浪回退路径（新浪接口只提供日线，周/月线由本地聚合）。
    """
    if period == "daily" or df is None or len(df) == 0:
        return df
    rule = {"weekly": "W-FRI", "monthly": "ME"}[period]
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    work = work.set_index("date").sort_index()

    agg: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "amount": "sum",
    }
    # 其余数值列（换手率/涨跌幅等）取周期末值，避免无意义求和
    for col in work.columns:
        if col not in agg and col != "source":
            agg[col] = "last"

    out = work.resample(rule).agg(agg).dropna(subset=["close"])
    out["date"] = out.index.strftime("%Y-%m-%d")
    out = out.reset_index(drop=True)
    if "source" in work.columns:
        out["source"] = work["source"].iloc[0]
    return out
