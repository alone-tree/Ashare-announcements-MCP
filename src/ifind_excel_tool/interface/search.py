# -*- coding: utf-8 -*-
"""第四块 检索：按关键词找科目，返回用法。

只做匹配与排序，不取数、不判断业务含义。候选条目来自第二块的 definitions，
所以新增一个科目不用改这里的代码。

别名优先：用户给科目起过短名（如「扣非净利润」）的，展示与检索都用短名，
没有别名才退回 iFinD 原名。
"""
from __future__ import annotations

from ifind_excel_tool.indicators import definitions

MATCH_EXACT_NAME = 1
MATCH_EXACT_ALIAS = 2
MATCH_NAME_CONTAINS = 3
MATCH_ALIAS_CONTAINS = 4
MATCH_INDICATOR_CONTAINS = 5
MATCH_DESCRIPTION = 6

MATCH_LABEL = {
    MATCH_EXACT_NAME: "名称完全匹配",
    MATCH_EXACT_ALIAS: "别名完全匹配",
    MATCH_NAME_CONTAINS: "名称包含",
    MATCH_ALIAS_CONTAINS: "别名包含",
    MATCH_INDICATOR_CONTAINS: "指标码包含",
    MATCH_DESCRIPTION: "说明文字命中",
}

# 展示顺序：衍生科目与组合优先（用户常点的），其次原始公式，最后特殊能力
KIND_ORDER = {"derived": 0, "package": 1, "formula": 2, "batch": 3, "special": 4}


def display_name(entry: dict) -> str:
    """展示用名称：有中文别名时用别名（用户自定义的短名优先），否则用原名。

    英文别名（如 gross_margin）只用于检索匹配，不作为展示名——给研究对象看的
    应该是中文。
    """
    for alias in entry.get("aliases") or []:
        if any("\u4e00" <= ch <= "\u9fff" for ch in alias):
            return alias
    return entry["name"]


def _suffix_hit(keyword: str, name: str, min_chars: int = 3) -> bool:
    """关键词去掉前缀后仍能在名称里找到，算命中。

    用户会说「沪深300成分股」，库里叫「指数成分股」：整串搜不到，但剥掉
    「沪深300」后「成分股」在。只剥前缀不剥后缀，且剩余至少3字，避免短词误中。
    """
    for start in range(1, len(keyword) - min_chars + 1):
        if keyword[start:] in name:
            return True
    return False


def _rank(entry: dict, keyword: str) -> int | None:
    kw = keyword.strip()
    name = entry.get("name") or ""
    aliases = entry.get("aliases") or []
    indicator = entry.get("indicator") or ""
    if kw == name:
        return MATCH_EXACT_NAME
    if kw in aliases:
        return MATCH_EXACT_ALIAS
    if kw in name:
        return MATCH_NAME_CONTAINS
    if any(kw in a for a in aliases):
        return MATCH_ALIAS_CONTAINS
    if kw in indicator:
        return MATCH_INDICATOR_CONTAINS
    if _suffix_hit(kw, name) or any(_suffix_hit(kw, a) for a in aliases):
        return MATCH_NAME_CONTAINS
    haystack = entry.get("description") or ""
    if kw in haystack:
        return MATCH_DESCRIPTION
    return None


def search(keyword: str, limit: int = 10, offset: int = 0, kind: str = "") -> dict:
    """在全部科目里搜索，返回带用法的条目。kind 可限定类型，不传搜全部。"""
    kw = (keyword or "").strip()
    if not kw:
        return {"ok": False, "error": "keyword 不能为空"}
    offset = max(0, int(offset))
    limit = max(1, min(50, int(limit)))
    ranked = []
    for order, entry in enumerate(definitions.build_index()):
        if kind and entry["kind"] != kind:
            continue
        rank = _rank(entry, kw)
        if rank is None:
            continue
        ranked.append((rank, KIND_ORDER.get(entry["kind"], 9), order, entry))
    ranked.sort(key=lambda x: (x[0], x[1], x[2]))
    hits = []
    for rank, _, _, entry in ranked:
        item = dict(entry)
        item["display_name"] = display_name(entry)
        item["match"] = MATCH_LABEL[rank]
        hits.append(item)
    return {"ok": True, "keyword": kw, "total": len(hits),
            "offset": offset, "limit": limit,
            "has_more": offset + limit < len(hits),
            "hits": hits[offset:offset + limit]}
