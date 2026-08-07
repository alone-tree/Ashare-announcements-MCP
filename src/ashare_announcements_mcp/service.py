"""公告档案同步和查询服务，供 MCP 与 CLI 共用。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ashare_announcements_mcp.api import (
    fetch_all_announcements,
    fetch_all_interactions,
    fetch_interaction_updates,
    fetch_updates,
)
from ashare_announcements_mcp.cache import (
    load_cache,
    load_companies,
    load_interactions,
    merge_items,
    save_cache,
    save_interactions,
)
from ashare_announcements_mcp import us_edgar

PAGE_SIZE = 50


def normalize_stock_code(value: str) -> str:
    """兼容 002271、SZ002271、002271.SZ、HK03308 等常见格式；不自动补零。

    本地公司使用非数字代码（如 LOCAL-YYYY）与美股代码（如 AAPL）：
    先在 companies.json 注册表精确匹配，命中则直接透传。
    """
    text = str(value).strip()
    if "LOCAL-" in text.upper():
        return text.upper()
    registry = load_companies()
    if text.upper() in registry["aliases"]:
        return text.upper()
    matches = re.findall(r"(?<!\d)(\d{5,6})(?!\d)", text.upper())
    if len(matches) != 1:
        raise ValueError("stock_code 必须包含一个五或六位证券代码，或已建档的 LOCAL-/美股代码")
    return matches[0]


def resolve_company(code: str) -> tuple[str, list[dict[str, Any]]]:
    """通过 companies.json 定位公司及关联证券；未建档时报错。"""
    registry = load_companies()
    company_key = registry["aliases"].get(code)
    if not company_key:
        raise ValueError(f"{code} 未建档，请先 check → establish → query")
    securities = registry["companies"].get(company_key, {}).get("securities") or []
    return company_key, securities


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


def sync_archive(
    code: str,
    ann_type: str = "A",
    inner_code: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """维护完整档案；查询层只消费本函数返回的缓存快照。

    ann_type 用于 A/H 公告接口；inner_code 用于港股按当前证券过滤旧公司记录。
    """
    cached = load_cache(code)
    items = cached.get("items") or []
    meta = cached.get("meta") or {}
    archive_was_complete = bool(items) and bool(meta.get("cache_complete"))
    try:
        if not archive_was_complete:
            fetched, fetch_meta = fetch_all_announcements(
                code, page_size=PAGE_SIZE, ann_type=ann_type, expected_inner_code=inner_code
            )
            if not fetch_meta.get("cache_complete"):
                raise RuntimeError("首次建档未能获取全部公告")
            items = merge_items([], fetched)
            new_count = len(items)
        else:
            known_codes = {
                str(item.get("code") or item.get("url") or "") for item in items
            }
            fetched, fetch_meta = fetch_updates(
                code,
                known_codes,
                page_size=PAGE_SIZE,
                ann_type=ann_type,
                expected_inner_code=inner_code,
            )
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


def sync_edgar_archive(
    code: str,
    cik: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """维护美股 EDGAR 提交档案；首次全量（含历史分片），之后增量拉 recent 前若干条。

    提交列表与东财公告统一为 items 格式：code=accession、title=表单+描述、
    display_time=提交日期、url=EDGAR 文档链接。
    """
    cached = load_cache(code)
    items = cached.get("items") or []
    meta = cached.get("meta") or {}
    archive_was_complete = bool(items) and bool(meta.get("cache_complete"))
    try:
        if not archive_was_complete:
            submissions = us_edgar.fetch_submissions(cik)
            fetched = [_format_us_filing(code, cik, item) for item in submissions["items"]]
            if not submissions.get("cache_complete"):
                raise RuntimeError("首次建档未能获取全部提交")
            items = fetched
            new_count = len(items)
            fetch_meta = {"total": len(fetched)}
        else:
            submissions = us_edgar.fetch_submissions(cik)
            known = {str(item.get("code") or "") for item in items}
            fresh = [
                _format_us_filing(code, cik, item)
                for item in submissions["items"]
                if str(item["accession"]) not in known
            ]
            new_count = len(fresh)
            if not fresh:
                return items, {
                    "update_check_ok": True,
                    "new_announcements": 0,
                    "update_error": None,
                }
            items = merge_items(items, fresh)
            fetch_meta = {"total": len(items)}
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
        raise RuntimeError(f"无法建立完整 EDGAR 档案：{exc}") from exc


def _format_us_filing(stock_code: str, cik: str, item: dict[str, Any]) -> dict[str, Any]:
    """EDGAR 提交记录 → 统一公告 item 格式。"""
    form = item.get("form", "")
    description = item.get("description") or ""
    title = f"{form} {description}".strip()
    return {
        "code": item.get("accession", ""),
        "url": us_edgar.filing_url(cik, item["accession"], item["document"]),
        "title": title,
        "display_time": f"{item.get('filing_date', '')} 00:00:00",
        "column_name": "SEC 提交",
        "short_name": stock_code,
        "form": form,
        "accession": item.get("accession", ""),
    }


def query_archive(
    stock_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
    market: str = "all",
) -> dict[str, Any]:
    """通过公司映射定位所有关联证券，同步后合并查询。

    market 允许 all/A/H，只作用于本地筛选；所有关联证券都执行增量更新。
    market=A 同时包含 B 股公告（B 股不单独筛选）；market=H 只筛港股。
    未建档时报错并提示 check → establish → query。
    """
    code = normalize_stock_code(stock_code)
    if market not in ("all", "A", "H"):
        raise ValueError("market 必须是 all、A 或 H")
    start = optional_date(start_date, "start_date")
    end = optional_date(end_date, "end_date")
    if start and end and start > end:
        raise ValueError("start_date 不能晚于 end_date")

    company_key, securities = resolve_company(code)

    merged: list[dict[str, Any]] = []
    security_status: list[dict[str, Any]] = []
    for security in securities:
        market_code = security["market"]
        try:
            if market_code == "LOCAL":
                # 本地公司（未上市等）：无网络来源，直接读缓存档案
                cached = load_cache(security["code"])
                items = cached.get("items") or []
                update_status = {"update_check_ok": True, "new_announcements": 0, "update_error": None}
            elif market_code == "US":
                # 美股：SEC EDGAR 提交档案
                items, update_status = sync_edgar_archive(
                    security["code"],
                    security.get("cik", ""),
                )
            else:
                items, update_status = sync_archive(
                    security["code"],
                    ann_type="H" if market_code == "H" else ("B" if market_code == "B" else "A"),
                    inner_code=security["inner_code"] if market_code in ("H", "B") else None,
                )
            security_status.append(
                {
                    "code": security["code"],
                    "market": market_code,
                    "name": security["name"],
                    "update": {
                        "success": True,
                        "total": len(items),
                        "new": update_status.get("new_announcements", 0),
                        "error": None,
                    },
                }
            )
            for item in items:
                item["market"] = market_code
            merged.extend(items)
        except Exception as exc:
            security_status.append(
                {
                    "code": security["code"],
                    "market": market_code,
                    "name": security["name"],
                    "update": {
                        "success": False,
                        "total": 0,
                        "new": 0,
                        "error": str(exc),
                    },
                }
            )

    merged.sort(key=lambda item: str(item.get("display_time") or ""), reverse=True)
    if market == "A":
        merged = [item for item in merged if item.get("market") in ("A", "B")]
    elif market == "H":
        merged = [item for item in merged if item.get("market") == "H"]

    filtered = []
    for item in merged:
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
        "company_key": company_key,
        "securities": security_status,
        "total_announcements": len(merged),
        "matched": len(filtered),
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


def _resolve_interaction_target(stock_code: str) -> tuple[str | None, str, list[dict[str, Any]]]:
    """通过公司映射定位互动问答对应的 A 股代码；纯港股/B 股/本地公司返回 None。"""
    code = normalize_stock_code(stock_code)
    company_key, securities = resolve_company(code)
    for security in securities:
        if security["market"] == "A":
            return security["code"], company_key, securities
    return None, company_key, securities


def sync_interactions(code: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """维护互动问答完整档案；首次全量，之后从最新页增量更新。"""
    cached = load_interactions(code)
    items = cached.get("items") or []
    meta = cached.get("meta") or {}
    archive_was_complete = bool(items) and bool(meta.get("cache_complete"))
    try:
        if not archive_was_complete:
            fetched, fetch_meta = fetch_all_interactions(code)
            if not fetch_meta.get("cache_complete"):
                raise RuntimeError("首次建档未能获取全部互动问答")
            items = fetched
            new_count = len(items)
        else:
            known_ids = {str(item.get("post_id") or "") for item in items}
            fetched, fetch_meta = fetch_interaction_updates(code, known_ids)
            new_count = len(fetched)
            if not fetched:
                return items, {
                    "update_check_ok": True,
                    "new_interactions": 0,
                    "update_error": None,
                }
            items = fetched + items
        meta = {**meta, **fetch_meta, "cache_complete": True}
        save_interactions(code, items, meta)
        return items, {
            "update_check_ok": True,
            "new_interactions": new_count,
            "update_error": None,
        }
    except Exception as exc:
        if archive_was_complete:
            return items, {
                "update_check_ok": False,
                "new_interactions": 0,
                "update_error": str(exc),
            }
        raise RuntimeError(f"无法建立完整互动问答档案：{exc}") from exc


def query_interactions(
    stock_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    """查询互动问答；纯港股返回不适用。日期按回答时间筛选。"""
    start = optional_date(start_date, "start_date")
    end = optional_date(end_date, "end_date")
    if start and end and start > end:
        raise ValueError("start_date 不能晚于 end_date")

    code, company_key, securities = _resolve_interaction_target(stock_code)
    if code is None:
        return {
            "stock_code": normalize_stock_code(stock_code),
            "company_key": company_key,
            "stock_name": securities[0].get("name", "") if securities else "",
            "applicable": False,
            "reason": "该公司无互动问答（纯港股/B 股/本地公司），不适用",
            "total_interactions": 0,
            "matched": 0,
            "results": [],
        }
    items, update_status = sync_interactions(code)
    filtered = []
    for item in items:
        item_date = str(item.get("post_display_time") or "")[:10]
        if start and item_date and item_date < start.isoformat():
            continue
        if end and item_date and item_date > end.isoformat():
            continue
        if not interaction_keyword_matches(item, keyword):
            continue
        filtered.append(item)

    return {
        "stock_code": code,
        "company_key": company_key,
        "stock_name": items[0].get("stockbar_name", "") if items else "",
        "applicable": True,
        "total_interactions": len(items),
        "matched": len(filtered),
        **update_status,
        "results": filtered,
    }


def interaction_keyword_matches(item: dict[str, Any], keyword: str | None) -> bool:
    """空格表示 OR；显式写 AND 时要求所有关键词都命中。问题和回答都检索。"""
    if not keyword:
        return True
    haystack = (
        f"{item.get('ask_question', '')} {item.get('ask_answer', '')}".lower()
    )
    text = keyword.strip().lower()
    if re.search(r"\s+and\s+", text, flags=re.IGNORECASE):
        terms = [term.strip() for term in re.split(r"\s+and\s+", text, flags=re.IGNORECASE)]
        return all(term in haystack for term in terms if term)
    terms = [term for term in text.split() if term]
    return any(term in haystack for term in terms)
