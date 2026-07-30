"""供确定性批处理脚本调用的公告 JSON CLI。

从 stdin 读取一个 JSON 请求，stdout 只输出一个 JSON 响应。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_announcements_mcp.service import query_archive


def _status(items: list[dict[str, Any]]) -> str:
    succeeded = sum(bool(item.get("ok")) for item in items)
    if succeeded == len(items):
        return "success"
    return "partial_success" if succeeded else "failed"


def _batch_response(action: str, items: list[dict[str, Any]], result_key: str) -> dict[str, Any]:
    succeeded = sum(bool(item.get("ok")) for item in items)
    return {
        "ok": succeeded == len(items),
        "action": action,
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


def _inspect_item(item: dict[str, Any]) -> dict[str, Any]:
    from ashare_announcements_mcp.downloader import download_pdf
    from ashare_announcements_mcp.reader import inspect_pdf

    identity = _announcement_identity(item)
    if not identity["stock_code"] or not identity["url"]:
        raise ValueError("每条公告必须包含 stock_code 和 url")
    path, cache_hit = download_pdf(identity["stock_code"], identity["url"])
    return {**identity, "cache_hit": cache_hit, "path": str(path), **inspect_pdf(path, identity["stock_code"])}


def inspect_batch(request: dict[str, Any]) -> dict[str, Any]:
    return _map_announcements("inspect_batch", request, "inspections", _inspect_item)


def _read_item(item: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    from ashare_announcements_mcp.downloader import download_pdf
    from ashare_announcements_mcp.reader import read_pdf

    identity = _announcement_identity(item)
    if not identity["stock_code"] or not identity["url"]:
        raise ValueError("每条公告必须包含 stock_code 和 url")
    start_page = int(item.get("start_page", request.get("start_page", 1)))
    raw_end_page = item.get("end_page", request.get("end_page"))
    end_page = int(raw_end_page) if raw_end_page is not None else None
    max_chars = int(item.get("max_chars", request.get("max_chars", 20_000)))
    ocr = bool(item.get("ocr", request.get("ocr", False)))
    path, cache_hit = download_pdf(identity["stock_code"], identity["url"])
    result = read_pdf(
        path,
        identity["stock_code"],
        start_page=start_page,
        end_page=end_page,
        max_chars=max_chars,
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


ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "query_batch": query_batch,
    "inspect_batch": inspect_batch,
    "read_batch": read_batch,
}


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    action = str(request.get("action") or "")
    handler = ACTIONS.get(action)
    if not handler:
        raise ValueError(f"未知 action：{action or '<empty>'}")
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
