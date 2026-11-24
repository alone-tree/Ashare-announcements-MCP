# -*- coding: utf-8 -*-
"""ifind_excel_tool CLI：stdin JSON → stdout JSON，顶层字段 cmd。

先跑 {"cmd":"help"} 看导航（start_here 按需求指明该调哪个命令）。
主要命令：
  search       查证券代码，必须指定kind=股票/指数/外汇（每页10行，offset翻页）
  fetch_scene  按固定场景取数（优先用这个）
  lookup/run/text  查公式、执行公式矩阵、取文本字段（场景没有才用）
  help/help_scene/help_indicators/scenes/scene_info  各种帮助查询
  open/status/close  Excel生命周期

详细用法见 usage.md。设计意图：让AI行动前先查清有什么、该用什么，
避免绕过现成场景自己拼公式踩坑（港股五位代码、非交易日前推等）。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ifind_excel_tool import engine, help as _help, scenes as _scenes, search as _search

LIB = Path(__file__).resolve().parent / "formula_library"


def _load(name: str) -> list[dict]:
    path = LIB / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# 匹配强度：数字越小越靠前。用途是让 AI 一眼看出哪条才是用户要的科目，
# 避免「搜净资产取第一条却拿到归母口径」这类错。
MATCH_EXACT_INDICATOR = 1   # 指标码完全相同
MATCH_EXACT_NAME = 2        # 正式名称完全相同
MATCH_EXACT_ALIAS = 3       # 别名完全相同
MATCH_NAME_CONTAINS = 4     # 正式名称包含
MATCH_ALIAS_CONTAINS = 5    # 别名包含
MATCH_INDICATOR_CONTAINS = 6  # 指标码包含
MATCH_DEFINITION = 7        # 仅定义正文命中


def _match_rank(record: dict, keyword: str) -> int | None:
    """返回该记录对关键词的匹配强度；不命中返回 None。

    多词关键词（空格分隔）沿用历史语义：全部词都要出现在检索范围内才命中，
    匹配强度按整串关键词在字段中的位置判定。
    """
    words = keyword.split()
    name = (record.get("name") or "").strip()
    aliases = [a.strip() for a in (record.get("aliases") or [])]
    indicator = record.get("indicator") or ""
    definition = record.get("definition") or ""
    path = record.get("path") or ""

    # 全部词必须出现在合并检索范围内，否则不命中（保持原有可用性）
    haystack = " ".join([path, name, indicator, " ".join(aliases), definition])
    if not all(w in haystack for w in words):
        return None

    # 单字关键词才能做完全匹配判定；多词按包含处理
    if len(words) == 1:
        if keyword == indicator:
            return MATCH_EXACT_INDICATOR
        if keyword == name:
            return MATCH_EXACT_NAME
        if keyword in aliases:
            return MATCH_EXACT_ALIAS
        if keyword in name:
            return MATCH_NAME_CONTAINS
        if any(keyword in a for a in aliases):
            return MATCH_ALIAS_CONTAINS
        if keyword in indicator:
            return MATCH_INDICATOR_CONTAINS
        return MATCH_DEFINITION

    if all(w in name for w in words):
        return MATCH_NAME_CONTAINS
    if any(all(w in a for w in words) for a in aliases):
        return MATCH_ALIAS_CONTAINS
    if all(w in indicator for w in words):
        return MATCH_INDICATOR_CONTAINS
    return MATCH_DEFINITION


def lookup(req: dict) -> dict:
    kw = (req.get("keyword") or "").strip()
    limit = int(req.get("limit") or 5)
    offset = max(0, int(req.get("offset") or 0))
    if not kw:
        return {"ok": False, "error": "keyword 不能为空"}
    verified = _load("verified-formulas.jsonl")
    general = _load("general-notes.jsonl")
    ranked = []
    for order, r in enumerate(verified):
        rank = _match_rank(r, kw)
        if rank is None:
            continue
        item = {k: r[k] for k in ("path", "name", "indicator", "formula_template",
                                   "parameters", "unit", "verification", "notes")}
        # reading_mode 决定该走数值通道还是文本通道，缺了它 AI 会用错命令
        item["reading_mode"] = r.get("reading_mode") or "matrix"
        item["aliases"] = r.get("aliases") or []
        item["match"] = {MATCH_EXACT_INDICATOR: "指标码完全匹配",
                         MATCH_EXACT_NAME: "名称完全匹配",
                         MATCH_EXACT_ALIAS: "别名完全匹配",
                         MATCH_NAME_CONTAINS: "名称包含",
                         MATCH_ALIAS_CONTAINS: "别名包含",
                         MATCH_INDICATOR_CONTAINS: "指标码包含",
                         MATCH_DEFINITION: "仅定义正文命中"}[rank]
        item["general_notes"] = [{"id": g["id"], "note": g["note"]}
                                 for g in general if r["path"].startswith(g["scope"])]
        ranked.append((rank, order, item))
    # 先按匹配强度，同强度保持库内原有顺序
    ranked.sort(key=lambda x: (x[0], x[1]))
    hits = [item for _, _, item in ranked]
    return {"ok": True, "keyword": kw, "source": "verified",
            "hits": hits[offset:offset + limit], "total": len(hits),
            "offset": offset, "limit": limit}


def run(req: dict) -> dict:
    matrix = req.get("matrix")
    if not matrix or not isinstance(matrix[0], list):
        return {"ok": False, "error": "matrix 必须是非空二维数组"}
    result = engine.fetch_matrix(matrix, visible=req.get("visible"),
                                 timeout=float(req.get("timeout") or 300))
    return {"ok": True, "source": "ifind_excel", **result}


def text(req: dict) -> dict:
    formulas = req.get("formulas")
    if not formulas:
        return {"ok": False, "error": "formulas 不能为空"}
    result = engine.fetch_formulas(formulas, visible=req.get("visible"),
                                   timeout=float(req.get("timeout") or 120), text_ok=True)
    return {"ok": True, "source": "ifind_excel", **result}


def close(req: dict) -> dict:
    return {"ok": True, "source": "ifind_excel",
            **engine.close_excel(timeout=float(req.get("timeout") or 30))}


def status(req: dict) -> dict:
    """只读查询；Excel 未打开时不会启动它。"""
    return {"ok": True, "source": "ifind_excel",
            **engine.status(timeout=float(req.get("timeout") or 15))}


def open_excel(req: dict) -> dict:
    return {"ok": True, "source": "ifind_excel",
            **engine.open_excel(visible=req.get("visible", True),
                                timeout=float(req.get("timeout") or 60))}


def _fetch_table_scene(req: dict, spec: dict) -> dict:
    """表函数场景：一条公式返回整张表，需要写公式后等函数把数据写到下方。

    与矩阵场景的差别在等待方式：矩阵靠单元格是否还在显示抓取/提取，
    表函数是往下方逐步追加行，只能按行数稳定判断。实测约 1 秒到位。
    """
    params = dict(req.get("params") or {})
    for key in spec.get("inputs") or []:
        if key not in params and req.get(key) is not None:
            params[key] = req[key]
    for key, value in (spec.get("defaults") or {}).items():
        if value == "today_ymd" and key not in params:
            params[key] = f"{datetime.now():%Y%m%d}"
        elif key not in params:
            params[key] = value
    try:
        built = _scenes.build_table(spec, params=params)
    except ValueError as exc:
        return {"ok": False, "error": str(exc),
                "expected_inputs": spec.get("inputs"),
                "input_labels": spec.get("input_labels") or {}}

    connected, _ = engine._find_workbook()
    if connected is None:
        return {"ok": False, "error": "专用工作簿未打开，请先执行 {\"cmd\":\"open\"}"}
    app, book, pid = connected
    sheet = book.Worksheets("data")
    engine._ensure_functions(app)
    sheet.Cells.ClearContents()

    region = req.get("read_region") or "A1:J2000"
    sheet.Range("A1").Formula2 = built["formula"]

    limit = float(req.get("timeout") or 120)
    started = time.time()
    prev_sig, stable, rows_now = None, 0, 0
    block = []
    while time.time() - started < limit:
        time.sleep(0.8)
        try:
            block = sheet.Range(region).Value2
        except Exception:
            continue
        if not isinstance(block, tuple):
            block = ((block,),)
        rows_now = sum(1 for row in block
                       if isinstance(row, tuple) and any(v is not None for v in row))
        sig = str(block)
        if sig == prev_sig:
            stable += 1
            if stable >= 2 and rows_now > 1:
                break
        else:
            stable = 0
            prev_sig = sig

    records = _scenes.shape_table(spec, block,
                                  meta={"params": params, "formula": built["formula"]})
    units = spec.get("field_units") or {}
    for record in records:
        for field, unit in units.items():
            if field in record:
                record[f"{field}__unit"] = unit
    resp = {"ok": True, "source": "ifind_excel", "scene": spec.get("name"),
            "kind": "table", "formula": built["formula"],
            "params": params, "rows": len(records), "records": records,
            "elapsed_seconds": round(time.time() - started, 2)}
    export_path = req.get("export_path")
    if export_path or len(records) > int(req.get("auto_export_rows") or 200):
        target = export_path or str(
            Path(__file__).resolve().parent / "exports"
            / f"{spec.get('name')}_{params.get('idx_code') or 'table'}_"
              f"{datetime.now():%Y%m%d-%H%M%S}.csv")
        resp["export"] = _scenes.to_csv(records, target)
        if not export_path:
            resp["records"] = records[:20]
            resp["truncated"] = True
    return resp


def search(req: dict) -> dict:
    """按名称或代码查证券，返回可直接用于取数的ifind代码（每页最多10行）。"""
    return _search.search(
        req.get("keyword") or "",
        offset=int(req.get("offset") or 0),
        limit=int(req.get("limit") or _search.PAGE_SIZE),
        kind=req.get("kind") or "",
    )


def scenes(req: dict) -> dict:
    """列出固定场景，让调用方知道自己能直接取哪几套数据。"""
    return {"ok": True, "scenes": _scenes.list_scenes()}


def scene_info(req: dict) -> dict:
    """看某个场景会取哪些字段，取数前先确认再取。"""
    spec = _scenes.load_scene(req.get("scene") or "")
    return {"ok": True, "name": spec.get("name"),
            "description": spec.get("description", ""),
            "dims": spec.get("dims") or {},
            "defaults": spec.get("defaults") or {},
            "fields": [{"label": f["label"],
                        "indicator": f.get("indicator") or "+".join(f.get("candidates") or []),
                        "pick": f.get("pick")} for f in spec["fields"]]}


def fetch_scene(req: dict) -> dict:
    """按固定场景取数。换公司与日期只改 code 和 report_date。"""
    name = req.get("scene") or ""
    spec = _scenes.load_scene(name)
    if spec.get("kind") == "table":
        return _fetch_table_scene(req, spec)
    codes = req.get("codes") or []
    single = (req.get("code") or "").strip()
    if single:
        codes = [single]
    if not codes:
        return {"ok": False, "error": "code 或 codes 至少要给一个"}
    library = _scenes._load_library()
    results = []
    for one in codes:
        built = _scenes.build(spec, library, code=one,
                              report_date=req.get("report_date"),
                              params=req.get("params"),
                              start=req.get("start"), end=req.get("end"))
        raw = engine.fetch_matrix(built["matrix"], visible=req.get("visible"),
                                  timeout=float(req.get("timeout") or 300),
                                  text_ok=True)
        records = _scenes.shape(spec, built["plan"], built["columns"],
                                built["combos"], raw["values"])
        for record in records:
            record["code"] = one
        results.extend(records)
    resp = {"ok": True, "source": "ifind_excel", "scene": spec.get("name"),
            "fields": len(spec["fields"]), "rows": len(results),
            "records": results}
    # 导出口径：调用方给了路径就写文件；没给且行数超过阈值，自动落盘避免把大结果塞进对话
    export_path = req.get("export_path")
    if export_path or len(results) > int(req.get("auto_export_rows") or 200):
        target = export_path or str(
            Path(__file__).resolve().parent / "exports"
            / f"{spec.get('name')}_{(req.get('code') or (req.get('codes') or [''])[0]).replace('.', '_')}"
              f"_{datetime.now():%Y%m%d-%H%M%S}.csv")
        resp["export"] = _scenes.to_csv(results, target)
        if not export_path:
            resp["records"] = results[:20]  # 大结果只回前20行示意，完整数据在文件里
            resp["truncated"] = True
    return resp


def help_overview(req: dict) -> dict:
    """一页看清所有场景与族归属。"""
    return _help.overview()


def help_scene(req: dict) -> dict:
    """某场景要什么参数、有哪些字段、默认值是什么。"""
    return _help.scene_params(req.get("scene") or "")


def help_indicators(req: dict) -> dict:
    """按市场或关键词列出库里可用的指标。"""
    return _help.list_indicators(req.get("market") or "",
                                 req.get("keyword") or "",
                                 int(req.get("limit") or 100))


CMDS = {"lookup": lookup, "run": run, "text": text, "close": close,
        "status": status, "open": open_excel, "search": search,
        "scenes": scenes, "scene_info": scene_info, "fetch_scene": fetch_scene,
        "help": help_overview, "help_scene": help_scene, "help_indicators": help_indicators}


def main() -> None:
    try:
        req = json.loads(sys.stdin.read())
    except json.JSONDecodeError as error:
        print(json.dumps({"ok": False, "error": f"输入不是合法JSON：{error}"},
                         ensure_ascii=False))
        return
    if not isinstance(req, dict):
        print(json.dumps({"ok": False, "error": "输入必须是JSON对象"},
                         ensure_ascii=False))
        return
    cmd = req.get("cmd")
    if cmd not in CMDS:
        resp = {"ok": False, "error": f"未知 cmd：{cmd}；支持 {list(CMDS)}"}
    else:
        try:
            resp = CMDS[cmd](req)
        except Exception as exc:
            resp = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    # 结果含®等字符时，GBK终端print会抛UnicodeEncodeError，强制UTF-8输出
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(json.dumps(resp, ensure_ascii=False))


if __name__ == "__main__":
    main()
