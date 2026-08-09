# -*- coding: utf-8 -*-
"""缓存读写与覆盖判定。

缓存文件：{root}/cache/{标准代码}/{data_type}.json，JSON {meta, items}
meta: code / market / data_type / source / updated_at / date_range / shape
- updated_at：写入时间（自动）
- date_range：数据实际覆盖范围 {"start": "...", "end": "..."}（请求模块写入）
- shape：数据形状 {"rows": N}（自动）

覆盖判定（2026-08-08 用户拍板）：**完整覆盖才算够**——
c_start ≤ start 且 c_end ≥ end（双向段覆盖）才直接返回缓存；
其他情况缺什么补什么。start/end 为 None 视为不约束该侧。
日期为 YYYY-MM-DD 字符串，字典序即时间序，直接比较。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# 数据文件（架构 §1.2 工具表）：缓存文件名
DATA_FILES = {
    "quote_daily_raw": "quote_daily_raw.json",      # get_quote raw（OHLC 四列）
    "quote_daily_hfq": "quote_daily_hfq.json",      # get_quote hfq（仅 close）
    "shares": "shares.json",                        # 股本（市值现算用）
    "financial_income": "financial_income.json",    # 利润表
    "financial_balance": "financial_balance.json",  # 资产负债表
    "financial_cash_flow": "financial_cash_flow.json",  # 现金流量表
    "ratios": "ratios.json",                        # 财务衍生指标
    "profile": "profile.json",                      # 公司概况/分红/盈利预测
}


def data_root(root: str | None = None) -> str:
    """数据根目录：MARKET_DATA_ROOT 环境变量优先，默认当前目录。"""
    if root:
        return root
    return os.environ.get("MARKET_DATA_ROOT", os.getcwd())


def cache_path(root: str, code: str, data_type: str) -> str:
    """缓存文件路径。code 为标准代码（带后缀，如 600519.SH）。"""
    if data_type not in DATA_FILES:
        raise ValueError(f"未知数据类型：{data_type}（支持 {sorted(DATA_FILES)}）")
    return os.path.join(root, "cache", code, DATA_FILES[data_type])


def read_cache(root: str, code: str, data_type: str) -> dict[str, Any] | None:
    """读缓存，返回 {meta, items}；不存在或损坏返回 None。"""
    path = cache_path(root, code, data_type)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_cache(
    root: str,
    code: str,
    data_type: str,
    *,
    meta: dict[str, Any],
    items: Any,
) -> str:
    """写缓存（原子：先写临时文件再改名）。meta 自动补 updated_at/date_range/shape。"""
    path = cache_path(root, code, data_type)
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
    if isinstance(items, dict):
        return {"keys": len(items)}
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
