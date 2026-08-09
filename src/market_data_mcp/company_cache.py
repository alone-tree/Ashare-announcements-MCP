# -*- coding: utf-8 -*-
"""公司信息缓存：按 section 分文件、快照性质、30 天新鲜期。

架构 docs/market-data架构设计.md §5.4（2026-08-09 用户拍板）：
- 每个 section 一个 JSON 文件（profile/ipo/dividends/forecast/holders），快照性质
- **刷新节奏与财报一致：30 天新鲜期**——缓存 30 天内直接返回，超过 30 天自动联网刷新；
  force_refresh 忽略新鲜期强制刷新
- 无行情式日期段覆盖概念（公司信息是快照不是时间序列）

文件格式：{meta, data}
meta: code / market / section / source / updated_at / shape / notes
data: section 数据本体（dict 或 list[dict]，保留上游字段名原样）
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from typing import Any

FRESH_FOR = timedelta(days=30)

# section → 缓存文件名
SECTION_FILES = {
    "profile": "profile.json",
    "ipo": "ipo.json",
    "dividends": "dividends.json",
    "forecast": "forecast.json",
    "holders": "holders.json",
}


def section_dir(root: str, code: str) -> str:
    return os.path.join(root, "cache", code, "company")


def section_path(root: str, code: str, section: str) -> str:
    if section not in SECTION_FILES:
        raise ValueError(f"未知 section：{section}（支持 {sorted(SECTION_FILES)}）")
    return os.path.join(section_dir(root, code), SECTION_FILES[section])


def read_section(root: str, code: str, section: str) -> dict[str, Any] | None:
    """读 section 缓存；不存在或损坏返回 None。"""
    path = section_path(root, code, section)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_section(
    root: str,
    code: str,
    section: str,
    *,
    market: str,
    source: str | None,
    data: Any,
    notes: list[str] | None = None,
) -> str:
    """写 section 缓存（原子：先写临时文件再改名）。meta 自动补 updated_at。"""
    path = section_path(root, code, section)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "meta": {
            "code": code,
            "market": market,
            "section": section,
            "source": source,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "shape": _shape_of(data),
            "notes": notes,
        },
        "data": data,
    }
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, allow_nan=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path


def is_fresh(meta: dict[str, Any], now: datetime | None = None) -> bool:
    """30 天新鲜期判定（与财报一致，2026-08-09 用户拍板）。"""
    text = meta.get("updated_at")
    if not text:
        return False
    try:
        updated = datetime.fromisoformat(str(text))
    except ValueError:
        return False
    return (now or datetime.now()) - updated < FRESH_FOR


def _shape_of(data: Any) -> dict[str, Any]:
    if isinstance(data, list):
        return {"rows": len(data)}
    if isinstance(data, dict):
        return {"fields": len(data)}
    return {}
