# -*- coding: utf-8 -*-
"""统一指标索引：把工具能拿到的全部业务数据收进同一个搜索范围。

设计边界见 docs/iFinD-CLI统一指标库与搜索框架方案-2026-11-25.md：
- 搜索按「业务数据」算，不按存储形态算；公式型、场景型、报表函数型、派生型、
  指标组、特殊能力都在同一处能搜到。
- 每条命中都带用法：用哪条命令、传什么参数、返回大概什么形状。
- 本模块只做索引与检索，不执行取数（取数见 indicators.py）。

索引来源四类：
  verified-formulas.jsonl   单格公式（原始型）
  scenes/*.json             固定场景与多候选字段（原始型/表函数型）
  derived-indicators.jsonl  自定义派生指标
  indicator-groups.jsonl    指标组
"""
from __future__ import annotations

import json
from pathlib import Path

LIBRARY = Path(__file__).resolve().parent / "formula_library"
SCENES = Path(__file__).resolve().parent / "scenes"

# 匹配强度：数字越小越靠前
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

# 返回示例：只写形状与单位，不编造具体数值
RETURNS = {
    "excel": "单值。raw 为数值或文本，单位见 unit；另带 __unit 标注。",
    "select": "单值。从多个候选里取较大值，值相同不留痕，不同时带 __choices 说明选了哪条。",
    "derived": "单值。已按定义算好并保留指定小数位，可直接用于研究，不需再加工。",
    "group": "一组指标。每条成员一条记录，键为成员名。",
    "scene": "一张表的全部字段。records 为逐行记录，大结果只回前20行预览，全量在 export.path。",
    "table": "报表函数整表。records 为逐行记录，列名见 fields。",
    "special": "单值。非取数能力的查询结果。",
}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _load_formulas() -> list[dict]:
    return _read_jsonl(LIBRARY / "verified-formulas.jsonl")


def _load_derived() -> list[dict]:
    return _read_jsonl(LIBRARY / "derived-indicators.jsonl")


def _load_groups() -> list[dict]:
    return _read_jsonl(LIBRARY / "indicator-groups.jsonl")


def _scene_specs() -> list[dict]:
    specs = []
    for path in sorted(SCENES.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        spec.setdefault("name", path.stem)
        specs.append(spec)
    return specs


def _call(indicator: str, *, extra: dict | None = None) -> dict:
    """统一的调用模板。参数留待调用方按自己代码与期间替换。"""
    payload = {"cmd": "get", "indicator": indicator, "code": "<证券代码>",
               "report_date": "<报告期或交易日>"}
    payload.update(extra or {})
    return payload


def build_index() -> list[dict]:
    """把所有能力展开成同一形态的条目。每条都能直接拿来用。"""
    entries: list[dict] = []
    seen_derived = set()
    derived = _load_derived()
    groups = _load_groups()
    for item in derived:
        seen_derived.add(item["name"])

    # 1 自定义派生指标（优先展示，同名时覆盖原始定义）
    for item in derived:
        entries.append({
            "name": item["name"],
            "kind": "derived",
            "aliases": item.get("aliases") or [],
            "indicator": item.get("indicator") or item["name"],
            "description": item.get("description", ""),
            "unit": item.get("unit", ""),
            "decimals": item.get("decimals"),
            "depends_on": [d["label"] for d in item.get("deps") or []],
            "call": _call(item["name"]),
            "returns": RETURNS["derived"],
        })

    # 2 指标组
    for item in groups:
        entries.append({
            "name": item["name"],
            "kind": "group",
            "aliases": item.get("aliases") or [],
            "indicator": item["name"],
            "description": item.get("description", ""),
            "members": item["members"],
            "call": _call(item["name"]),
            "returns": RETURNS["group"],
        })

    # 3 多候选字段（藏在场景里的，作为独立指标暴露出来）
    for spec in _scene_specs():
        if spec.get("kind") == "table":
            continue
        for field in spec.get("fields") or []:
            if not field.get("candidates"):
                continue
            if field["label"] in seen_derived:
                continue
            entries.append({
                "name": field["label"],
                "kind": "select",
                "aliases": field.get("aliases") or [],
                "indicator": field["label"],
                "description": f"多候选取较大值。候选：{'、'.join(field['candidates'])}",
                "unit": field.get("unit", ""),
                "candidates": field["candidates"],
                "pick": field.get("pick") or "max",
                "call": _call(field["label"]),
                "returns": RETURNS["select"],
            })

    # 4 单格公式指标（原始型）。同名派生指标存在时不重复占位。
    for record in _load_formulas():
        name = (record.get("name") or "").strip()
        if not name:
            continue
        entries.append({
            "name": name,
            "kind": "excel",
            "aliases": record.get("aliases") or [],
            "indicator": record["indicator"],
            "description": record.get("definition") or "",
            "unit": record.get("unit", ""),
            "path": record.get("path", ""),
            "reading_mode": record.get("reading_mode") or "matrix",
            "params_needed": [p["name"] for p in record.get("parameters") or []
                              if p.get("default") is None and p["name"] not in ("thsCode", "Date")],
            "call": _call(record["indicator"]),
            "returns": RETURNS["excel"],
        })

    # 5 固定场景（矩阵场景与表函数场景）
    for spec in _scene_specs():
        kind = "table" if spec.get("kind") == "table" else "scene"
        entry = {
            "name": spec["name"],
            "kind": kind,
            "aliases": [],
            "indicator": spec["name"],
            "description": spec.get("description", ""),
            "call": {"cmd": "fetch_scene", "scene": spec["name"], "code": "<证券代码>"},
            "returns": RETURNS[kind],
        }
        if kind == "table":
            entry["required_inputs"] = spec.get("input_labels") or spec.get("inputs")
        else:
            entry["fields"] = len(spec.get("fields") or [])
        entries.append(entry)

    # 6 特殊能力：探最新报告期
    entries.append({
        "name": "最新报告期",
        "kind": "special",
        "aliases": ["最新财报期", "最新一期", "探报告期"],
        "indicator": "latest_report_date",
        "description": "查询某只股票最新已披露的报告期，不取财务数值。",
        "call": {"cmd": "get", "indicator": "latest_report_date", "code": "<证券代码>"},
        "returns": RETURNS["special"],
    })
    return entries


def _suffix_hit(keyword: str, name: str, min_chars: int = 3) -> bool:
    """关键词去掉前缀后仍能在名称里找到，算命中。

    用户会说「沪深300成分股」，库里叫「指数成分股」：整串搜不到，但剥掉
    「沪深300」后「成分股」在。只剥前缀不剥后缀，且剩余至少3字，
    避免短词到处命中。
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
    haystack = " ".join([entry.get("description") or "", entry.get("path") or ""])
    if kw in haystack:
        return MATCH_DESCRIPTION
    return None


# 展示顺序：派生与组优先（用户常点的），其次单指标，最后整表场景
KIND_ORDER = {"derived": 0, "group": 1, "select": 2, "excel": 3,
              "special": 4, "scene": 5, "table": 6}


def search(keyword: str, limit: int = 10, offset: int = 0,
           kind: str = "") -> dict:
    """在全部能力里搜指标，返回用法。kind 可限定类型，不传搜全部。"""
    kw = (keyword or "").strip()
    if not kw:
        return {"ok": False, "error": "keyword 不能为空"}
    offset = max(0, int(offset))
    limit = max(1, min(50, int(limit)))
    ranked = []
    for order, entry in enumerate(build_index()):
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
        item["match"] = MATCH_LABEL[rank]
        hits.append(item)
    return {"ok": True, "keyword": kw, "total": len(hits),
            "offset": offset, "limit": limit,
            "has_more": offset + limit < len(hits),
            "hits": hits[offset:offset + limit]}


def _market_rank(entry: dict) -> int:
    """同名指标跨市场并存时，按证券代码后缀挑市场，避免「营业利润」这类撞名报错。

    A股代码（.SH/.SZ/.BJ）用「股票全部指标」，港股用「港股全部指标」，
    美股用「美股全部指标」，指数用「指数全部指标」，外汇用「外汇全部指标」。
    """
    path = entry.get("path") or ""
    if path.startswith("股票全部指标"):
        return 0
    if path.startswith("港股全部指标"):
        return 1
    if path.startswith("美股全部指标"):
        return 2
    if path.startswith("指数全部指标"):
        return 3
    if path.startswith("外汇全部指标"):
        return 4
    return 5


def _market_of(code: str) -> str:
    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    return {"SH": "股票", "SZ": "股票", "BJ": "股票", "HK": "港股",
            "US": "美股", "IN": "外汇", "FX": "外汇",
            "CSI": "指数", "GI": "指数"}.get(suffix, "")


def _prefer_market(candidates: list[dict], code: str) -> dict | None:
    """按代码后缀在同名候选里挑市场匹配的那条；代码信息不足时返回 None 交调用方报歧义。"""
    market = _market_of(code or "")
    if not market:
        return None
    prefix = {"股票": "股票全部指标", "港股": "港股全部指标", "美股": "美股全部指标",
              "指数": "指数全部指标", "外汇": "外汇全部指标"}[market]
    matched = [e for e in candidates if (e.get("path") or "").startswith(prefix)]
    return matched[0] if len(matched) == 1 else None


def _describe_markets(candidates: list[dict]) -> str:
    names = {"股票全部指标": "A股", "港股全部指标": "港股", "美股全部指标": "美股",
             "指数全部指标": "指数", "外汇全部指标": "外汇"}
    markets = []
    for entry in candidates:
        first = (entry.get("path") or "").split("/")[0]
        label = names.get(first, first or entry["kind"])
        if label not in markets:
            markets.append(label)
    return "、".join(markets)


def resolve(name_or_code: str, code: str = "") -> dict:
    """按名称、别名或指标码定位一条定义。

    跨市场同名指标（营业利润、总股本、收盘价等）按证券代码后缀自动择市场；
    给不出代码或仍无法唯一确定时明确报错并列出候选，不替调用方猜。
    """
    key = (name_or_code or "").strip()
    if not key:
        raise ValueError("indicator 不能为空")
    index = build_index()
    for entry in index:
        if entry["indicator"] == key:
            return entry
    exact = [e for e in index if e["name"] == key]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        picked = _prefer_market(exact, code)
        if picked:
            return picked
        given = _market_of(code or "")
        available = _describe_markets(exact)
        if given and given not in available:
            raise ValueError(f"「{key}」目前只有{available}版本，没有{given}版本；"
                             f"可用 find 查该市场能取哪些指标")
        kinds = "；".join(f"{e['indicator']}（{e.get('path') or e['kind']}）" for e in exact)
        raise ValueError(f"「{key}」有多个同名定义：{kinds}。请改用指标码指定")
    alias = [e for e in index if key in (e.get("aliases") or [])]
    if len(alias) == 1:
        return alias[0]
    if len(alias) > 1:
        picked = _prefer_market(alias, code)
        if picked:
            return picked
        codes = "、".join(e["indicator"] for e in alias)
        raise ValueError(f"「{key}」匹配到多个别名定义：{codes}。请改用指标码指定")
    near = [e["name"] for e in index if key in e["name"]][:8]
    raise ValueError(f"没有名为「{key}」的指标"
                     + (f"；相近的有：{'、'.join(near)}" if near else "，可用 find 搜索"))
