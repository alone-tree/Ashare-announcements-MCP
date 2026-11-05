# -*- coding: utf-8 -*-
"""缓存读写与覆盖判定（字段级独立缓存）。

缓存文件：{root}/cache/{标准代码}/{字段}.json，JSON {meta, items}
items：`[{date, value, source}]`——每条记录带 source，便于追踪与后期增加其他来源
      （同一字段不同来源的记录可并存，读取时按字段链优先级取源）。
meta: code / market / field / source / updated_at / date_range / shape
- updated_at：写入时间（自动）
- date_range：数据实际覆盖范围 {"start": "...", "end": "..."}（请求模块写入）
- shape：数据形状 {"rows": N}（自动）

覆盖判定：
- 实际数据完整覆盖请求范围时直接返回缓存；
- 实际终点尚未覆盖，但最近一次成功请求写入缓存距今不足 10 分钟时，短期复用缓存；
- 满 10 分钟后重新请求上游。程序不判断交易所开收盘、周末或节假日。
start/end 为 None 视为不约束该侧；日期为 YYYY-MM-DD 字符串，字典序即时间序。

缓存文件清单（2026-08-09 用户拍板：字段级独立 json）：
- 高开低收原值：open / high / low / close
- 收盘价后复权：close_hfq（仅存 close）
- 成交额/成交量：amount / volume
- 总股本/流通股本：total_shares / floating_shares
其余（qfq、市值、换手率、周月线、hfq OHL）全部派生现算，不落盘。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from typing import Any

# 实际数据尚未覆盖请求终点时，短期复用最近一次成功请求写入的缓存。
# 用户决策：固定 10 分钟，不暴露为参数，不判断交易所开收盘时间。
INCOMPLETE_RETRY_INTERVAL = timedelta(minutes=10)

# 字段 → 缓存文件名（2026-08-09 用户拍板）
DATA_FILES = {
    "open": "open.json",
    "high": "high.json",
    "low": "low.json",
    "close": "close.json",
    "close_hfq": "close_hfq.json",
    "volume": "volume.json",
    "amount": "amount.json",
    "total_shares": "total_shares.json",
    "floating_shares": "floating_shares.json",
    "total_market_cap": "total_market_cap.json",
    **{field: f"{field}.json" for field in (
        "open_hfq", "high_hfq", "low_hfq", "avg_price", "avg_price_hfq", "turnover",
        "company_total_shares", "security_total_shares", "company_total_market_cap", "security_total_market_cap")},
}

# 行情原始字段（新浪宽拉列）
RAW_FIELDS = ("open", "high", "low", "close", "volume", "amount")
# 股本字段
SHARE_FIELDS = ("total_shares", "floating_shares")


def data_root(root: str | None = None) -> str:
    """数据根目录：MARKET_DATA_ROOT 环境变量优先，默认当前目录。"""
    if root:
        return root
    return os.environ.get("MARKET_DATA_ROOT", os.getcwd())


def cache_path(root: str, code: str, field: str) -> str:
    """缓存文件路径。code 为标准代码（带后缀，如 600519.SH）。"""
    if field not in DATA_FILES:
        raise ValueError(f"未知字段：{field}（支持 {sorted(DATA_FILES)}）")
    return os.path.join(root, "cache", code, DATA_FILES[field])


def read_cache(root: str, code: str, field: str) -> dict[str, Any] | None:
    """读字段缓存，返回 {meta, items}；不存在或损坏返回 None。"""
    path = cache_path(root, code, field)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def merge_items(existing: list[dict] | None, fresh: list[dict]) -> list[dict]:
    """按 (date, source) 维度合并：同 date 同 source 新数据覆盖，异 source 并存。
    升序返回（date, source）。"""
    by_key = {(r.get("date"), r.get("source")): r for r in (existing or [])}
    for r in fresh:
        by_key[(r.get("date"), r.get("source"))] = r
    return sorted(by_key.values(), key=lambda r: (r.get("date") or "", r.get("source") or ""))


def write_cache(
    root: str,
    code: str,
    field: str,
    *,
    meta: dict[str, Any],
    items: Any,
) -> str:
    """写字段缓存（原子：先写临时文件再改名）。meta 自动补 updated_at/date_range/shape。
    items 为 [{date, value, source}]。"""
    path = cache_path(root, code, field)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    meta = dict(meta)
    meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta.setdefault("date_range", None)
    meta.setdefault("shape", _shape_of(items))
    payload = {"meta": meta, "items": items}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path


def refresh_cache(root: str, code: str, field: str) -> dict[str, Any] | None:
    """上游请求成功但没有新行时，刷新已有字段缓存的 updated_at；无缓存不创建空文件。"""
    data = read_cache(root, code, field)
    if data is None:
        return None
    old = data.get("meta") or {}
    meta = {k: old.get(k) for k in ("code", "market", "field", "source", "date_range")}
    write_cache(root, code, field, meta=meta, items=data.get("items") or [])
    return meta.get("date_range")


def _shape_of(items: Any) -> dict[str, Any]:
    if isinstance(items, list):
        return {"rows": len(items)}
    return {}


def coverage(meta: dict[str, Any], start: str | None, end: str | None,
             market: str | None = None, now: datetime | None = None) -> bool:
    """判断缓存是否可复用。

    实际日期范围完整覆盖请求时直接复用。若仅终点不足，但本缓存距最近一次成功请求
    写入尚不足 10 分钟，也短期复用；满 10 分钟后重新请求上游。market 参数保留兼容
    现有调用方，不参与判断。
    """
    del market
    dr = meta.get("date_range") or {}
    c_start, c_end = dr.get("start"), dr.get("end")
    if start is not None and (c_start is None or c_start > start):
        return False
    if end is None or (c_end is not None and c_end >= end):
        return True
    updated_at = meta.get("updated_at")
    if not updated_at:
        return False
    try:
        updated = datetime.fromisoformat(updated_at)
    except (TypeError, ValueError):
        return False
    now = now or datetime.now()
    elapsed = now - updated
    return timedelta(0) <= elapsed < INCOMPLETE_RETRY_INTERVAL
