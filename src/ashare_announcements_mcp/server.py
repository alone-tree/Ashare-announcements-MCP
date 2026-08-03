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
from ashare_announcements_mcp.company import check_company, establish_company as establish_securities
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
    query_interactions as query_interactions_service,
)


mcp = FastMCP("A 股公告阅读")


@mcp.tool()
def establish_company(
    action: str = "check",
    keyword: str | None = None,
    codes: list[str] | None = None,
) -> dict[str, Any]:
    """查询或建档东方财富 A/H 上市公司。

    action=check 用 keyword 搜索候选证券（不过滤、不归组，忠实返回前 20 条）。
    action=establish 用 codes 建档（一个代码，或一个 A 股代码加一个 H 股代码；
    不要使用 -R、-WR 等人民币柜台代码建档，应选择主要港股代码）。
    """
    try:
        if action == "check":
            if not keyword:
                raise ValueError("action=check 需要 keyword")
            return {"ok": True, "action": action, **check_company(keyword)}
        if action == "establish":
            return {"ok": True, "action": action, **establish_securities(codes or [])}
        raise ValueError(f"未知 action：{action}")
    except Exception as exc:
        return {"ok": False, "action": action, "error": str(exc)}


@mcp.tool()
def query_announcements(
    stock_code: str,
    page: int = 1,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
    market: str = "all",
) -> dict[str, Any]:
    """查询完整公告档案；首次全量建档，之后每次查询前自动检查新公告。

    market 只筛选本地结果（all/A/H），所有关联证券都会自动增量更新。
    """
    try:
        if page < 1:
            raise ValueError("page 必须大于等于 1")
        result = query_archive(
            stock_code,
            start_date=start_date,
            end_date=end_date,
            keyword=keyword,
            market=market,
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
def query_interactions(
    stock_code: str,
    page: int = 1,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    """查询 A 股互动问答；纯港股返回不适用。首次全量建档，之后增量更新。"""
    try:
        if page < 1:
            raise ValueError("page 必须大于等于 1")
        result = query_interactions_service(
            stock_code,
            start_date=start_date,
            end_date=end_date,
            keyword=keyword,
        )
        return {"ok": True, **paginate_query(result, page, PAGE_SIZE)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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
