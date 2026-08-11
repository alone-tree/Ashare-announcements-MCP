"""A 股公告 MCP Server 入口。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 支持直接执行导出目录中的 server.py。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP
from pydantic import ConfigDict

# FastMCP 默认静默忽略未声明参数（pydantic extra='ignore'），
# AI 传错参数名（如把分页 page 当 start_page）会静默落回默认值，难以察觉。
# 开启严格模式：任何未声明参数在进入工具函数前显式报错，提示 AI 使用正确参数名。
try:
    from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase

    ArgModelBase.model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
    )
except Exception:  # 兼容 mcp 版本差异：拿不到基类时保持默认行为
    pass

from ashare_announcements_mcp.downloader import download_pdf
from ashare_announcements_mcp.company import check_company, establish_company as establish_securities
from ashare_announcements_mcp.reader import (
    initialize_pdf_engine,
    read_pdf,
    search_pdf,
)
from ashare_announcements_mcp.service import (
    PAGE_SIZE,
    normalize_stock_code as _stock_code,
    paginate_query,
    query_archive,
    query_a_share_interactions as query_a_share_interactions_service,
)
from ashare_announcements_mcp.transcripts import (
    query_transcripts as query_transcripts_service,
    search_transcripts as search_transcripts_service,
)


mcp = FastMCP("A 股公告阅读")


@mcp.tool()
def establish_company(
    action: str = "check",
    keyword: str | None = None,
    codes: list[str] | None = None,
) -> dict[str, Any]:
    """查询或建档上市公司。A/H/B 股走东方财富，美股走 SEC EDGAR（官方一手数据，优先于网络搜索的第三方转述）。

    action=check 用 keyword 搜索候选证券（不过滤、不归组，忠实返回前 20 条；候选可能包含权证、ADR、人民币柜台、指数或板块，AI 必须按返回字段自行核对）。
    action=establish 用 codes 建档（一个代码，或一个 A 股代码加一个 H 股代码；
    支持美股字母代码如 AAPL（原生股）或 NIO（ADR）；不要使用 -R、-WR 等人民币柜台代码建档，应选择主要港股代码）。
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
    """查询完整公告档案；首次全量建档，之后每次查询前自动检查新公告（官方一手数据，优先于网络搜索）。

    未建档代码会报错并提示 check → establish → query。市场按代码自动路由：数字代码走东方财富（A/B/H），美股字母代码（如 AAPL/NIO）走 SEC EDGAR，不需要显式指定 market。
    market 只筛选本地结果（all/A/H），美股提交归入 all（不参与 A/H 筛选）。所有关联证券都会自动增量更新。
    market=A 同时包含 B 股公告（B 股不单独筛选）；market=H 只筛港股。
    每页固定 50 条；用 page 翻页，has_more 表示是否还有下一页。
    某个市场更新失败时仍返回旧缓存；可重新查询一次，第二次仍失败则停止重复尝试。
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
async def search_announcement(
    stock_code: str,
    url: str,
    query: str,
    max_results: int = 20,
    ocr_scanned: bool = True,
) -> dict[str, Any]:
    """检索整份公告正文；url 可以是东方财富 pdf.dfcfw.com 链接（A/H/B 股）或 SEC EDGAR 链接（美股，官方一手数据）。

    本工具按 stock_code 作为 PDF 缓存目录，不要求公司已建档；公告是否存在以 url 下载结果为准。
    扫描页每次 OCR 三页，search_complete=false 时用相同参数续建索引。
    """
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
    if Path(url).is_file():
        return
    if url.startswith("https://pdf.dfcfw.com/pdf/"):
        return
    if url.startswith("https://www.sec.gov/Archives/edgar/"):
        return
    raise ValueError("url 必须是东方财富 pdf.dfcfw.com 公告链接、本地已存在的 PDF 文件路径，或 SEC EDGAR 文档链接")


@mcp.tool()
def query_a_share_interactions(
    stock_code: str,
    page: int = 1,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    """查询 A 股互动问答；首次全量建档，之后增量更新。仅适用于 A 股（互动易/e互动 官方问答平台）。

    传 H 股代码时，若该公司有关联 A 股，则返回对应 A 股互动问答；纯港股/B 股/本地公司/美股返回 ok=true、applicable=false、reason 说明不适用。
    每页固定 50 条；用 page 翻页，has_more 表示是否还有下一页。
    """
    try:
        if page < 1:
            raise ValueError("page 必须大于等于 1")
        result = query_a_share_interactions_service(
            stock_code,
            start_date=start_date,
            end_date=end_date,
            keyword=keyword,
        )
        return {"ok": True, **paginate_query(result, page, PAGE_SIZE)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def query_transcripts(
    stock_code: str,
    period: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """查询美股电话会议（earnings call transcript）索引与正文（仅美股适用）。

    不传 period：返回全部财季索引（fiscal_quarter/report_date/status），30 天自动增量同步新财季，force_refresh 强制刷新。
    传 period（如 FY2025-Q1）：返回该财季完整正文（逐发言轮次：作者+内容）。
    索引以公司申报的 10-Q/10-K 报告期为锚：报告列表与 HTML 复用公告档案，不重复下载。
    注：上游数据源（Alpha Spread）的季度标签偶尔与公司申报财季错位（如部分公司偏移一年），
    正文第一句会注明实际报告期（如 "First Quarter 2025"），请以正文为准。
    """
    try:
        return {"ok": True, **query_transcripts_service(stock_code, period, force_refresh)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def search_transcripts(
    stock_code: str,
    query: str,
) -> dict[str, Any]:
    """检索美股电话会议正文；在全部已缓存财季中定位关键词，返回命中财季与片段（仅美股适用）。

    字面关键词检索（空格=AND）。结果含发言作者与上下文片段，可用于跨季度对比管理层口径。
    """
    try:
        return {"ok": True, **search_transcripts_service(stock_code, query)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
async def read_announcement(
    stock_code: str,
    url: str,
    start_page: int | None = None,
    end_page: int | None = None,
    return_pages: int = 20,
    ocr: bool = True,
) -> dict[str, Any]:
    """阅读公告；url 可以是东方财富 pdf.dfcfw.com 链接（A/H/B 股）或 SEC EDGAR 链接（美股，HTML 自动按虚拟页切分，官方一手数据）。

    不传 start_page 时自动检测：≤20 页短公告直接返回全文；>20 页长公告返回画像和前 5 页预览及阅读建议。
    传 start_page 时精读指定页段：从 start_page 起返回 return_pages 页（默认 20 页，可传任意大的值一次读完全文），保留 Markdown 表格，扫描页自动 OCR，用 next_page 续读。
    本工具按 stock_code 作为 PDF 缓存目录，不要求公司已建档；公告是否存在以 url 下载结果为准。
    续读：把上次返回的 next_page 值传给 start_page（如 start_page=50），end_page 可选。
    注意：SEC 补充材料类提交（如 DEFA14A、部分 8-K）的主文档可能只是封面，正文在另一次提交或附件里；
    若 search/read 到的内容与预期不符，检查是否还有正式的 DEF 14A / 主文档提交。
    """
    try:
        code = _stock_code(stock_code)
        _validate_pdf_url(url)
        path, cache_hit = download_pdf(code, url)
        result = read_pdf(
            path,
            code,
            start_page=start_page,
            end_page=end_page,
            return_pages=return_pages,
            ocr=ocr,
        )
        return {"ok": True, "cache_hit": cache_hit, "path": str(path), **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    initialize_pdf_engine()
    mcp.run()
