# -*- coding: utf-8 -*-
"""证券代码搜索：按名称或代码找到标的，返回可直接用于CLI取数的代码。

三个通道：
  股票  东方财富搜索接口，清洗成iFinD代码（港股四位、正股优先）
  指数  本地「指数总表.csv」+ 常用表独有条目
  外汇  本地「汇率代码表.csv」

规则：12741个指数全可搜，精确匹配排前，常用标记次之；每页最多10行，offset翻页。
"""
from __future__ import annotations

import csv
from pathlib import Path

LIB = Path(__file__).resolve().parent / "formula_library"
PAGE_SIZE = 10

# 东财搜索（与 market_data_mcp 保持零 import 依赖，接口与规则在此自带）
_EM_URL = "https://searchapi.eastmoney.com/api/suggest/get"
_EM_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
_STOCK_SUFFIX = {
    "沪A": "SH", "深A": "SZ", "京A": "BJ", "科创板": "SH", "创业板": "SZ", "沪B": "SH", "深B": "SZ",
}


def _read_csv(name: str) -> list[dict[str, str]]:
    with (LIB / name).open(encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _ifind_stock_code(code: str, name: str, sec_type: str, type_us: str) -> str | None:
    """东财股票候选 → iFinD代码；非正股权证等返回None。"""
    suffix = _STOCK_SUFFIX.get(sec_type)
    if sec_type == "港股":
        if type_us not in ("1", "3"):  # 排除权证等衍生品
            return None
        if name.endswith("-R"):  # 人民币柜台，非正股
            return None
        return (code.lstrip("0") or "0").zfill(4) + ".HK"
    if sec_type == "美股":
        if type_us in ("5", "6"):  # 票据等
            return None
        return code + ".US"
    if not suffix:
        return None
    return code + "." + suffix


def _search_stock(keyword: str) -> tuple[list[dict], list[dict]]:
    import requests

    with requests.Session() as s:
        s.trust_env = False
        resp = s.get(_EM_URL, params={"input": keyword, "type": "14", "count": "50", "token": _EM_TOKEN}, timeout=20)
        resp.raise_for_status()
        table = resp.json()["QuotationCodeTable"]
    if int(table.get("Status", -1)) != 0:
        raise RuntimeError(f"东财搜索失败：{table.get('Message')}")
    matches, excluded = [], []
    for item in table.get("Data") or []:
        c = (item.get("Code") or "").strip()
        name = (item.get("Name") or "").strip()
        sec_type = (item.get("SecurityTypeName") or "").strip()
        type_us = str(item.get("TypeUS") or "")
        if sec_type not in ("港股", "美股", "沪A", "深A", "京A", "科创板", "创业板", "沪B", "深B"):
            continue  # 指数、基金、板块等不进股票通道
        code = _ifind_stock_code(c, name, sec_type, type_us)
        row = {"name": name, "ifind_code": code, "kind": "股票", "market": sec_type,
               "type": "正股", "source_code": c, "type_us": type_us}
        if code:
            matches.append(row)
        else:
            row["type"] = "非正股" if sec_type in ("港股", "美股") else sec_type
            excluded.append(row)
    # 名称完全相等排最前，其次名称包含关键词
    matches.sort(key=lambda r: (0 if r["name"] == keyword else (1 if keyword in r["name"] else 2), r["ifind_code"]))
    return matches, excluded


def _index_records() -> list[dict]:
    """指数总表全部行 + 常用表独有条目，带常用标记与匹配所需字段。"""
    rows = _read_csv("指数总表.csv")
    total_codes = {r["证券代码"].strip() for r in rows}
    for r in rows:
        r["常用"] = r.get("常用", "")
    for r in _read_csv("常用指数基本信息.csv"):
        code = r["证券代码"].strip()
        if code in total_codes:
            continue
        # 常用表独有（商品/债券指数），整行补进去，字段对齐总表
        r["所在类型"] = ""
        r["常用"] = "1"
        for col in ("指数全称", "指数简介", "加权方式", "指数类别", "指数基期", "指数基点",
                    "发布机构", "交易币种", "所属国家", "启用日期", "摘牌日期", "最早成份日期", "最早交易日期"):
            r.setdefault(col, "")
        rows.append(r)
    return rows


def _rank_index(row: dict, kw: str) -> int | None:
    code = (row.get("证券代码") or "").strip()
    bare = code.split(".")[0]
    name = (row.get("证券名称") or "").strip()
    full = (row.get("指数全称") or "").strip()
    if code == kw or bare == kw:
        return 1
    if name == kw:
        return 2
    if full == kw:
        return 3
    if kw in name:
        return 4
    if kw in full:
        return 5
    return None


def _search_index(keyword: str) -> list[dict]:
    hit = []
    for row in _index_records():
        rank = _rank_index(row, keyword)
        if rank is not None:
            hit.append((rank, 0 if row.get("常用") == "1" else 1, row))
    hit.sort(key=lambda x: (x[0], x[1], x[2]["证券代码"]))
    return [r for _, _, r in hit]


def _search_forex(keyword: str) -> list[dict]:
    hit = []
    for row in _read_csv("汇率代码表.csv"):
        code = row.get("证券代码", "").strip()
        name = row.get("证券名称", "").strip()
        if code == keyword:
            rank = 1
        elif name == keyword:
            rank = 2
        elif keyword in code or keyword in name:
            rank = 3
        else:
            continue
        hit.append((rank, row))
    hit.sort(key=lambda x: (x[0], x[1]["证券代码"]))
    return [r for _, r in hit]


def search(keyword: str, offset: int = 0, limit: int = PAGE_SIZE, kind: str = "") -> dict:
    """统一搜索入口。kind 可限定：股票/指数/外汇；空则全部。"""
    kw = (keyword or "").strip()
    if not kw:
        return {"ok": False, "error": "keyword不能为空"}
    offset = max(0, int(offset))
    limit = max(1, min(PAGE_SIZE, int(limit)))

    matches: list[dict] = []
    excluded: list[dict] = []
    if kind in ("", "股票"):
        m, ex = _search_stock(kw)
        matches.extend(m)
        excluded.extend(ex)
    if kind in ("", "指数"):
        for row in _search_index(kw):
            matches.append({"name": row["证券名称"], "ifind_code": row["证券代码"],
                            "kind": "指数", "row": row})
    if kind in ("", "外汇"):
        for row in _search_forex(kw):
            matches.append({"name": row["证券名称"], "ifind_code": row["证券代码"],
                            "kind": "外汇", "row": row})

    total = len(matches)
    page = matches[offset:offset + limit]
    return {
        "ok": True,
        "keyword": kw,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
        "note": "ifind_code可直接传给CLI取数；名称相近请核对是同一标的。指数/外汇命中时row返回该行全部字段。",
        "matches": page,
        "excluded": excluded[:PAGE_SIZE],
    }
