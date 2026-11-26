# -*- coding: utf-8 -*-
"""第二块 取数：按科目定义取回数据，类型自动分派。

对调用方只有一个入口 get()：给科目名或指标码，拿回加工好的结果，不用判断底层
是原始公式、批量公式、衍生科目、科目组合还是特殊能力。

三条纪律：
- 依赖合并取数：一个科目组合的多项依赖一次矩阵提交，不重复跑 Excel。
- 算式只走四则运算白名单，不执行任意代码。
- 缺依赖、分母为零时该值不可用并给原因，不静默回退成 0。
"""
from __future__ import annotations

import ast
import operator

from ifind_excel_tool.execution import engine
from ifind_excel_tool.formulas import library
from ifind_excel_tool.indicators import definitions

_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub,
            ast.Mult: operator.mul, ast.Div: operator.truediv}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def evaluate(definition: dict, values: dict):
    """按四则运算白名单求值。不可用（缺依赖、分母为零）时返回 None 并留原因。"""
    expr = definition.get("expr")
    if not expr:
        return None
    missing = [d["label"] for d in definition.get("deps") or []
               if d["label"] not in values]
    if missing:
        return None
    try:
        number = _eval_expr(expr, values)
    except ZeroDivisionError:
        return None
    except ValueError:
        return None
    decimals = definition.get("decimals")
    if isinstance(decimals, int) and decimals >= 0:
        number = round(number, decimals)
    return number


def _eval_expr(expr: str, names: dict[str, float]) -> float:
    """对只含四则运算与变量名的表达式求值，不用 eval。"""
    tree = ast.parse(expr, mode="eval")

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError(f"算式里出现非数值常量：{node.value!r}")
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise ValueError(f"算式引用了未提供的依赖：{node.id}")
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](walk(node.operand))
        raise ValueError(f"算式含不支持的写法：{ast.dump(node)}")

    return walk(tree)


def probe_latest_report(code: str) -> str | None:
    """探最新已披露报告期，返回 YYYY-MM-DD；探不到返回 None。

    用库内已验证的文本公式，不猜参数。交易日用当天，公式按公告日返回截止日。
    """
    import re

    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    indicator = "ths_latest_rp_hks" if suffix == "HK" else "ths_regular_report_latest_rp_stock"
    from datetime import date as _date

    formula = f'=@thsiFinD("{indicator}","{code}","{_date.today().isoformat()}")'
    result = engine.fetch_formulas([formula], text_ok=True)
    values = result.get("values") or []
    raw = values[0] if values else None
    if not isinstance(raw, str):
        return None
    matched = re.fullmatch(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", raw.strip()[:10])
    if not matched:
        return None
    year, month, day = matched.groups()
    return f"{year}-{month}-{day}"


def _probe_if_needed(kind: str, code: str, date: str) -> tuple[str, str | None]:
    """财报类科目不给日期时先探最新已披露报告期，探不到明确报错，不静默取空。

    原始公式不给日期则保持原样：行情类指标有意留空取最新值。
    """
    if date or kind not in ("derived", "package", "select") or not code:
        return date, None
    probed = probe_latest_report(code)
    if not probed:
        raise ValueError(f"无法确定最新报告期，请显式传 report_date（探测 {code} 失败）。"
                         f"{engine.ZERO_VALUE_HINT}")
    return probed, probed


def get(name_or_code: str, code: str = "", date: str = "",
        params: dict | None = None) -> dict:
    """按科目名或指标码取数。类型自动分派，调用方不用判断底层形态。"""
    entry = definitions.resolve(name_or_code, code)
    kind = entry["kind"]
    date, probed = _probe_if_needed(kind, code, date)

    if kind == "special":
        latest = probe_latest_report(code)
        if not latest:
            return {"ok": False, "indicator": entry["name"],
                    "error": f"无法确定最新报告期（探测 {code} 失败）",
                    "hint": engine.ZERO_VALUE_HINT}
        return {"ok": True, "indicator": entry["name"], "code": code,
                "value": latest, "unit": "报告期"}

    if kind == "package":
        return get_package(entry["name"], code=code, date=date)

    if kind == "batch":
        return {"ok": False, "indicator": entry["name"],
                "error": f"「{entry['name']}」是批量公式，需要专有输入参数，"
                         f"请用 fetch_batch 指定：{entry.get('required_inputs')}"}

    if kind == "select":
        # 多候选：一次取全部候选，取较大值，与组合内同一套规则
        single = library.load_single()
        formulas = [library.render(single[c], {"code": code, "date": date,
                                               **(params or {})})
                    for c in entry["candidates"]]
        block = (engine.fetch_matrix([formulas], text_ok=True).get("values") or [[]])[0]
        cells = [library.coerce(v) for v in block]
        numbers = [(v, c) for v, c in zip(cells, entry["candidates"])
                   if isinstance(v, (int, float))]
        if not numbers:
            return {"ok": True, "indicator": entry["name"], "value": 0,
                    "unit": entry.get("unit", ""), "candidates": entry["candidates"]}
        value, picked = max(numbers, key=lambda x: x[0])
        out = {"ok": True, "indicator": entry["name"], "value": value,
               "unit": entry.get("unit", ""), "picked": picked,
               "date": date, "date_probed": probed is not None,
               "candidates": entry["candidates"]}
        if len({v for v, _ in numbers}) > 1:
            out["choices"] = {c: v for v, c in zip(cells, entry["candidates"])}
        return out

    if kind == "derived":
        definition = definitions.load_derived()[entry["name"]]
        values, missing = _fetch_deps(definition.get("deps") or [], code, date)
        if missing:
            return {"ok": False, "indicator": entry["name"],
                    "error": f"缺依赖：{'、'.join(missing)}，{entry['name']}不可用"}
        computed = evaluate(definition, values)
        if computed is None:
            return {"ok": False, "indicator": entry["name"],
                    "error": f"{entry['name']}不可用：分母为零或依赖缺失"}
        return {"ok": True, "indicator": entry["name"], "value": computed,
                "unit": definition.get("unit", ""),
                "decimals": definition.get("decimals"),
                "date": date, "date_probed": probed is not None, "deps": values}

    # 原始单点公式
    if not code:
        return {"ok": False, "indicator": entry["name"], "error": "code 必须提供"}
    single = library.load_single()
    record = single.get(entry["indicator"])
    if record is None:
        return {"ok": False, "indicator": entry["name"],
                "error": f"指标未入库：{entry['indicator']}"}
    formula = library.render(record, {"code": code, "date": date, **(params or {})})
    raw = _fetch_one(record, formula)
    return {"ok": True, "indicator": entry["name"], "code": code, "date": date,
            "value": library.coerce(raw), "unit": record.get("unit", ""),
            "indicator_code": entry["indicator"]}


def _fetch_one(record: dict, formula: str):
    """取单个公式的值。文本指标走 text 通道。"""
    if (record.get("reading_mode") or "matrix") == "text":
        values = engine.fetch_formulas([formula], text_ok=True).get("values") or []
        return values[0] if values else None
    block = engine.fetch_matrix([[formula]], text_ok=True).get("values") or []
    return block[0][0] if block and block[0] else None


def _fetch_deps(deps: list[dict], code: str, date: str) -> tuple[dict, list[str]]:
    """一次取回全部依赖。返回 (label→数值, 缺失说明)。"""
    single = library.load_single()
    formulas, labels = [], []
    for dep in deps:
        record = single.get(dep["indicator"])
        if record is None:
            raise ValueError(f"指标未入库：{dep['indicator']}")
        formulas.append(library.render(record, {"code": code, "date": date,
                                                **(dep.get("params") or {})}))
        labels.append(dep["label"])
    if not formulas:
        return {}, []
    block = (engine.fetch_matrix([formulas], text_ok=True).get("values") or [[]])[0]
    values, missing = {}, []
    for label, raw in zip(labels, block):
        value = library.coerce(raw)
        if isinstance(value, (int, float)):
            values[label] = float(value)
        else:
            missing.append(label)
    return values, missing


def get_package(name: str, code: str = "", date: str = "", *,
                dims: dict | None = None, report_dates: list[str] | None = None,
                start: str | None = None, end: str | None = None,
                period: str = "daily", params: dict | None = None,
                export_path: str | None = None,
                auto_export_rows: int | None = 200) -> dict:
    """一次取回整块科目组合，组内衍生科目已算好。

    这是唯一的科目组合取数入口，供 CLI 与报告共用。历史行情支持周月聚合。
    """
    import time
    from pathlib import Path

    from ifind_excel_tool.indicators import aggregate, packages

    spec = definitions.load_packages().get(name)
    if spec is None:
        return {"ok": False, "error": f"没有名为「{name}」的科目组合"}
    if spec.get("kind") == "batch" or spec.get("kind") == "table":
        return {"ok": False, "indicator": name,
                "error": f"「{name}」是批量公式，请用 fetch_batch 指定输入参数"}
    period = period or "daily"
    if period not in ("daily", "weekly", "monthly"):
        return {"ok": False, "error": f"不支持的周期 {period}（支持 daily/weekly/monthly）"}
    resample_spec = spec.get("resample") or {}
    if period != "daily" and not resample_spec:
        return {"ok": False, "error": f"「{name}」不支持 period={period}（仅日线）"}

    if not code:
        return {"ok": False, "error": "code 必须提供"}
    if report_dates and not isinstance(report_dates, list):
        return {"ok": False, "error": "report_dates 必须是日期字符串数组"}

    probed = None
    if not date and not report_dates and spec.get("date_kind") == "report":
        probed = probe_latest_report(code)
        if not probed:
            return {"ok": False,
                    "error": f"无法确定最新报告期，请显式传 report_date（探测 {code} 失败）",
                    "hint": engine.ZERO_VALUE_HINT}
        date = probed

    started = time.time()
    expanded = packages.expand(name, code=code, report_date=date or None,
                               params=params, start=start, end=end,
                               report_dates=report_dates,
                               dims_override=dims)
    raw = engine.fetch_matrix(expanded["matrix"], text_ok=True)
    records = packages.shape(name, expanded, raw.get("values") or [])
    for record in records:
        record["code"] = code
    if period != "daily":
        records = aggregate.resample_ohlcv(records, period,
                                           resample_spec.get("field_map") or {})

    resp = {"ok": True, "indicator": name, "kind": "package", "code": code,
            "period": period, "fields": len(spec["fields"]),
            "rows": len(records), "records": records,
            "elapsed_seconds": round(time.time() - started, 2)}
    if probed:
        resp["report_date"] = probed
        resp["report_date_probed"] = True
    if report_dates:
        resp["report_dates"] = report_dates
    if _all_zero(records):
        resp["hint"] = engine.ZERO_VALUE_HINT
    if export_path or (auto_export_rows is not None and len(records) > auto_export_rows):
        target = export_path or str(
            Path(__file__).resolve().parent / "exports"
            / f"{name}_{code.replace('.', '_')}_{int(time.time())}.csv")
        resp["export"] = packages.to_csv(records, target)
        if not export_path:
            resp["records"] = records[:20]
            resp["truncated"] = True
    return resp


def _all_zero(records: list[dict]) -> bool:
    """判断一批结果是不是「看起来有数据但全为0」。

    这种情形常常是插件缓存而非上游没数据，值得提示一句；不做自动重试，
    以免把偶发情况做成通用兜底。
    """
    numbers = [v for record in records for k, v in record.items()
               if not k.endswith("__unit") and isinstance(v, (int, float))]
    return bool(numbers) and all(v == 0 for v in numbers)
