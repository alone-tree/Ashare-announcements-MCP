# -*- coding: utf-8 -*-
"""帮助查询：让 AI 在动手前先看清有哪些场景、每个场景要什么参数、支持哪些科目。

与 lookup 的分工：
  lookup      查单个指标码/名称，面向「我要这个数用哪条公式」
  help_*      查场景与参数，面向「我要这类数据该调用什么、给什么参数」
"""
from __future__ import annotations

import json
from pathlib import Path

SCENES = Path(__file__).resolve().parent / "scenes"
LIBRARY = Path(__file__).resolve().parent / "formula_library"


def _load(name: str) -> list[dict]:
    path = LIBRARY / name
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# 场景族归属：按名字前缀归类，新增场景时在此登记，未登记的归入「其他」
FAMILY = {
    "历史行情": "行情",
    "估值快照": "行情",
    "指数成分股": "零散命令",
    "工商信息": "基本信息",
    "十大股东": "基本信息",
    "资产负债表": "财报",
    "利润表": "财报",
    "现金流量表": "财报",
    "利润表单季": "财报",
    "现金流量表单季": "财报",
}

FAMILY_DESC = {
    "行情": "按交易日连续更新的数值。变化在复权方式、要哪些量、日周月频率。",
    "财报": "按报告期更新的数值。变化在累计还是单季、要哪些科目。",
    "基本信息": "单点时刻的状态，不定期更新。变化在问哪个时点。",
    "零散命令": "一次返回一张特定报表，参数各不相同。",
}


def overview() -> dict:
    """一页看清所有场景与族归属，AI 先看这个再决定调什么。"""
    families: dict[str, list] = {}
    for path in sorted(SCENES.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        name = spec.get("name") or path.stem
        family = FAMILY.get(name, "其他")
        kind = spec.get("kind") or "matrix"
        item = {"scene": name, "kind": kind,
                "fields": len(spec.get("fields") or []),
                "description": spec.get("description", "")}
        if kind == "table":
            item["inputs"] = spec.get("input_labels") or spec.get("inputs")
        else:
            item["defaults"] = spec.get("defaults") or {}
        families.setdefault(family, []).append(item)

    return {
        "ok": True,
        "families": [
            {"family": fam,
             "what": FAMILY_DESC.get(fam, ""),
             "scenes": items}
            for fam, items in sorted(families.items())
        ],
        "how_to_call": {
            "看场景清单": '{"cmd":"scenes"}',
            "看某场景要哪些字段": '{"cmd":"scene_info","scene":"历史行情"}',
            "取数": '{"cmd":"fetch_scene","scene":"历史行情","code":"600519.SH"}',
            "查单个指标公式": '{"cmd":"lookup","keyword":"营业收入"}',
            "直接执行任意公式": '{"cmd":"run","matrix":[[...]]}',
        },
    }


def scene_params(scene: str) -> dict:
    """某个场景的可选参数与默认值，取数前确认用。"""
    path = SCENES / f"{scene}.json"
    if not path.is_file():
        available = [p.stem for p in sorted(SCENES.glob("*.json"))]
        return {"ok": False, "error": f"没有名为「{scene}」的场景", "available": available}
    spec = json.loads(path.read_text(encoding="utf-8"))
    kind = spec.get("kind") or "matrix"

    out = {"ok": True, "scene": spec.get("name") or scene, "kind": kind,
           "description": spec.get("description", "")}

    if kind == "table":
        out["required_inputs"] = {
            name: (spec.get("input_labels") or {}).get(name, name)
            for name in (spec.get("inputs") or [])}
        out["defaults"] = spec.get("defaults") or {}
        out["output_fields"] = [
            {"field": f,
             "label": (spec.get("field_labels") or spec.get("fields"))[i]
                      if i < len(spec.get("field_labels") or []) else f,
             "unit": (spec.get("field_units") or {}).get(f, "")}
            for i, f in enumerate(spec.get("fields") or [])]
        out["formula_preview"] = spec.get("notes", "")
        return out

    out["required_inputs"] = ({"code": "证券代码，如 600519.SH"}
                              if spec.get("code_required") else {})
    out["optional_inputs"] = {
        "report_date": "报告期或交易日，YYYY-MM-DD。不传取该场景默认。",
        "start": "区间起点，YYYY-MM-DD（仅按日期展开的场景有效）",
        "end": "区间终点，YYYY-MM-DD，或 today",
        "params": "覆盖场景里的字段参数，如 {\"adjust\": 100}",
        "export_path": "结果写 CSV 的路径；不传但行数超 200 时自动落盘",
    }
    out["defaults"] = spec.get("defaults") or {}
    out["dims"] = spec.get("dims") or {}
    out["fields"] = [{"label": f["label"],
                      "indicator": f.get("indicator") or "+".join(f.get("candidates") or []),
                      "unit": f.get("unit", ""),
                      "hidden": bool(f.get("hidden"))}
                     for f in spec.get("fields") or []]
    return out


def list_indicators(market: str = "", keyword: str = "", limit: int = 100) -> dict:
    """按市场或关键词列出库里可用的指标，回答「这类数据支持哪些科目」。"""
    rows = _load("verified-formulas.jsonl")
    out = []
    for r in rows:
        path = r.get("path") or ""
        if market and market not in path:
            continue
        if keyword and keyword not in (r.get("name") or "") and keyword not in (r.get("indicator") or ""):
            continue
        out.append({"name": (r.get("name") or "").strip(),
                    "indicator": r.get("indicator"),
                    "path": path,
                    "unit": r.get("unit", ""),
                    "verification": r.get("verification")})
    markets = sorted({(r.get("path") or "").split("/")[0] for r in rows if r.get("path")})
    return {"ok": True, "total": len(out), "shown": min(len(out), limit),
            "indicators": out[:limit], "markets": markets}
