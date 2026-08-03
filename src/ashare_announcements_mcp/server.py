"""A 股公告 MCP Server 入口。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 支持直接执行导出目录中的 server.py。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP

from ashare_announcements_mcp.downloader import download_pdf
from ashare_announcements_mcp.company import check_company
from ashare_announcements_mcp.reader import (
    initialize_pdf_engine,
    inspect_pdf,
    read_pdf,
    search_pdf,
)
from ashare_announcements_mcp.service import (
    PAGE_SIZE,
    normalize_stock_code as _stock_code,
    paginate_query,
    query_archive,
)


mcp = FastMCP("A 股公告阅读")


@mcp.tool()
def establish_company(
    keyword: str,
    action: str = "check",
) -> dict[str, Any]:
    """查询东方财富中的 A 股和港股上市公司证券；当前仅支持 check。"""
    try:
        if action != "check":
            raise ValueError("当前仅支持 action=check")
        return {"ok": True, "action": action, **check_company(keyword)}
    except Exception as exc:
        return {"ok": False, "action": action, "error": str(exc)}


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
        if page < 1:
            raise ValueError("page 必须大于等于 1")
        result = query_archive(
            stock_code,
            start_date=start_date,
            end_date=end_date,
            keyword=keyword,
        )
        return {"ok": True, **paginate_query(result, page, PAGE_SIZE)}
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
    initialize_pdf_engine()
    mcp.run()
