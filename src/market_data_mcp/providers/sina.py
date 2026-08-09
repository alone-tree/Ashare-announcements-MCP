# -*- coding: utf-8 -*-
"""新浪行情请求模块（源 × 市场 × 档位 = sina × 各市场 × raw 除权价）。

raw 宽写：一次请求把源返回的全部列写入缓存（字段聚合器按列名消费）。
- A/B 股/北交所：`ak.stock_zh_a_daily(symbol=sh600519/sz000001/bj920002, start_date, end_date, adjust="")`
  返回列：date/open/high/low/close/volume/amount/outstanding_share/turnover（支持 start/end）
- 港股：`ak.stock_hk_daily(symbol=00700, adjust="")`，无 start/end → 拉全量本地过滤
  返回列：date/open/high/low/close/volume/amount
- 美股：`ak.stock_us_daily(symbol=AAPL, adjust="")`，无 start/end → 拉全量本地过滤
  返回列：date/open/high/low/close/volume

模块契约（架构 §1.8）：**结构化返回，不抛异常**——
`{ok, source, path, new_items, date_range, error}`；失败原因可读（供审计与聚合器提示重试）。
每次上游请求写审计日志 logs/requests.jsonl。
"""

from __future__ import annotations

import math
import os
import time
from datetime import date as _date

import akshare as ak
import pandas as pd

from market_data_mcp import audit, cache
from market_data_mcp.routing import MarketCode

# 新浪为国内源：清代理直连（Hermes 注入的代理对数据接口致 ProxyError/SSLError）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

SOURCE = "sina"
DATA_TYPE = "quote_daily_raw"

# 市场 → (akshare 接口名, 是否无 start/end 需本地过滤)
_APIS = {
    "A": ("stock_zh_a_daily", False),  # 含 B 股（同通道）
    "BJ": ("stock_zh_a_daily", False),  # 北交所 bj920002 同接口
    "HK": ("stock_hk_daily", True),
    "US": ("stock_us_daily", True),
}


def _sina_symbol(mc: MarketCode) -> str:
    if mc.market in ("A", "BJ"):
        prefix = "bj" if mc.market == "BJ" else ("sh" if mc.suffix == "SH" else "sz")
        return prefix + mc.code
    return mc.code  # 港股 5 位裸码 / 美股字母


def _fmt(d: str | None, default: str) -> str:
    return (d or "").replace("-", "") or default


def _clean_value(v):
    """NaN 清理必须显式逐值判断（df.where(pd.notnull()) 对 float NaN 不生效）。"""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT:
        return None
    if isinstance(v, _date):  # 含 datetime.datetime
        return v.strftime("%Y-%m-%d")
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    return v


def _rows_to_records(df: pd.DataFrame) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        rec = {}
        for col in df.columns:
            key = str(col).strip().lower()
            rec[key] = _clean_value(row[col])
        records.append(rec)
    return records


def _filter_range(records: list[dict], start: str | None, end: str | None) -> list[dict]:
    if start is None and end is None:
        return records
    out = []
    for r in records:
        d = r.get("date")
        if d is None:
            continue
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        out.append(r)
    return out


def _merge(existing: list[dict] | None, fresh: list[dict]) -> list[dict]:
    """按 date 合并去重（新数据覆盖同日期），升序。"""
    by_date = {r["date"]: r for r in (existing or [])}
    for r in fresh:
        by_date[r["date"]] = r
    return sorted(by_date.values(), key=lambda r: r["date"])


def _standard_code(mc: MarketCode) -> str:
    return f"{mc.code}.{mc.suffix}"


def fetch_raw(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求新浪 raw 并写缓存（宽写全部列）。返回 {ok, source, path, new_items, date_range, error}。"""
    api_name, need_filter = _APIS[mc.market]
    fn = getattr(ak, api_name)
    code = _standard_code(mc)
    t0 = time.time()
    try:
        if mc.market in ("A", "BJ"):
            df = fn(symbol=_sina_symbol(mc), start_date=_fmt(start, "19900101"), end_date=_fmt(end, "21000101"))
        else:
            df = fn(symbol=_sina_symbol(mc))
    except Exception as exc:  # noqa: BLE001 —— 契约：结构化返回不抛异常
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api=api_name,
                          adjust="raw", start=start, end=end, ok=False, elapsed=elapsed,
                          error=str(exc))
        return {"ok": False, "source": SOURCE, "path": None, "new_items": 0,
                "date_range": None, "error": f"新浪 {api_name} 请求失败：{exc}"}

    records = _rows_to_records(df)
    fresh = _filter_range(records, start, end)
    existing = cache.read_cache(root, code, DATA_TYPE)
    existing_items = existing["items"] if existing else None
    merged = _merge(existing_items, fresh)
    date_range = None
    if merged:
        date_range = {"start": merged[0]["date"], "end": merged[-1]["date"]}
    path = cache.write_cache(
        root, code, DATA_TYPE,
        meta={"code": code, "market": mc.market, "data_type": DATA_TYPE,
              "source": SOURCE, "date_range": date_range},
        items=merged,
    )
    elapsed = time.time() - t0
    audit.log_request(root, source=SOURCE, market=mc.market, code=code, api=api_name,
                      fields=",".join(df.columns), adjust="raw", start=start, end=end,
                      ok=True, elapsed=elapsed)
    return {"ok": True, "source": SOURCE, "path": path, "new_items": len(fresh),
            "date_range": date_range, "error": None}
