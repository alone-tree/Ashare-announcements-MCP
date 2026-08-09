# -*- coding: utf-8 -*-
"""缓存读写与覆盖判定（字段级独立缓存）。

缓存文件：{root}/cache/{标准代码}/{字段}.json，JSON {meta, items}
items：`[{date, value, source}]`——每条记录带 source，便于追踪与后期增加其他来源
      （同一字段不同来源的记录可并存，读取时按字段链优先级取源）。
meta: code / market / field / source / updated_at / date_range / shape
- updated_at：写入时间（自动）
- date_range：数据实际覆盖范围 {"start": "...", "end": "..."}（请求模块写入）
- shape：数据形状 {"rows": N}（自动）

覆盖判定（2026-08-08 用户拍板）：**完整覆盖才算够**——
c_start ≤ start 且 c_end ≥ end（双向段覆盖）才直接返回缓存；
其他情况缺什么补什么。start/end 为 None 视为不约束该侧。
日期为 YYYY-MM-DD 字符串，字典序即时间序，直接比较。

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
from typing import Any

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
    meta.setdefault("updated_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
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


def _shape_of(items: Any) -> dict[str, Any]:
    if isinstance(items, list):
        return {"rows": len(items)}
    return {}


def coverage(meta: dict[str, Any], start: str | None, end: str | None) -> bool:
    """覆盖判定：缓存完整覆盖请求日期段才算够（c_start ≤ start 且 c_end ≥ end）。
    meta 无 date_range 或日期缺失视为不覆盖。"""
    dr = meta.get("date_range") or {}
    c_start, c_end = dr.get("start"), dr.get("end")
    if start is not None and c_start is None:
        return False
    if end is not None and c_end is None:
        return False
    if start is not None and c_start > start:
        return False
    if end is not None and c_end < end:
        return False
    return True
