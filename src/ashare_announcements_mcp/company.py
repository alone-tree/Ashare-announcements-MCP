"""东方财富上市公司证券查询。"""

from __future__ import annotations

from typing import Any

import requests

from ashare_announcements_mcp.api import HEADERS
from ashare_announcements_mcp.cache import load_companies, save_companies
from ashare_announcements_mcp.service import sync_archive, sync_interactions


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


def _resolve_security(code: str) -> dict[str, Any]:
    """精确查询单个证券代码，返回建档所需的普通 A/H 公司证券信息。"""
    text = str(code).strip()
    if not text:
        raise ValueError("代码不能为空")
    if not text.isdigit():
        raise ValueError(f"代码必须是数字：{text}")
    candidates, _ = _search(text)
    matched = [item for item in candidates if str(item.get("Code") or "") == text]
    if not matched:
        raise ValueError(f"无法精确查询到证券：{text}")
    item = matched[0]
    classify = str(item.get("Classify") or "")
    type_us = str(item.get("TypeUS") or "")
    security_type_name = str(item.get("SecurityTypeName") or "")
    if classify == "AStock" or security_type_name in ("沪A", "深A", "科创板", "京A"):
        market = "A"
    elif classify == "HK" and type_us == "3":
        market = "H"
    elif security_type_name in ("沪B", "深B"):
        market = "B"
    else:
        raise ValueError(
            f"{text} 不是普通 A/B/H 公司证券（Classify={classify} TypeUS={type_us}），拒绝建档"
        )
    inner_code = str(item.get("InnerCode") or "")
    if market in ("H", "B") and not inner_code:
        raise ValueError(f"{text} 缺少{('港股' if market == 'H' else 'B股')} InnerCode，拒绝建档")
    return {
        "code": text,
        "name": str(item.get("Name") or ""),
        "market": market,
        "classify": classify,
        "inner_code": inner_code,
    }


def establish_company(codes: list[str]) -> dict[str, Any]:
    """按明确代码数组建档，保存公司映射并同步各证券公告列表。"""
    if not isinstance(codes, list) or not codes:
        raise ValueError("codes 必须是非空数组")
    if len(codes) > 2:
        raise ValueError("codes 最多接受两个代码（如一个 A 股加一个 H 股/B 股）")

    securities = [_resolve_security(code) for code in codes]
    markets = {security["market"] for security in securities}
    if len(markets) != len(securities):
        raise ValueError("codes 不能包含两个同市场代码")

    registry = load_companies()
    companies = registry["companies"]
    aliases = registry["aliases"]

    owned_keys = {
        security["code"]: aliases.get(security["code"]) for security in securities
    }
    existing_keys = {key for key in owned_keys.values() if key}
    if len(existing_keys) > 1:
        raise RuntimeError("所选代码分属不同公司，拒绝合并建档")
    company_key = existing_keys.pop() if existing_keys else None

    if company_key:
        existing = companies[company_key]["securities"]
        existing_markets = {security["market"] for security in existing}
        for security in securities:
            if security["market"] in existing_markets and not any(
                item["code"] == security["code"] for item in existing
            ):
                raise RuntimeError(
                    f"{security['code']} 与公司 {company_key} 现有 {security['market']} 股代码冲突"
                )
    else:
        company_key = next(
            (security["code"] for security in securities if security["market"] == "A"),
            securities[0]["code"],
        )
        companies[company_key] = {"securities": []}

    company = companies[company_key]
    for security in securities:
        if not any(item["code"] == security["code"] for item in company["securities"]):
            company["securities"].append(
                {
                    "code": security["code"],
                    "market": security["market"],
                    "name": security["name"],
                    "classify": security["classify"],
                    "inner_code": security["inner_code"],
                }
            )
        aliases[security["code"]] = company_key
    save_companies({"companies": companies, "aliases": aliases})

    results = []
    for security in securities:
        try:
            items, status = sync_archive(
                security["code"],
                ann_type="H" if security["market"] == "H" else ("B" if security["market"] == "B" else "A"),
                inner_code=security["inner_code"] if security["market"] in ("H", "B") else None,
            )
            results.append(
                {
                    "code": security["code"],
                    "market": security["market"],
                    "name": security["name"],
                    "success": True,
                    "total": len(items),
                    "new": status.get("new_announcements", 0),
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "code": security["code"],
                    "market": security["market"],
                    "name": security["name"],
                    "success": False,
                    "total": 0,
                    "new": 0,
                    "error": str(exc),
                }
            )

    interactions_status = {"applicable": False, "reason": "该公司无互动问答（纯港股/B 股），不适用"}
    a_security = next((s for s in securities if s["market"] == "A"), None)
    if a_security:
        try:
            items, status = sync_interactions(a_security["code"])
            interactions_status = {
                "applicable": True,
                "success": True,
                "total": len(items),
                "new": status.get("new_interactions", 0),
                "error": None,
            }
        except Exception as exc:
            interactions_status = {
                "applicable": True,
                "success": False,
                "total": 0,
                "new": 0,
                "error": str(exc),
            }

    return {"company_key": company_key, "securities": results, "interactions": interactions_status}
