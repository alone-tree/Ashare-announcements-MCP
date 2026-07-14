"""A 股公告 MCP Server 入口。"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

# 支持直接执行导出目录中的 server.py。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP

from ashare_announcements_mcp.api import fetch_announcements
from ashare_announcements_mcp.cache import load_cache, merge_items, save_cache
from ashare_announcements_mcp.downloader import download_pdf
from ashare_announcements_mcp.reader import read_pdf


mcp = FastMCP("A 股公告阅读")


def _stock_code(value: str) -> str:
    code = str(value).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("stock_code 必须是六位数字")
    return code


def _optional_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是 YYYY-MM-DD 格式") from exc


def _keyword_matches(item: dict[str, Any], keyword: str | None) -> bool:
    """竖线表示 OR，每组内的空格表示 AND。"""
    if not keyword:
        return True
    haystack = f"{item.get('title', '')} {item.get('column_name', '')}".lower()
    groups = [group.split() for group in keyword.lower().split("|") if group.strip()]
    return any(all(word in haystack for word in group) for group in groups)


@mcp.tool()
def query_announcements(
    stock_code: str,
    keyword: str | None = None,
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page: int = 1,
    page_size: int = 50,
    refresh: bool = False,
    max_pages: int = 20,
) -> dict[str, Any]:
    """查询 A 股公司公告。首次查询或 refresh=true 时从东方财富抓取并缓存。"""
    try:
        code = _stock_code(stock_code)
        start = _optional_date(start_date, "start_date")
        end = _optional_date(end_date, "end_date")
        if start and end and start > end:
            raise ValueError("start_date 不能晚于 end_date")
        if page < 1 or not 1 <= page_size <= 200 or not 1 <= max_pages <= 200:
            raise ValueError("page >= 1，page_size 为 1-200，max_pages 为 1-200")

        cached = load_cache(code)
        items = cached.get("items") or []
        meta = cached.get("meta") or {}
        cache_hit = bool(items) and not refresh
        if not cache_hit:
            fetched, fetch_meta = fetch_announcements(code, max_pages=max_pages, stop_before=start)
            items = merge_items(items, fetched)
            meta = {**meta, **fetch_meta}
            save_cache(code, items, meta)

        filtered = []
        for item in items:
            item_date = str(item.get("display_time") or "")[:10]
            if start and item_date and item_date < start.isoformat():
                continue
            if end and item_date and item_date > end.isoformat():
                continue
            if category and category.lower() not in str(item.get("column_name") or "").lower():
                continue
            if not _keyword_matches(item, keyword):
                continue
            filtered.append(item)

        offset = (page - 1) * page_size
        total_filtered = len(filtered)
        return {
            "ok": True,
            "stock_code": code,
            "stock_name": items[0].get("short_name", "") if items else "",
            "cache_hit": cache_hit,
            "total_cached": len(items),
            "source_total": meta.get("source_total"),
            "cache_complete": bool(meta.get("cache_complete")),
            "filtered": total_filtered,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_filtered + page_size - 1) // page_size,
            "results": filtered[offset : offset + page_size],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def read_announcement(
    stock_code: str,
    url: str,
    max_chars: int = 8000,
    start_page: int = 0,
    start_char: int = 0,
) -> dict[str, Any]:
    """下载并读取公告 PDF；长公告用返回的 next_page 和 next_char 继续读取。"""
    try:
        code = _stock_code(stock_code)
        if not url.startswith("https://pdf.dfcfw.com/pdf/"):
            raise ValueError("url 必须是东方财富 pdf.dfcfw.com 公告链接")
        if not 1 <= max_chars <= 100_000:
            raise ValueError("max_chars 必须在 1 到 100000 之间")
        path, cache_hit = download_pdf(code, url)
        result = read_pdf(
            path,
            max_chars=max_chars,
            start_page=start_page,
            start_char=start_char,
        )
        return {"ok": True, "cache_hit": cache_hit, "path": str(path), **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    mcp.run()
