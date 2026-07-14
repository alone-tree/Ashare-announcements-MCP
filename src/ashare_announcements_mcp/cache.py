"""公告和 PDF 的本地缓存路径。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def app_root() -> Path:
    """导出后默认以用户版根目录为数据根目录。"""
    configured = os.environ.get("ASHARE_ANNOUNCEMENTS_ROOT")
    if configured:
        return Path(configured).resolve()
    package_parent = Path(__file__).resolve().parents[1]
    return package_parent.parent if package_parent.name == "src" else package_parent


def stock_cache_dir(stock_code: str) -> Path:
    path = app_root() / "cache" / stock_code
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_cache(stock_code: str) -> dict[str, Any]:
    path = stock_cache_dir(stock_code) / "announcements.json"
    if not path.exists():
        return {"items": [], "meta": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": [], "meta": {}}
    return data if isinstance(data, dict) else {"items": [], "meta": {}}


def save_cache(stock_code: str, items: list[dict[str, Any]], meta: dict[str, Any]) -> Path:
    path = stock_cache_dir(stock_code) / "announcements.json"
    payload = {
        "meta": {**meta, "updated_at": datetime.now().astimezone().isoformat(timespec="seconds")},
        "items": items,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def merge_items(old_items: list[dict[str, Any]], new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按公告代码去重，新数据优先，并保持时间倒序。"""
    merged: dict[str, dict[str, Any]] = {}
    for item in old_items:
        merged[str(item.get("code") or item.get("url"))] = item
    for item in new_items:
        merged[str(item.get("code") or item.get("url"))] = item
    return sorted(merged.values(), key=lambda item: item.get("display_time", ""), reverse=True)


def pdf_dir(stock_code: str) -> Path:
    path = stock_cache_dir(stock_code) / "pdfs"
    path.mkdir(parents=True, exist_ok=True)
    return path
