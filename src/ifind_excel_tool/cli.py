# -*- coding: utf-8 -*-
"""ifind_excel_tool 入口：stdin JSON → stdout JSON，顶层字段 cmd。

这个文件只做一件事：把命令分派到对应层级。业务逻辑一律不在本文件里写。

五块的入口对应关系：
  find / get / fetch_package / fetch_batch / packages / package_info / search / help
      第四块 interface（对AI的检索与说明）
  get / fetch_package / fetch_batch 的实现在第二块 indicators（业务定义与取数）
  report / draw 在第三块 features（额外功能）
  run / text / open / status / close 在第五块 execution（执行层）
  lookup 是第一块 formulas 的检索（针对还没登记成科目的原始公式）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ifind_excel_tool.execution import engine
from ifind_excel_tool.features import chart as _chart
from ifind_excel_tool.features import report_command as _report
from ifind_excel_tool.formulas import library as _library
from ifind_excel_tool.indicators import fetch as _fetch
from ifind_excel_tool.indicators import packages as _packages
from ifind_excel_tool.interface import help as _help
from ifind_excel_tool.interface import search as _find
from ifind_excel_tool.interface import securities as _securities


# ---------------- 第四块：AI 检索与说明 ----------------

def find(req: dict) -> dict:
    """在全部科目里搜，返回用法。"""
    return _find.search(req.get("keyword") or "",
                        limit=int(req.get("limit") or 10),
                        offset=int(req.get("offset") or 0),
                        kind=req.get("kind") or "")


def search(req: dict) -> dict:
    """按名称或代码查证券，返回可直接取数的 ifind 代码（每页最多10行）。"""
    return _securities.search(
        req.get("keyword") or "",
        offset=int(req.get("offset") or 0),
        limit=int(req.get("limit") or _securities.PAGE_SIZE),
        kind=req.get("kind") or "")


def help_overview(req: dict) -> dict:
    """一页看清能取什么、怎么取。"""
    return _help.overview()


def packages(req: dict) -> dict:
    """列出全部科目组合。"""
    return _help.list_packages()


def package_info(req: dict) -> dict:
    """看某个组合有哪些字段、什么参数、默认值。"""
    return _help.package_info(req.get("package") or "")


def help_indicators(req: dict) -> dict:
    """按市场或关键词列出库里可用的原始公式。"""
    return _help.list_indicators(req.get("market") or "",
                                 req.get("keyword") or "",
                                 int(req.get("limit") or 100))


# ---------------- 第二块：取数 ----------------

def get(req: dict) -> dict:
    """按科目名或指标码取数。类型自动分派，不用判断底层形态。"""
    return _fetch.get(req.get("indicator") or "",
                      code=(req.get("code") or "").strip(),
                      date=(req.get("report_date") or "").strip(),
                      params=req.get("params"))


def fetch_package(req: dict) -> dict:
    """按科目组合取数：支持多期、维度覆盖、周月聚合、导出 CSV。"""
    name = req.get("package") or req.get("scene") or ""
    codes = req.get("codes") or []
    single = (req.get("code") or "").strip()
    if single:
        codes = [single]
    if not codes:
        return {"ok": False, "error": "code 或 codes 至少要给一个"}
    results = []
    last = None
    for one in codes:
        last = _fetch.get_package(
            name, code=one, date=(req.get("report_date") or "").strip(),
            dims=req.get("dims"), report_dates=req.get("report_dates"),
            start=req.get("start"), end=req.get("end"),
            period=req.get("period") or "daily", params=req.get("params"),
            export_path=req.get("export_path"),
            auto_export_rows=req.get("auto_export_rows"))
        if not last.get("ok"):
            return last
        results.extend(last.get("records") or [])
    resp = {"ok": True, "kind": "package", "indicator": name,
            "period": (last or {}).get("period") or "daily",
            "fields": (last or {}).get("fields"),
            "rows": len(results), "records": results}
    for key in ("report_date", "report_date_probed", "report_dates", "export", "hint"):
        if last and key in last:
            resp[key] = last[key]
    return resp


def fetch_batch(req: dict) -> dict:
    """按批量公式取数：一条公式让 Excel 函数把整张表写到下方。"""
    name = req.get("batch") or ""
    try:
        spec = _library.load_batch(name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    params = dict(req.get("params") or {})
    for key in spec.get("inputs") or []:
        if key not in params and req.get(key) is not None:
            params[key] = req[key]
    code_input = spec.get("code_input")
    if code_input and code_input not in params and req.get("code"):
        params[code_input] = req["code"]
    for key, value in (spec.get("defaults") or {}).items():
        params.setdefault(key, _expand_table_default(value))
    try:
        built = _library.build_batch(spec, params=params)
    except ValueError as exc:
        return {"ok": False, "error": str(exc),
                "expected_inputs": spec.get("inputs"),
                "input_labels": spec.get("input_labels") or {}}
    try:
        fetched = engine.fetch_table(built["formula"],
                                     region=req.get("read_region") or "A1:J2000",
                                     timeout=float(req.get("timeout") or 120))
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    records = _library.shape_batch(
        spec, fetched["block"], meta={"params": params, "formula": built["formula"]})
    for record in records:
        for field, unit in (spec.get("field_units") or {}).items():
            if field in record:
                record[f"{field}__unit"] = unit
    resp = {"ok": True, "source": "ifind_excel", "kind": "batch", "indicator": name,
            "formula": built["formula"], "params": params,
            "rows": len(records), "records": records,
            "elapsed_seconds": fetched["elapsed_seconds"]}
    if _fetch._all_zero([{k: v for k, v in r.items() if k not in ("params", "formula")}
                         for r in records]):
        resp["hint"] = engine.ZERO_VALUE_HINT
    _export_if_needed(req, spec["name"], params, records, resp)
    return resp


def _export_if_needed(req: dict, name: str, params: dict, records: list[dict],
                      resp: dict) -> None:
    export_path = req.get("export_path")
    limit = req.get("auto_export_rows")
    limit = 200 if limit is None else int(limit)
    if not export_path and len(records) <= limit:
        return
    target = export_path or str(
        Path(__file__).resolve().parent / "exports"
        / f"{name}_{int(__import__('time').time())}.csv")
    resp["export"] = _packages.to_csv(records, target)
    if not export_path:
        resp["records"] = records[:20]
        resp["truncated"] = True


def _expand_table_default(value):
    """批量公式输入默认值占位符。

    today_ymd    今天，YYYYMMDD
    today-1y_ymd 一年前同一天，YYYYMMDD
    """
    import re
    from datetime import datetime, timedelta

    if not isinstance(value, str):
        return value
    if value == "today_ymd":
        return f"{datetime.now():%Y%m%d}"
    rolling = re.fullmatch(r"today-(\d+)y_ymd", value)
    if rolling:
        return f"{(datetime.now() - timedelta(days=365 * int(rolling.group(1)))):%Y%m%d}"
    return value


# ---------------- 第一块：原始公式检索 ----------------

def lookup(req: dict) -> dict:
    """查还没登记成科目的原始公式。日常取数应先用 find。"""
    kw = (req.get("keyword") or "").strip()
    limit = int(req.get("limit") or 5)
    offset = max(0, int(req.get("offset") or 0))
    if not kw:
        return {"ok": False, "error": "keyword 不能为空"}
    single = _library.load_single()
    notes = _library.load_notes()
    ranked = []
    for order, (code, record) in enumerate(single.items()):
        rank = _match_rank(record, kw)
        if rank is None:
            continue
        item = {k: record[k] for k in ("path", "name", "indicator", "formula_template",
                                       "parameters", "unit", "verification", "notes")}
        item["reading_mode"] = record.get("reading_mode") or "matrix"
        item["aliases"] = record.get("aliases") or []
        item["general_notes"] = [{"id": g["id"], "note": g["note"]} for g in notes
                                 if (record.get("path") or "").startswith(g["scope"])]
        ranked.append((rank, order, item))
    ranked.sort(key=lambda x: (x[0], x[1]))
    hits = [item for _, _, item in ranked]
    return {"ok": True, "keyword": kw, "hits": hits[offset:offset + limit],
            "total": len(hits), "offset": offset, "limit": limit}


MATCH_EXACT_INDICATOR = 1
MATCH_EXACT_NAME = 2
MATCH_EXACT_ALIAS = 3
MATCH_NAME_CONTAINS = 4
MATCH_ALIAS_CONTAINS = 5
MATCH_INDICATOR_CONTAINS = 6
MATCH_DEFINITION = 7


def _match_rank(record: dict, keyword: str) -> int | None:
    words = keyword.split()
    name = (record.get("name") or "").strip()
    aliases = [a.strip() for a in (record.get("aliases") or [])]
    indicator = record.get("indicator") or ""
    definition = record.get("definition") or ""
    path = record.get("path") or ""
    haystack = " ".join([path, name, indicator, " ".join(aliases), definition])
    if not all(w in haystack for w in words):
        return None
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


# ---------------- 第三块：额外功能 ----------------

def report(req: dict) -> dict:
    """一条命令出完整报告：取数、换算、绘图、拼Markdown、落盘。"""
    return _report.generate(req)


def draw(req: dict) -> dict:
    """按模板绘图：读已导出的行情CSV，输出 PNG。"""
    return _chart.draw(req)


# ---------------- 第五块：执行层 ----------------

def run(req: dict) -> dict:
    """执行原始公式矩阵。只有统一科目库覆盖不到时才用。"""
    matrix = req.get("matrix")
    if not matrix or not isinstance(matrix[0], list):
        return {"ok": False, "error": "matrix 必须是非空二维数组"}
    result = engine.fetch_matrix(matrix, visible=req.get("visible"),
                                 timeout=float(req.get("timeout") or 300))
    return {"ok": True, "source": "ifind_excel", **result}


def text(req: dict) -> dict:
    """取文本字段的原始公式。"""
    formulas = req.get("formulas")
    if not formulas:
        return {"ok": False, "error": "formulas 不能为空"}
    result = engine.fetch_formulas(formulas, visible=req.get("visible"),
                                   timeout=float(req.get("timeout") or 120),
                                   text_ok=True)
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


CMDS = {"find": find, "search": search,
        "help": help_overview, "packages": packages, "package_info": package_info,
        "help_indicators": help_indicators,
        "get": get, "fetch_package": fetch_package, "fetch_scene": fetch_package,
        "fetch_batch": fetch_batch,
        "lookup": lookup,
        "report": report, "draw": draw,
        "run": run, "text": text, "open": open_excel, "status": status, "close": close}


def main() -> None:
    try:
        req = json.loads(sys.stdin.read())
    except json.JSONDecodeError as error:
        print(json.dumps({"ok": False, "error": f"输入不是合法JSON：{error}"},
                         ensure_ascii=False))
        return
    if not isinstance(req, dict):
        print(json.dumps({"ok": False, "error": "输入必须是JSON对象"}, ensure_ascii=False))
        return
    cmd = req.get("cmd")
    if cmd not in CMDS:
        resp = {"ok": False, "error": f"未知 cmd：{cmd}；支持 {list(CMDS)}"}
    else:
        try:
            resp = CMDS[cmd](req)
        except Exception as exc:  # noqa: BLE001
            resp = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(json.dumps(resp, ensure_ascii=False))


if __name__ == "__main__":
    main()
