# -*- coding: utf-8 -*-
"""新浪整组行情取数与规范化，返回data字段批次，不直接写业务缓存。

A/B/北交所用stock_zh_a_daily，港美用对应daily；raw返回真实字段组，
hfq仅保留close_hfq。港美全量拉取后本地按日期筛选。契约见架构§1.8。
"""

from __future__ import annotations

import math
import os
import time
from datetime import date as _date

import akshare as ak
import pandas as pd

from market_data_mcp import audit
from market_data_mcp.routing import MarketCode

# 新浪为国内源：清代理直连（Hermes 注入的代理对数据接口致 ProxyError/SSLError）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

SOURCE = "sina"

# 市场 → (akshare 接口名, 是否无 start/end 需本地过滤, raw 宽写字段列)
_APIS = {
    "A": ("stock_zh_a_daily", False, ("open", "high", "low", "close", "volume", "amount", "floating_shares")),
    "BJ": ("stock_zh_a_daily", False, ("open", "high", "low", "close", "volume", "amount", "floating_shares")),
    "HK": ("stock_hk_daily", True, ("open", "high", "low", "close", "volume", "amount")),
    "US": ("stock_us_daily", True, ("open", "high", "low", "close", "volume")),
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


def _fetch(
    root: str,
    mc: MarketCode,
    start: str | None,
    end: str | None,
    adjust: str,
) -> dict:
    """新浪行情请求（raw/hfq共用），返回尚未提交的字段批次。"""
    api_name, need_filter, raw_fields = _APIS[mc.market]
    if adjust == "hfq" and mc.market == "US":
        return {"ok": False, "source": SOURCE, "fields": {},
                "error": "新浪美股接口无 hfq（实测 TypeError），美股后复权走 iFinD 请求模块",
                "notes": None}
    fn = getattr(ak, api_name)
    code = f"{mc.code}.{mc.suffix}"
    t0 = time.time()
    try:
        if mc.market in ("A", "BJ"):
            df = fn(symbol=_sina_symbol(mc), start_date=_fmt(start, "19900101"), end_date=_fmt(end, "21000101"),
                    adjust=adjust)
        else:
            df = fn(symbol=_sina_symbol(mc), adjust=adjust)
    except Exception as exc:  # noqa: BLE001 —— 契约：结构化返回不抛异常
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api=api_name,
                          adjust=adjust, start=start, end=end, ok=False, elapsed=elapsed,
                          error=str(exc))
        return {"ok": False, "source": SOURCE, "fields": {},
                "error": f"新浪 {api_name} 请求失败：{exc}", "notes": None}

    records = _rows_to_records(df)
    fresh = _filter_range(records, start, end)
    field_map = {"close_hfq": "close"} if adjust == "hfq" else {f: f for f in raw_fields}
    if "floating_shares" in field_map:
        field_map["floating_shares"] = "outstanding_share"
    data = {field: [{"date": r["date"], "value": r.get(column), "source": SOURCE} for r in fresh]
            for field, column in field_map.items()}
    fields = {field: {"start": min(r["date"] for r in records), "end": max(r["date"] for r in records)} if records else None
              for field, records in data.items()}

    elapsed = time.time() - t0
    audit.log_request(root, source=SOURCE, market=mc.market, code=code, api=api_name,
                      fields=",".join(df.columns), adjust=adjust, start=start, end=end,
                      ok=True, elapsed=elapsed)
    return {"ok": True, "source": SOURCE, "fields": fields, "data": data, "error": None, "notes": None}


def fetch_raw(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求新浪raw整组字段，不写缓存。"""
    return _fetch(root, mc, start, end, adjust="")


def fetch_hfq(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求新浪 hfq（A/B/北交所/港股，仅存 close_hfq）。美股无此能力，走 iFinD。"""
    return _fetch(root, mc, start, end, adjust="hfq")
