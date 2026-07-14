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

from ashare_announcements_mcp.api import fetch_all_announcements, fetch_updates
from ashare_announcements_mcp.cache import load_cache, merge_items, save_cache
from ashare_announcements_mcp.downloader import download_pdf
from ashare_announcements_mcp.reader import inspect_pdf, read_pdf, search_pdf


mcp = FastMCP("A 股公告阅读")
PAGE_SIZE = 50


def _stock_code(value: str) -> str:
    """兼容 002271、SZ002271、002271.SZ 等常见格式。"""
    matches = re.findall(r"(?<!\d)(\d{6})(?!\d)", str(value).strip().upper())
    if len(matches) != 1:
        raise ValueError("stock_code 必须包含一个六位股票代码")
    return matches[0]


def _optional_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是 YYYY-MM-DD 格式") from exc


def _keyword_matches(item: dict[str, Any], keyword: str | None) -> bool:
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


def _sync_archive(code: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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


@mcp.tool()
def query_announcements(
    stock_code: str,
    page: int = 1,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    """查询完整公告档案；首次全量建档，之后每次查询前自动检查新公告。"""
    try:
        code = _stock_code(stock_code)
        start = _optional_date(start_date, "start_date")
        end = _optional_date(end_date, "end_date")
        if start and end and start > end:
            raise ValueError("start_date 不能晚于 end_date")
        if page < 1:
            raise ValueError("page 必须大于等于 1")

        items, update_status = _sync_archive(code)

        filtered = []
        for item in items:
            item_date = str(item.get("display_time") or "")[:10]
            if start and item_date and item_date < start.isoformat():
                continue
            if end and item_date and item_date > end.isoformat():
                continue
            if not _keyword_matches(item, keyword):
                continue
            filtered.append(item)

        offset = (page - 1) * PAGE_SIZE
        matched = len(filtered)
        total_pages = (matched + PAGE_SIZE - 1) // PAGE_SIZE
        return {
            "ok": True,
            "stock_code": code,
            "stock_name": items[0].get("short_name", "") if items else "",
            "total_announcements": len(items),
            "matched": matched,
            "page": page,
            "page_size": PAGE_SIZE,
            "total_pages": total_pages,
            "has_more": page < total_pages,
            **update_status,
            "results": filtered[offset : offset + PAGE_SIZE],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def inspect_announcement(
    stock_code: str,
    url: str,
) -> dict[str, Any]:
    """检查公告页数、文本覆盖、扫描页和目录；长公告应先调用本工具。"""
    try:
        code = _stock_code(stock_code)
        _validate_pdf_url(url)
        path, cache_hit = download_pdf(code, url)
        return {"ok": True, "cache_hit": cache_hit, "path": str(path), **inspect_pdf(path, code)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
async def search_announcement(
    stock_code: str,
    url: str,
    query: str,
    max_results: int = 20,
    ocr_scanned: bool = True,
) -> dict[str, Any]:
    """检索整份公告；扫描页每次 OCR 三页，search_complete=false 时用相同参数续建索引。"""
    try:
        code = _stock_code(stock_code)
        _validate_pdf_url(url)
        if not 1 <= max_results <= 100:
            raise ValueError("max_results 必须在 1 到 100 之间")
        path, cache_hit = download_pdf(code, url)
        return {
            "ok": True,
            "cache_hit": cache_hit,
            "path": str(path),
            **search_pdf(path, code, query, max_results, ocr_scanned),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _validate_pdf_url(url: str) -> None:
    if not url.startswith("https://pdf.dfcfw.com/pdf/"):
        raise ValueError("url 必须是东方财富 pdf.dfcfw.com 公告链接")


@mcp.tool()
async def read_announcement(
    stock_code: str,
    url: str,
    start_page: int = 1,
    end_page: int | None = None,
    max_chars: int = 12_000,
    ocr: bool = True,
) -> dict[str, Any]:
    """按完整页面读取公告，保留 Markdown 表格；扫描页自动 OCR，长文用 next_page 续读。"""
    try:
        code = _stock_code(stock_code)
        _validate_pdf_url(url)
        path, cache_hit = download_pdf(code, url)
        result = read_pdf(
            path,
            code,
            start_page=start_page,
            end_page=end_page,
            max_chars=max_chars,
            ocr=ocr,
        )
        return {"ok": True, "cache_hit": cache_hit, "path": str(path), **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    mcp.run()
