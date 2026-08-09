# -*- coding: utf-8 -*-
"""新浪行情请求模块（源 × 市场 × 档位 = sina × 各市场 × raw/hfq）。

**拉到什么写什么（2026-08-09 用户拍板）**：一次上游请求返回整组数据，
按字段拆分写入各自独立的 json（open/high/low/close/volume/amount/floating_shares），
items 统一 `[{date, value, source}]`，同字段异 source 并存。
- A/B 股/北交所：`ak.stock_zh_a_daily(symbol=sh600519/sz000001/bj920002, start_date, end_date, adjust="")`
  返回列：date/open/high/low/close/volume/amount/outstanding_share/turnover
  → 写 open/high/low/close/volume/amount/floating_shares（outstanding_share 归流通股本，source=sina）
- 港股：`ak.stock_hk_daily(symbol=00700, adjust="")`，无 start/end → 拉全量本地过滤
  返回列：date/open/high/low/close/volume/amount → 写 6 字段
- 美股：`ak.stock_us_daily(symbol=AAPL, adjust="")`，无 start/end → 拉全量本地过滤
  返回列：date/open/high/low/close/volume → 写 5 字段（无 amount）
- hfq（A/B/北交所/港股）：只写 close_hfq（仅存 close；美股无此能力走 iFinD）

模块契约（架构 §1.8）：**结构化返回，不抛异常**——
`{ok, source, fields, error, notes}`，fields 为 {字段名: date_range}（本次更新的字段）。
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
from market_data_mcp.routing import MarketCode, is_market_closed

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


def _write_fields(root: str, code: str, market: str, fresh: list[dict],
                  field_map: dict[str, str]) -> dict[str, dict | None]:
    """把拉到的行拆分写入各字段 json，返回 {字段: date_range}。field_map: 目标字段 → 源列名。"""
    updated: dict[str, dict | None] = {}
    for field, src_col in field_map.items():
        items = [{"date": r["date"], "value": r.get(src_col), "source": SOURCE}
                 for r in fresh]
        items = [x for x in items if x["value"] is not None or True]  # 保留 None 行（占位）
        existing = cache.read_cache(root, code, field)
        existing_items = existing["items"] if existing else None
        merged = cache.merge_items(existing_items, items)
        date_range = None
        if merged:
            date_range = {"start": merged[0]["date"], "end": merged[-1]["date"]}
        cache.write_cache(
            root, code, field,
            meta={"code": code, "market": market, "field": field,
                  "source": SOURCE, "date_range": date_range},
            items=merged,
        )
        updated[field] = date_range
    return updated


def _fetch(
    root: str,
    mc: MarketCode,
    start: str | None,
    end: str | None,
    adjust: str,
) -> dict:
    """新浪行情请求（raw/hfq 共用）。raw 按字段宽写；hfq 只写 close_hfq。"""
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
    if adjust == "hfq":
        # hfq 缓存只存 close_hfq 一列（派生层按因子还原 OHL）
        hfq_items = [{"date": r["date"], "value": r.get("close"), "source": SOURCE} for r in fresh]
        existing = cache.read_cache(root, code, "close_hfq")
        merged = cache.merge_items(existing["items"] if existing else None, hfq_items)
        date_range = None
        if merged:
            date_range = {"start": merged[0]["date"], "end": merged[-1]["date"]}
        cache.write_cache(root, code, "close_hfq",
                          meta={"code": code, "market": mc.market, "field": "close_hfq",
                                "source": SOURCE, "date_range": date_range},
                          items=merged)
        fields = {"close_hfq": date_range}
    else:
        # raw：按字段宽写。outstanding_share → floating_shares（A 股流通股本口径）
        field_map = {f: f for f in raw_fields}
        if "floating_shares" in raw_fields:
            field_map["floating_shares"] = "outstanding_share"
        fields = _write_fields(root, code, mc.market, fresh, field_map)

    elapsed = time.time() - t0
    # 探测验证（2026-08-09 用户拍板）：返回末日 < end 且市场已收盘 → 写 verified
    # （confirmed: end 之前无更多已收盘数据；周末自动延伸；盘中不写，防当日数据被误缓存）
    if end is not None and is_market_closed(mc.market):
        last = fresh[-1]["date"] if fresh else None
        if last is None or last < end:
            for f in fields:
                cache.set_verified(root, code, f, end)
    audit.log_request(root, source=SOURCE, market=mc.market, code=code, api=api_name,
                      fields=",".join(df.columns), adjust=adjust, start=start, end=end,
                      ok=True, elapsed=elapsed)
    return {"ok": True, "source": SOURCE, "fields": fields, "error": None, "notes": None}


def fetch_raw(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求新浪 raw：宽拉整组，按字段拆分写入 open/high/low/close/volume/amount/floating_shares。"""
    return _fetch(root, mc, start, end, adjust="")


def fetch_hfq(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求新浪 hfq（A/B/北交所/港股，仅存 close_hfq）。美股无此能力，走 iFinD。"""
    return _fetch(root, mc, start, end, adjust="hfq")
