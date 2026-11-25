# -*- coding: utf-8 -*-
"""统一指标取数：按指标定义自动取齐依赖、完成计算，返回加工好的结果。

分工（见 docs/iFinD-CLI统一指标库与搜索框架方案-2026-11-25.md）：
  indicator_index.py  搜指标、给用法（不取数）
  indicators.py       按定义取数（本模块），调用方不接触 Excel 公式
  engine.py           Excel COM 执行层

三条纪律：
- 依赖合并取数：一个指标组或派生指标的多个依赖，一次矩阵提交，不重复跑 Excel。
- 算术表达式只走白名单求值，不执行任意代码。表达式里出现的名字必须是已取到的依赖。
- 分母为零、依赖缺失时该值不可用并给原因，不悄悄回退成 0 或绝对值。
"""
from __future__ import annotations

import ast
import operator
from pathlib import Path

from ifind_excel_tool import engine, scenes as _scenes
from ifind_excel_tool import indicator_index as _index

LIBRARY = Path(__file__).resolve().parent / "formula_library"

_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_expr(expr: str, names: dict[str, float]) -> float:
    """对只含四则运算与变量名的表达式求值。

    用 ast 白名单而非 eval：表达式来自库文件，仍然不该有能力执行任意代码。
    变量名必须已在 names 里，否则报错指出缺哪个依赖。
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as error:
        raise ValueError(f"派生算式语法错误：{expr}（{error}）") from error

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


def _load_derived() -> dict[str, dict]:
    path = LIBRARY / "derived-indicators.jsonl"
    if not path.is_file():
        return {}
    import json
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return {r["name"]: r for r in rows}


def _load_groups() -> dict[str, dict]:
    path = LIBRARY / "indicator-groups.jsonl"
    if not path.is_file():
        return {}
    import json
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return {r["name"]: r for r in rows}


# ---------------------------------------------------------------------------
# 原始指标：单格公式与多候选取值
# ---------------------------------------------------------------------------

def _formula_for(indicator: str, code: str, date: str, params: dict | None = None) -> str:
    """把公式库里的模板填成可提交的一行公式。"""
    library = _scenes._load_library()
    record = library.get(indicator)
    if record is None:
        raise ValueError(f"指标未入库：{indicator}")
    context = {"code": code, "date": date or "", **(params or {})}
    # 模板里出现但调用方没给值的参数，用库里登记的默认值；库里也没默认就报错，
    # 不猜参数值（项目铁律：iFinD 参数严禁猜测）。
    for param in record.get("parameters") or []:
        name = param.get("name") or ""
        if not name or param.get("default") is None:
            continue
        context.setdefault(name.lower(), param["default"])
    return _scenes._fill(record["formula_template"], context)


def _fetch_raw(indicator: str, code: str, date: str,
               params: dict | None = None) -> dict:
    """取一个原始指标的单值。文本指标走 text 通道。"""
    library = _scenes._load_library()
    record = library.get(indicator)
    if record is None:
        raise ValueError(f"指标未入库：{indicator}")
    formula = _formula_for(indicator, code, date, params)
    if (record.get("reading_mode") or "matrix") == "text":
        result = engine.fetch_formulas([formula], text_ok=True)
        values = result.get("values") or []
        raw = values[0] if values else None
    else:
        result = engine.fetch_matrix([[formula]], text_ok=True)
        block = result.get("values") or []
        raw = block[0][0] if block and block[0] else None
    return {"indicator": indicator, "value": _coerce(raw), "unit": record.get("unit", "")}


def _coerce(value):
    import re
    if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value.strip()):
        return float(value.strip())
    return value


# ---------------------------------------------------------------------------
# 派生指标：取齐依赖后按算式计算
# ---------------------------------------------------------------------------

def _resolve_deps(deps: list[dict], code: str, date: str) -> tuple[dict, list[str]]:
    """一次取回全部依赖。返回 (label→数值, 缺失说明)。"""
    formulas, labels = [], []
    for dep in deps:
        formulas.append(_formula_for(dep["indicator"], code, date, dep.get("params")))
        labels.append(dep["label"])
    if not formulas:
        return {}, []
    result = engine.fetch_matrix([formulas], text_ok=True)
    block = (result.get("values") or [[]])[0]
    values, missing = {}, []
    for label, raw in zip(labels, block):
        value = _coerce(raw)
        if isinstance(value, (int, float)):
            values[label] = float(value)
        else:
            missing.append(label)
    return values, missing


def _compute_derived(definition: dict, values: dict) -> dict:
    """按定义算派生值。分母为零等不可用情形给原因，不回退。"""
    expr = definition["expr"]
    try:
        number = _eval_expr(expr, values)
    except ZeroDivisionError:
        return {"ok": False, "error": f"{definition['name']}：分母为零，该值不可用"}
    except ValueError as error:
        return {"ok": False, "error": f"{definition['name']}：{error}"}
    decimals = definition.get("decimals")
    if isinstance(decimals, int) and decimals >= 0:
        number = round(number, decimals)
    return {"ok": True, "value": number}


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def get(indicator: str, code: str = "", date: str = "",
        params: dict | None = None) -> dict:
    """按指标名或指标码取数。类型自动分派，调用方不用判断。"""
    entry = _index.resolve(indicator, code)
    kind = entry["kind"]

    if kind == "special":
        from ifind_excel_tool import cli as _cli
        latest = _cli._probe_report_date(code)
        if not latest:
            return {"ok": False, "indicator": entry["name"],
                    "error": f"无法确定最新报告期（探测 {code} 失败）"}
        return {"ok": True, "indicator": entry["name"], "code": code,
                "value": latest, "unit": "报告期"}

    if kind == "scene" or kind == "table":
        from ifind_excel_tool import cli as _cli
        payload = {"cmd": "fetch_scene", "scene": entry["indicator"], "code": code,
                   "report_date": date} if kind == "scene" else None
        if kind == "table":
            return {"ok": False, "indicator": entry["name"],
                    "error": f"「{entry['name']}」是报表函数整表，需要专有输入参数，"
                             f"请用 fetch_scene 指定 inputs：{entry.get('required_inputs')}"}
        return _cli.fetch_scene(payload)

    if kind == "group":
        return get_group(entry["name"], code=code, date=date)

    if kind == "select":
        # 多候选：一次取全部候选，取较大值，与场景层同一套规则
        library = _scenes._load_library()
        formulas = [_formula_for(c, code, date, params) for c in entry["candidates"]]
        result = engine.fetch_matrix([formulas], text_ok=True)
        block = (result.get("values") or [[]])[0]
        numbers = [(v, c) for v, c in zip((_coerce(x) for x in block), entry["candidates"])
                   if isinstance(v, (int, float))]
        if not numbers:
            return {"ok": True, "indicator": entry["name"], "value": 0,
                    "unit": entry.get("unit", ""), "candidates": entry["candidates"]}
        value, picked = max(numbers, key=lambda x: x[0])
        out = {"ok": True, "indicator": entry["name"], "value": value,
               "unit": entry.get("unit", ""), "picked": picked,
               "candidates": entry["candidates"]}
        if len({v for v, _ in numbers}) > 1:
            out["choices"] = {c: v for v, c in zip((_coerce(x) for x in block),
                                                   entry["candidates"])}
        return out

    if kind == "derived":
        definition = _load_derived()[entry["name"]]
        values, missing = _resolve_deps(definition.get("deps") or [], code, date)
        if missing:
            return {"ok": False, "indicator": entry["name"],
                    "error": f"缺依赖：{'、'.join(missing)}，{entry['name']}不可用"}
        computed = _compute_derived(definition, values)
        if not computed.get("ok"):
            return {"ok": False, "indicator": entry["name"], "error": computed["error"]}
        return {"ok": True, "indicator": entry["name"], "value": computed["value"],
                "unit": definition.get("unit", ""), "decimals": definition.get("decimals"),
                "deps": values}

    # excel 原始型
    if not code:
        return {"ok": False, "indicator": entry["name"], "error": "code 必须提供"}
    fetched = _fetch_raw(entry["indicator"], code, date, params)
    return {"ok": True, "indicator": entry["name"], "code": code, "date": date,
            "value": fetched["value"], "unit": fetched["unit"],
            "indicator_code": fetched["indicator"]}


def get_group(name: str, code: str = "", date: str = "") -> dict:
    """一次取回整组指标。成员可以是原始型、派生型，也可以是另一个组。"""
    groups = _load_groups()
    members = groups[name]["members"]
    # 先展开到底层依赖，合并成一次 Excel 提交
    raw_needed: dict[str, dict] = {}
    derived_needed: dict[str, dict] = {}

    def collect(member: str, chain: list[str]):
        entry = _index.resolve(member, code)
        if entry["kind"] == "group":
            if entry["name"] in chain:
                raise ValueError(f"指标组循环嵌套：{' → '.join(chain + [entry['name']])}")
            for sub in groups[entry["name"]]["members"]:
                collect(sub, chain + [entry["name"]])
        elif entry["kind"] == "derived":
            definition = _load_derived()[entry["name"]]
            derived_needed[entry["name"]] = definition
            for dep in definition.get("deps") or []:
                raw_needed[dep["indicator"]] = dep
        elif entry["kind"] == "select":
            for candidate in entry["candidates"]:
                raw_needed[candidate] = {"label": candidate, "indicator": candidate}
        else:
            raw_needed[entry["indicator"]] = {"label": entry["name"],
                                              "indicator": entry["indicator"]}

    for member in members:
        collect(member, [name])

    # 合并成一次矩阵取数
    library = _scenes._load_library()
    indicators = list(raw_needed)
    formulas = [_formula_for(i, code, date) for i in indicators]
    values: dict[str, float] = {}
    missing: list[str] = []
    if formulas:
        result = engine.fetch_matrix([formulas], text_ok=True)
        block = (result.get("values") or [[]])[0]
        for indicator, raw in zip(indicators, block):
            value = _coerce(raw)
            if isinstance(value, (int, float)):
                values[indicator] = float(value)
            else:
                missing.append(indicator)

    def value_of(member: str):
        entry = _index.resolve(member, code)
        if entry["kind"] == "group":
            return {sub: value_of(sub) for sub in groups[entry["name"]]["members"]}
        if entry["kind"] == "derived":
            definition = _load_derived()[entry["name"]]
            local = {dep["label"]: values.get(dep["indicator"]) for dep in definition["deps"]}
            if any(v is None for v in local.values()):
                return None
            computed = _compute_derived(definition, local)
            return computed.get("value") if computed.get("ok") else None
        if entry["kind"] == "select":
            candidates = [(values.get(c), c) for c in entry["candidates"]
                          if values.get(c) is not None]
            return max(candidates, key=lambda x: x[0])[0] if candidates else None
        return values.get(entry["indicator"])

    result_records = {member: value_of(member) for member in members}
    out = {"ok": True, "indicator": name, "code": code, "date": date,
           "members": result_records}
    if missing:
        out["missing"] = [library[i].get("name", i) for i in missing]
    return out
