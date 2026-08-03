"""东方财富公告接口。"""

from __future__ import annotations

import json
import random
import time
from typing import Any

import requests


API_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
PDF_URL = "https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://data.eastmoney.com/notices/",
}


def _normalize_time(value: Any) -> str:
    """把接口中的时间戳或时间字符串统一为可排序格式。"""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) or str(value).isdigit():
        timestamp = int(value)
        if timestamp > 1_000_000_000_000:
            timestamp //= 1000
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    text = str(value).strip()
    if text.count(":") == 3 and text.rsplit(":", 1)[1].isdigit():
        text = text.rsplit(":", 1)[0]
    if "." in text and text.rsplit(".", 1)[1].isdigit():
        text = text.rsplit(".", 1)[0]
    return text


def _format_item(
    stock_code: str, item: dict[str, Any], expected_inner_code: str | None = None
) -> dict[str, str]:
    """只保留 AI 查询和后续读取需要的字段。"""
    art_code = str(item.get("art_code") or "")
    columns = item.get("columns") or []
    codes = item.get("codes") or []
    short_name = ""
    if codes:
        if expected_inner_code:
            matched = [
                code
                for code in codes
                if str(code.get("inner_code") or "") == expected_inner_code
            ]
            if matched:
                short_name = str(matched[0].get("short_name") or "")
        if not short_name:
            short_name = str(codes[0].get("short_name") or "")
    return {
        "short_name": short_name,
        "stock_code": stock_code,
        "display_time": _normalize_time(
            item.get("display_time") or item.get("eiTime") or item.get("notice_date")
        ),
        "column_name": ", ".join(
            str(column.get("column_name") or "") for column in columns if column
        ),
        "title": str(item.get("title") or item.get("title_ch") or ""),
        "url": PDF_URL.format(art_code=art_code) if art_code else "",
        "code": art_code,
    }


def fetch_page(
    stock_code: str,
    page: int,
    page_size: int = 50,
    ann_type: str = "A",
    expected_inner_code: str | None = None,
) -> tuple[list[dict[str, str]], int]:
    """抓取一页公告，并返回公告列表和接口报告的总条数。

    expected_inner_code 用于港股：公告列表可能混入旧公司记录（代码复用），
    只保留 codes 中包含该 InnerCode 的公告。total_hits 始终是接口原始总数。
    """
    callback = f"jQuery{random.randint(10**18, 10**19 - 1)}_{int(time.time() * 1000)}"
    params = {
        "cb": callback,
        "sr": "-1",
        "page_size": str(page_size),
        "page_index": str(page),
        "ann_type": ann_type,
        "client_source": "web",
        "stock_list": stock_code,
        "f_node": "0",
        "s_node": "0",
    }
    response = requests.get(API_URL, params=params, headers=HEADERS, timeout=20)
    response.raise_for_status()
    text = response.text.strip()
    prefix = f"{callback}("
    if not text.startswith(prefix) or not text.endswith(")"):
        raise RuntimeError("东方财富返回了无法识别的 JSONP 数据")
    payload = json.loads(text[len(prefix) : -1])
    if not payload.get("success"):
        raise RuntimeError(f"东方财富接口返回失败：{payload.get('error') or '未知错误'}")
    data = payload.get("data") or {}
    items = []
    for item in data.get("list") or []:
        if expected_inner_code:
            codes = item.get("codes") or []
            if not any(
                str(code.get("inner_code") or "") == expected_inner_code for code in codes
            ):
                continue
        items.append(_format_item(stock_code, item, expected_inner_code))
    return items, int(data.get("total_hits") or len(items))


def fetch_all_announcements(
    stock_code: str,
    page_size: int = 50,
    ann_type: str = "A",
    expected_inner_code: str | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """首次建档时翻完全部公告页。

    港股带 expected_inner_code 时，total_hits 包含旧公司记录，不能用
    len(all_items) >= source_total 判断完成；改为连续 3 页过滤后为空即停。
    """
    all_items: list[dict[str, str]] = []
    source_total = 0
    fetched_pages = 0
    empty_pages = 0
    for page in range(1, 501):
        items, source_total = fetch_page(
            stock_code, page, page_size, ann_type, expected_inner_code
        )
        fetched_pages = page
        if not items:
            empty_pages += 1
            if empty_pages >= 3 or not expected_inner_code:
                break
            time.sleep(0.12)
            continue
        empty_pages = 0
        all_items.extend(items)
        if not expected_inner_code and len(all_items) >= source_total:
            break
        time.sleep(0.12)
    complete = source_total == 0 or len(all_items) >= source_total
    if expected_inner_code:
        complete = bool(all_items) and (empty_pages >= 3 or fetched_pages >= 500)
    return all_items, {
        "fetched_pages": fetched_pages,
        "source_total": source_total,
        "cache_complete": complete,
    }


def fetch_updates(
    stock_code: str,
    known_codes: set[str],
    page_size: int = 50,
    ann_type: str = "A",
    expected_inner_code: str | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """从最新页向后读取，遇到缓存中的公告后停止。"""
    new_items: list[dict[str, str]] = []
    source_total = 0
    fetched_pages = 0
    empty_pages = 0
    for page in range(1, 501):
        items, source_total = fetch_page(
            stock_code, page, page_size, ann_type, expected_inner_code
        )
        fetched_pages = page
        if not items:
            empty_pages += 1
            if empty_pages >= 3:
                break
            time.sleep(0.12)
            continue
        empty_pages = 0
        for item in items:
            identity = str(item.get("code") or item.get("url") or "")
            if identity in known_codes:
                return new_items, {
                    "fetched_pages": fetched_pages,
                    "source_total": source_total,
                    "cache_complete": True,
                }
            new_items.append(item)
        if not expected_inner_code and len(new_items) >= source_total:
            break
        time.sleep(0.12)
    return new_items, {
        "fetched_pages": fetched_pages,
        "source_total": source_total,
        "cache_complete": len(new_items) >= source_total,
    }
