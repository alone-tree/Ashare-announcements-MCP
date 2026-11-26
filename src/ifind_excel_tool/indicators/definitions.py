# -*- coding: utf-8 -*-
"""第二块 业务定义：衍生科目与科目组合的登记表。

这块回答「有哪些科目、每个科目怎么取」。对调用方来说，下面几种东西地位完全相同：
  formula  第一块录入的原始公式（单点或批量）
  derived  衍生科目（写依赖与算式）
  package  科目组合（若干科目打包，一次取回）

谁排在谁上面只影响内部实现，不影响检索和调用。所以这里把三者展开成同一形态的条目。
"""
from __future__ import annotations

import json
from pathlib import Path

from ifind_excel_tool.formulas import library

HERE = Path(__file__).resolve().parent

# 返回形状：让调用的 AI 一眼知道会拿到什么，不用试。
RETURNS = {
    "formula": "单值。raw 为数值或文本，单位见 unit。",
    "batch": "整表。一条公式让 Excel 函数把多行数据写到下方，records 为逐行记录。",
    "derived": "单值。已按定义算好并保留指定小数位，可直接用，不需再加工。",
    "package": "一组值。records 每行一条，组内的衍生科目已算好。",
    "select": "单值。从多个候选里取较大值，值不同时带 choices 说明选了哪条。",
    "special": "单值。非取数能力的查询结果。",
}


def load_derived() -> dict[str, dict]:
    path = HERE / "derived.jsonl"
    if not path.is_file():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return {row["name"]: row for row in rows}


def load_packages() -> dict[str, dict]:
    path = HERE / "packages.jsonl"
    if not path.is_file():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return {row["name"]: row for row in rows}


def _call(name: str, *, extra: dict | None = None) -> dict:
    payload = {"cmd": "get", "indicator": name, "code": "<证券代码>"}
    payload.update(extra or {})
    return payload


def build_index() -> list[dict]:
    """把全部科目展开成同一形态的条目，供检索与解析用。"""
    entries: list[dict] = []
    derived = load_derived()
    packages = load_packages()
    single = library.load_single()

    # 衍生科目
    for name, item in derived.items():
        entries.append({
            "name": name,
            "kind": "derived",
            "aliases": item.get("aliases") or [],
            "indicator": name,
            "description": item.get("description", ""),
            "unit": item.get("unit", ""),
            "decimals": item.get("decimals"),
            "depends_on": [d["label"] for d in item.get("deps") or []],
            "call": _call(name),
            "returns": RETURNS["derived"],
        })

    # 科目组合
    for name, item in packages.items():
        entries.append({
            "name": name,
            "kind": "package",
            "aliases": item.get("aliases") or [],
            "indicator": name,
            "description": item.get("description", ""),
            "members": [f["label"] for f in item.get("fields") or []],
            "call": _call(name),
            "returns": RETURNS["package"],
        })

    # 多候选取值的字段：藏在组合里的规则，单独暴露成可检索的科目
    for name, item in packages.items():
        for field in item.get("fields") or []:
            if not field.get("candidates"):
                continue
            label = field["label"]
            if label in derived or any(e["name"] == label for e in entries):
                continue
            entries.append({
                "name": label,
                "kind": "select",
                "aliases": field.get("aliases") or [],
                "indicator": label,
                "description": f"多候选取较大值。候选：{'、'.join(field['candidates'])}",
                "unit": field.get("unit", ""),
                "candidates": field["candidates"],
                "pick": field.get("pick") or "max",
                "package": name,
                "call": _call(label),
                "returns": RETURNS["select"],
            })

    # 原始单点公式
    for code, record in single.items():
        name = (record.get("name") or "").strip()
        if not name:
            continue
        entries.append({
            "name": name,
            "kind": "formula",
            "aliases": record.get("aliases") or [],
            "indicator": code,
            "description": record.get("definition") or "",
            "unit": record.get("unit", ""),
            "path": record.get("path", ""),
            "reading_mode": record.get("reading_mode") or "matrix",
            "call": _call(code),
            "returns": RETURNS["formula"],
        })

    # 批量公式
    for spec in library.list_batch():
        entries.append({
            "name": spec["name"],
            "kind": "batch",
            "aliases": spec.get("aliases") or [],
            "indicator": spec["name"],
            "description": spec.get("description", ""),
            "required_inputs": spec.get("input_labels") or spec.get("inputs"),
            "call": _call(spec["name"]),
            "returns": RETURNS["batch"],
        })

    # 特殊能力：探最新报告期
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


def _market_of(code: str) -> str:
    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    return {"SH": "股票", "SZ": "股票", "BJ": "股票", "HK": "港股",
            "US": "美股", "IN": "外汇", "FX": "外汇",
            "CSI": "指数", "GI": "指数"}.get(suffix, "")


def _prefer_market(candidates: list[dict], code: str) -> dict | None:
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
    """按名称、别名或指标码定位一条科目定义。

    同名时优先用「多候选取值」定义：那一条是有意合并过的口径，比原始单科目更准。
    跨市场同名科目按证券代码后缀自动择市场；无法唯一确定时报错列出候选。
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
        select = [e for e in exact if e["kind"] == "select"]
        if len(select) == 1:
            return select[0]
        # 与原始科目同名的衍生定义是有意合并过的稳健口径（如合同负债=max(合同负债,预收)），优先
        derived = [e for e in exact if e["kind"] == "derived"]
        if len(derived) == 1:
            return derived[0]
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
