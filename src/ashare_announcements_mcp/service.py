"""公告档案同步和查询服务，供 MCP 与 CLI 共用。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ashare_announcements_mcp.api import fetch_all_announcements, fetch_updates
from ashare_announcements_mcp.cache import load_cache, merge_items, save_cache

PAGE_SIZE = 50


def normalize_stock_code(value: str) -> str:
    """兼容 002271、SZ002271、002271.SZ 等常见格式。"""
    matches = re.findall(r"(?<!\d)(\d{6})(?!\d)", str(value).strip().upper())
    if len(matches) != 1:
        raise ValueError("stock_code 必须包含一个六位股票代码")
    return matches[0]


def optional_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是 YYYY-MM-DD 格式") from exc


def keyword_matches(item: dict[str, Any], keyword: str | None) -> bool:
    """空格表示 OR；显式写 AND 时要求所有关键词都命中。"""
    if not keyword:
        return True
    haystack = f"{item.get('title', '')} {item.get('column_name', '')}".lower()
    text = keyword.strip().lower()
    if re.search(r"\s+and\s+", text, flags=re.IGNORECASE):
        terms = [term.strip() for term in re.split(r"\s+and\s+", text, flags=re.IGNORECASE)]
        return all(term in haystack for term in terms if term)
    terms = [term for term in text.split() if term]
    return any(term in haystack for term in terms)


def sync_archive(code: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """维护完整档案；查询层只消费本函数返回的缓存快照。"""
    cached = load_cache(code)
    items = cached.get("items") or []
    meta = cached.get("meta") or {}
    archive_was_complete = bool(items) and bool(meta.get("cache_complete"))
    try:
        if not archive_was_complete:
            fetched, fetch_meta = fetch_all_announcements(code, page_size=PAGE_SIZE)
            if not fetch_meta.get("cache_complete"):
                raise RuntimeError("首次建档未能获取全部公告")
            items = merge_items([], fetched)
            new_count = len(items)
        else:
            known_codes = {
                str(item.get("code") or item.get("url") or "") for item in items
            }
            fetched, fetch_meta = fetch_updates(code, known_codes, page_size=PAGE_SIZE)
            new_count = len(fetched)
            if not fetched:
                return items, {
                    "update_check_ok": True,
                    "new_announcements": 0,
                    "update_error": None,
                }
            items = merge_items(items, fetched)
        meta = {**meta, **fetch_meta, "cache_complete": True}
        save_cache(code, items, meta)
        return items, {
            "update_check_ok": True,
            "new_announcements": new_count,
            "update_error": None,
        }
    except Exception as exc:
        if archive_was_complete:
            return items, {
                "update_check_ok": False,
                "new_announcements": 0,
                "update_error": str(exc),
            }
        raise RuntimeError(f"无法建立完整公告档案：{exc}") from exc


def query_archive(
    stock_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    """同步完整档案并返回本地筛选后的全部匹配公告。"""
    code = normalize_stock_code(stock_code)
    start = optional_date(start_date, "start_date")
    end = optional_date(end_date, "end_date")
    if start and end and start > end:
        raise ValueError("start_date 不能晚于 end_date")

    items, update_status = sync_archive(code)
    filtered = []
    for item in items:
        item_date = str(item.get("display_time") or "")[:10]
        if start and item_date and item_date < start.isoformat():
            continue
        if end and item_date and item_date > end.isoformat():
            continue
        if not keyword_matches(item, keyword):
            continue
        filtered.append(item)

    return {
        "stock_code": code,
        "stock_name": items[0].get("short_name", "") if items else "",
        "total_announcements": len(items),
        "matched": len(filtered),
        **update_status,
        "results": filtered,
    }


def paginate_query(result: dict[str, Any], page: int, page_size: int = PAGE_SIZE) -> dict[str, Any]:
    """把完整查询结果转换成 MCP 的固定分页契约。"""
    if page < 1:
        raise ValueError("page 必须大于等于 1")
    if page_size < 1:
        raise ValueError("page_size 必须大于等于 1")
    results = result.get("results") or []
    matched = len(results)
    total_pages = (matched + page_size - 1) // page_size
    offset = (page - 1) * page_size
    return {
        **{key: value for key, value in result.items() if key != "results"},
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_more": page < total_pages,
        "results": results[offset : offset + page_size],
    }
