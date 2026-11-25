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
    "指数进出记录": "零散命令",
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
        "start_here": {
            "不知道证券代码": '先 {"cmd":"search","keyword":"腾讯","kind":"股票"} 查代码（kind必须指定：股票/指数/外汇），用返回的ifind_code取数',
            "不知道要的数据叫什么": '先 {"cmd":"find","keyword":"毛利率"} 搜指标，范围含公式、场景、报表函数、自定义指标与指标组；看到用法后用 get 取数',
            "要一个具体的数": '{"cmd":"get","indicator":"毛利率","code":"002796.SZ","report_date":"2026-09-30"}，类型自动分派',
            "要一组常用科目": '{"cmd":"get","indicator":"利润表常用科目","code":"002796.SZ","report_date":"2026-09-30"}',
            "要一段行情或某天估值": 'fetch_scene 场景「历史行情」「估值快照」',
            "要财报三表": "fetch_scene 对应的资产负债表/利润表/现金流量表场景",
            "要公司资料或股东": "fetch_scene 场景「工商信息」「十大股东」",
            "要指数成分股": "fetch_scene 场景「指数成分股」",
            "要一份完整报告": '{"cmd":"report","code":"002796.SZ","output":"导出目录"} 一条命令取数、换算、绘图、拼Markdown',
            "要画行情图": '{"cmd":"draw","template":"kline_volume","data_path":"...csv","output":"...png"}',
            "库里没有的指标": "find 搜确认确实没有，再 lookup 查公式、用 run 拼；原始公式原样传给Excel执行，AI不直接操作Excel",
            "重要规则": [
                "不知道指标名就先 find，别凭印象拼公式",
                "优先用fetch_scene和get，场景确实没有才用run自己拼公式",
                "取数的code必须是iFinD格式：港股四位如0700.HK，不是五位；用search查最稳",
                "search每页最多10行，更多用offset翻页",
                "财报类场景与get不传report_date时自动探最新已披露期；探不到会明确报错要求指定",
                "固定资产/在建工程已合并为多候选字段，自动取合计与单科目较大值",
            ],
        },
        "families": [
            {"family": fam,
             "what": FAMILY_DESC.get(fam, ""),
             "scenes": items}
            for fam, items in sorted(families.items())
        ],
        "how_to_call": {
            "查证券代码": '{"cmd":"search","keyword":"腾讯","kind":"股票"}  kind必须指定：股票/指数/外汇',
            "搜指标（不知道叫什么）": '{"cmd":"find","keyword":"毛利率"}  范围含公式/场景/报表函数/自定义/指标组',
            "按指标取一个数": '{"cmd":"get","indicator":"毛利率","code":"002796.SZ","report_date":"2026-09-30"}',
            "取一组常用科目": '{"cmd":"get","indicator":"利润表常用科目","code":"002796.SZ","report_date":"2026-09-30"}',
            "看场景清单": '{"cmd":"scenes"}',
            "看某场景要哪些字段": '{"cmd":"scene_info","scene":"历史行情"}',
            "取数": '{"cmd":"fetch_scene","scene":"历史行情","code":"600519.SH"}',
            "板块导出CSV": '{"cmd":"fetch_scene","scene":"工商信息","code":"002796.SZ","export_path":"数据/工商信息.csv"}',
            "只看单个板块": '{"cmd":"fetch_scene","scene":"分红","code":"002796.SZ","dims":{"year":["2025","2024"]}}',
            "画行情图": '{"cmd":"draw","template":"kline_volume","data_path":"数据/历史行情.csv","output":"行情.png"}',
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
    if scene == "历史行情":
        out["key_points"] = [
            "默认前复权108，可在params改adjust：100不复权、107后复权、108前复权",
            "区间start/end，默认2016年至今",
            "已剔除非交易日（周末、节假日），但保留停牌日、量额记0；判据是不前推收盘价大于0",
            "period可选daily/weekly/monthly，默认daily；先取日K再本地聚合，不直接取周月K",
        ]

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
    if spec.get("resample"):
        out["optional_inputs"]["period"] = "daily/weekly/monthly，默认daily；周/月线由日线本地聚合"
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
