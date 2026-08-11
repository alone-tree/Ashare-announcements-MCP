"""供确定性批处理脚本调用的公告 JSON CLI。

从 stdin 读取一个 JSON 请求，stdout 只输出一个 JSON 响应。
tool 支持：establish_company、query_batch、query_interactions_batch、search_batch、read_batch。
同 MCP 能力保持一致；批处理查询返回全部匹配结果，不做 MCP 的 50 条分页。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_announcements_mcp.company import (
    check_company,
    establish_company as establish_securities,
)
from ashare_announcements_mcp.service import query_a_share_interactions, query_archive


def _status(items: list[dict[str, Any]]) -> str:
    succeeded = sum(bool(item.get("ok")) for item in items)
    if succeeded == len(items):
        return "success"
    return "partial_success" if succeeded else "failed"


def _batch_response(tool: str, items: list[dict[str, Any]], result_key: str) -> dict[str, Any]:
    succeeded = sum(bool(item.get("ok")) for item in items)
    return {
        "ok": succeeded == len(items),
        "tool": tool,
        "status": _status(items),
        "requested": len(items),
        "succeeded": succeeded,
        "failed": len(items) - succeeded,
        result_key: items,
    }


def query_batch(request: dict[str, Any]) -> dict[str, Any]:
    stock_codes = request.get("stock_codes")
    if not isinstance(stock_codes, list) or not stock_codes:
        raise ValueError("stock_codes 必须是非空数组")

    companies: list[dict[str, Any]] = []
    announcements: list[dict[str, Any]] = []
    for value in stock_codes:
        stock_code = str(value)
        try:
            result = query_archive(
                stock_code,
                start_date=request.get("start_date"),
                end_date=request.get("end_date"),
                keyword=request.get("keyword"),
                market=request.get("market", "all"),
            )
            company = {"ok": True, **result}
            announcements.extend(result.get("results") or [])
        except Exception as exc:
            company = {"ok": False, "stock_code": stock_code, "error": str(exc), "results": []}
        companies.append(company)

    response = _batch_response("query_batch", companies, "companies")
    response["announcements"] = announcements
    response["matched"] = len(announcements)
    return response


def _announcement_identity(item: dict[str, Any]) -> dict[str, str]:
    return {
        "stock_code": str(item.get("stock_code") or ""),
        "url": str(item.get("url") or ""),
        "code": str(item.get("code") or ""),
        "title": str(item.get("title") or ""),
    }


def _search_item(item: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    from ashare_announcements_mcp.downloader import download_pdf
    from ashare_announcements_mcp.reader import search_pdf

    identity = _announcement_identity(item)
    if not identity["stock_code"] or not identity["url"]:
        raise ValueError("每条公告必须包含 stock_code 和 url")
    raw_query = item.get("query") or request.get("query") or ""
    query = str(raw_query).strip()
    if not query:
        raise ValueError("每条公告必须包含 query，或在请求顶层提供 query")
    max_results = int(item.get("max_results", request.get("max_results", 20)))
    if not 1 <= max_results <= 100:
        raise ValueError("max_results 必须在 1 到 100 之间")
    ocr_scanned = bool(item.get("ocr_scanned", request.get("ocr_scanned", True)))
    path, cache_hit = download_pdf(identity["stock_code"], identity["url"])
    result = search_pdf(
        path,
        identity["stock_code"],
        query=query,
        max_results=max_results,
        ocr_scanned=ocr_scanned,
    )
    return {**identity, "cache_hit": cache_hit, "path": str(path), **result}


def search_batch(request: dict[str, Any]) -> dict[str, Any]:
    return _map_announcements(
        "search_batch",
        request,
        "searches",
        lambda item: _search_item(item, request),
    )


def _read_item(item: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    from ashare_announcements_mcp.downloader import download_pdf
    from ashare_announcements_mcp.reader import read_pdf

    identity = _announcement_identity(item)
    if not identity["stock_code"] or not identity["url"]:
        raise ValueError("每条公告必须包含 stock_code 和 url")
    raw_start = item.get("start_page", request.get("start_page"))
    start_page = int(raw_start) if raw_start is not None else None
    raw_end_page = item.get("end_page", request.get("end_page"))
    end_page = int(raw_end_page) if raw_end_page is not None else None
    return_pages = int(item.get("return_pages", request.get("return_pages", 20)))
    ocr = bool(item.get("ocr", request.get("ocr", True)))
    path, cache_hit = download_pdf(identity["stock_code"], identity["url"])
    result = read_pdf(
        path,
        identity["stock_code"],
        start_page=start_page,
        end_page=end_page,
        return_pages=return_pages,
        ocr=ocr,
    )
    return {**identity, "cache_hit": cache_hit, "path": str(path), **result}


def read_batch(request: dict[str, Any]) -> dict[str, Any]:
    return _map_announcements(
        "read_batch",
        request,
        "readings",
        lambda item: _read_item(item, request),
    )


def _map_announcements(
    action: str,
    request: dict[str, Any],
    result_key: str,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    announcements = request.get("announcements")
    if not isinstance(announcements, list) or not announcements:
        raise ValueError("announcements 必须是非空数组")
    outputs: list[dict[str, Any]] = []
    for item in announcements:
        if not isinstance(item, dict):
            outputs.append({"ok": False, "error": "公告必须是对象"})
            continue
        identity = _announcement_identity(item)
        try:
            outputs.append({"ok": True, **handler(item)})
        except Exception as exc:
            outputs.append({"ok": False, **identity, "error": str(exc)})
    return _batch_response(action, outputs, result_key)


def query_a_share_interactions_batch(request: dict[str, Any]) -> dict[str, Any]:
    stock_codes = request.get("stock_codes")
    if not isinstance(stock_codes, list) or not stock_codes:
        raise ValueError("stock_codes 必须是非空数组")

    companies: list[dict[str, Any]] = []
    interactions: list[dict[str, Any]] = []
    for value in stock_codes:
        stock_code = str(value)
        try:
            result = query_a_share_interactions(
                stock_code,
                start_date=request.get("start_date"),
                end_date=request.get("end_date"),
                keyword=request.get("keyword"),
            )
            company = {"ok": True, **result}
            interactions.extend(result.get("results") or [])
        except Exception as exc:
            company = {"ok": False, "stock_code": stock_code, "error": str(exc), "results": []}
        companies.append(company)

    response = _batch_response("query_a_share_interactions_batch", companies, "companies")
    response["interactions"] = interactions
    response["matched"] = len(interactions)
    return response


def establish_company_action(request: dict[str, Any]) -> dict[str, Any]:
    """CLI 版建档：与 MCP 一致，action=check 用 keyword、action=establish 用 codes。"""
    action = request.get("action") or "check"
    if action == "check":
        keyword = request.get("keyword")
        if not keyword:
            raise ValueError("action=check 需要 keyword")
        return {"ok": True, "action": action, **check_company(str(keyword))}
    if action == "establish":
        codes = request.get("codes")
        if not isinstance(codes, list) or not codes:
            raise ValueError("action=establish 需要非空 codes 数组")
        return {"ok": True, "action": action, **establish_securities(codes)}
    raise ValueError(f"未知 action：{action}")


def query_transcripts_batch(request: dict[str, Any]) -> dict[str, Any]:
    from ashare_announcements_mcp.transcripts import query_transcripts

    stock_codes = request.get("stock_codes")
    if not isinstance(stock_codes, list) or not stock_codes:
        raise ValueError("stock_codes 必须是非空数组")

    companies: list[dict[str, Any]] = []
    transcripts: list[dict[str, Any]] = []
    period = request.get("period")
    force_refresh = bool(request.get("force_refresh", False))
    for value in stock_codes:
        stock_code = str(value)
        try:
            result = query_transcripts(stock_code, period=period, force_refresh=force_refresh)
            company = {"ok": True, **result}
            transcripts.extend(result.get("results") or [])
        except Exception as exc:
            company = {"ok": False, "stock_code": stock_code, "error": str(exc), "results": []}
        companies.append(company)

    response = _batch_response("query_transcripts_batch", companies, "companies")
    response["transcripts"] = transcripts
    response["matched"] = len(transcripts)
    return response


def search_transcripts_batch(request: dict[str, Any]) -> dict[str, Any]:
    from ashare_announcements_mcp.transcripts import search_transcripts

    stock_codes = request.get("stock_codes")
    if not isinstance(stock_codes, list) or not stock_codes:
        raise ValueError("stock_codes 必须是非空数组")
    query = request.get("query")
    if not query:
        raise ValueError("query 不能为空")

    companies: list[dict[str, Any]] = []
    transcripts: list[dict[str, Any]] = []
    for value in stock_codes:
        stock_code = str(value)
        try:
            result = search_transcripts(stock_code, query)
            company = {"ok": True, **result}
            transcripts.extend(result.get("results") or [])
        except Exception as exc:
            company = {"ok": False, "stock_code": stock_code, "error": str(exc), "results": []}
        companies.append(company)

    response = _batch_response("search_transcripts_batch", companies, "companies")
    response["transcripts"] = transcripts
    response["matched"] = len(transcripts)
    return response


ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "establish_company": establish_company_action,
    "query_batch": query_batch,
    "query_a_share_interactions_batch": query_a_share_interactions_batch,
    "search_batch": search_batch,
    "read_batch": read_batch,
    "query_transcripts_batch": query_transcripts_batch,
    "search_transcripts_batch": search_transcripts_batch,
}


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    tool = str(request.get("tool") or "")
    handler = ACTIONS.get(tool)
    if not handler:
        raise ValueError(f"未知 tool：{tool or '<empty>'}")
    return handler(request)


def main() -> None:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("请求必须是 JSON 对象")
        response = dispatch(request)
    except Exception as exc:
        response = {"ok": False, "status": "failed", "error": str(exc)}
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
