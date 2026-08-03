"""东方财富上市公司证券查询。"""

from __future__ import annotations

from typing import Any

import requests

from ashare_announcements_mcp.api import HEADERS


SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"


def _search(keyword: str) -> tuple[list[dict[str, Any]], int]:
    response = requests.get(
        SEARCH_URL,
        params={
            "input": keyword,
            "type": "14",
            "token": SEARCH_TOKEN,
            "count": "20",
        },
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    table = (response.json() or {}).get("QuotationCodeTable") or {}
    if int(table.get("Status") or 0) != 0:
        raise RuntimeError(f"东方财富证券搜索失败：{table.get('Message') or '未知错误'}")
    return list(table.get("Data") or []), int(table.get("TotalCount") or 0)


def _format_security(item: dict[str, Any]) -> dict[str, str]:
    """按东方财富原始字段整理，不补充推测字段。"""
    return {
        "code": str(item.get("Code") or ""),
        "name": str(item.get("Name") or ""),
        "pinyin": str(item.get("PinYin") or ""),
        "id": str(item.get("ID") or ""),
        "jys": str(item.get("JYS") or ""),
        "classify": str(item.get("Classify") or ""),
        "market_type": str(item.get("MarketType") or ""),
        "security_type_name": str(item.get("SecurityTypeName") or ""),
        "security_type": str(item.get("SecurityType") or ""),
        "mkt_num": str(item.get("MktNum") or ""),
        "type_us": str(item.get("TypeUS") or ""),
        "quote_id": str(item.get("QuoteID") or ""),
        "unified_code": str(item.get("UnifiedCode") or ""),
        "inner_code": str(item.get("InnerCode") or ""),
    }


def check_company(keyword: str) -> dict[str, Any]:
    """查询关键词，忠实返回东方财富搜索接口的候选，不过滤、不归组。"""
    text = str(keyword).strip()
    if not text:
        raise ValueError("keyword 不能为空")

    raw_candidates, source_total = _search(text)
    candidates = [_format_security(item) for item in raw_candidates]
    result: dict[str, Any] = {
        "keyword": text,
        "source_total_count": source_total,
        "returned_count": len(candidates),
        "candidates": candidates,
    }
    if source_total > len(candidates):
        result["hint"] = "命中数超过返回上限，请使用更精确的关键词重新查询"
    return result
