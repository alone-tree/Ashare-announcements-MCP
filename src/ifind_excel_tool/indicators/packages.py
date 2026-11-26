# -*- coding: utf-8 -*-
"""第二块 科目组合：把若干科目打成一个包，一次取回。

一块组合 = 一组字段 + 维度 + 默认值。它在检索和调用上和单个科目地位相同，
调用方看到的只是「一个能一次取回多条数据的科目」。

本模块只做两件事：把组合展开成待提交的公式矩阵、把取回的结果还原成记录。
不碰 Excel，不关心一个字段底层是原始公式还是衍生科目。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ifind_excel_tool.formulas import library
from ifind_excel_tool.indicators import definitions

HERE = Path(__file__).resolve().parent


def _combos(dims: dict) -> list[dict]:
    """维度笛卡尔积；无维度时返回单个空组合，即普通的一对一取数。"""
    combos = [{}]
    for key, values in dims.items():
        combos = [{**c, key: v} for c in combos for v in values]
    return combos


def date_range(start: str, end: str) -> list[str]:
    """按自然日展开。周末与节假日由调用方按需过滤，此处不猜交易日历。"""
    from datetime import date, timedelta

    def parse(text: str) -> date:
        if text in ("today", "", None):
            return date.today()
        rolling = re.fullmatch(r"today-(\d+)d", str(text))
        if rolling:
            return date.today() - timedelta(days=int(rolling.group(1)))
        return date.fromisoformat(text)

    first, last = parse(start), parse(end)
    if first > last:
        raise ValueError(f"开始日期 {first} 晚于结束日期 {last}")
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def expand_dim_default(token):
    """把维度默认值里的占位符换成实际取值。

      __recent_years:5__      最近5个年度（含当年），用于分红
      __recent_year_ends:5__  最近5个年末，严格早于今天，用于历史估值
    """
    from datetime import date

    if not isinstance(token, str) or not token.startswith("__"):
        return token if isinstance(token, list) else [token]
    today = date.today()
    years = re.fullmatch(r"__recent_years:(\d+)__", token)
    if years:
        return [str(today.year - offset) for offset in range(int(years.group(1)))]
    ends = re.fullmatch(r"__recent_year_ends:(\d+)__", token)
    if ends:
        newest = today.year if today.isoformat().endswith("-12-31") else today.year - 1
        return [f"{newest - offset}-12-31" for offset in range(int(ends.group(1)))]
    raise ValueError(f"不认识的维度默认值占位符：{token}")


def resolve_date(text: str) -> str:
    """把 today / today-Nd 这类占位符换成具体日期；具体日期原样返回。"""
    from datetime import date, timedelta

    if not text:
        return ""
    if text == "today":
        return date.today().isoformat()
    rolling = re.fullmatch(r"today-(\d+)d", str(text))
    if rolling:
        return (date.today() - timedelta(days=int(rolling.group(1)))).isoformat()
    return text


def _field_refs(field: dict) -> list[dict]:
    """一个字段可能对应多个候选科目；返回每个候选的取数描述。"""
    if field.get("derived"):
        return [{"kind": "derived", "name": field["derived"], "params": {}}]
    candidates = field.get("candidates") or [field["indicator"]]
    return [{"kind": "formula", "code": code, "params": field.get("params") or {}}
            for code in candidates]


def expand(name: str, *, code: str, report_date: str | None = None,
           params: dict | None = None, start: str | None = None,
           end: str | None = None, report_dates: list[str] | None = None,
           dims_override: dict | None = None) -> dict:
    """把科目组合展开成待提交的公式矩阵与还原方案。

    返回 {"matrix": 二维公式列表, "plan": 还原方案, "combos": 维度组合}。
    字段若引用衍生科目，其依赖在这里一并展开成公式列后计算，调用方不必关心。
    """
    spec = definitions.load_packages()[name]
    single = library.load_single()
    derived = definitions.load_derived()

    dims = dict(spec.get("dims") or {})
    defaults = spec.get("defaults") or {}
    if dims_override:
        dims.update(dims_override)
    for key, value in list(dims.items()):
        if isinstance(value, (list, tuple)) and len(value) == 1 \
                and isinstance(value[0], str) and value[0].startswith("__"):
            dims[key] = expand_dim_default(value[0])

    combos: list[dict]
    if report_dates:
        extra_dims = {k: v for k, v in dims.items() if k != "date_range"}
        extra = _combos(extra_dims) if extra_dims else [{}]
        combos = [{**e, "date": d} for d in report_dates for e in extra]
    elif dims.pop("date_range", False):
        days = date_range(start or defaults.get("start") or "",
                          end or defaults.get("end") or "today")
        extra = _combos(dims) if dims else [{}]
        combos = [{**e, "date": d} for d in days for e in extra]
    else:
        combos = _combos(dims)

    user_params = dict(params or {})
    if "adjust" in user_params:
        user_params.setdefault("type", user_params["adjust"])
    base = {"code": code,
            "date": resolve_date(report_date or defaults.get("date") or ""),
            **user_params}

    # 展开：每个字段产出若干「计算单元」。原始公式直接一列，衍生科目展开成依赖列。
    units: list[dict] = []          # 一次公式行的构成
    plan: list[dict] = []
    for field in spec["fields"]:
        refs = _field_refs(field)
        plan.append({"label": field["label"], "refs": refs,
                     "pick": field.get("pick"), "unit": field.get("unit", ""),
                     "hidden": bool(field.get("hidden")),
                     "group": field.get("group", "")})
        if len(refs) > 1:
            for ref in refs:
                units.append({"label": field["label"], "ref": ref})
            continue
        ref = refs[0]
        if ref["kind"] == "derived":
            definition = derived[ref["name"]]
            for dep in definition.get("deps") or []:
                if dep["indicator"] not in single:
                    raise ValueError(f"指标未入库：{dep['indicator']}")
                units.append({"label": field["label"], "ref": {"kind": "formula",
                                                              "code": dep["indicator"],
                                                              "params": dep.get("params") or {}}})
        else:
            if ref["code"] not in single:
                raise ValueError(f"指标未入库：{ref['code']}（组合「{name}」的字段「{field['label']}」）")
            units.append({"label": field["label"], "ref": ref})

    matrix = []
    for combo in combos:
        row = []
        for unit in units:
            if unit["ref"]["kind"] == "derived":
                continue
            code_ = unit["ref"]["code"]
            context = {**base, **(unit["ref"].get("params") or {}), **combo,
                       **{k: v for k, v in user_params.items() if k in ("type", "adjust")}}
            if not context.get("date"):
                context["date"] = defaults.get("date") or ""
            row.append(library.render(single[code_], context))
        matrix.append(row)
    return {"matrix": matrix, "plan": plan, "combos": combos,
            "units": units, "derived": derived}


def shape(spec_name: str, expanded: dict, values: list[list]) -> list[dict]:
    """把裸数值按还原方案变成带列名的记录。多候选取较大值并留下选择痕迹。"""
    plan = expanded["plan"]
    units = expanded["units"]
    derived = expanded["derived"]

    # 按字段把列值归位。行比预期短时缺的位置给 None，不抛越界。
    def column_values(row: list) -> dict[str, list]:
        grouped: dict[str, list] = {}
        for position, unit in enumerate(units):
            cell = row[position] if position < len(row) else None
            grouped.setdefault(unit["label"], []).append(library.coerce(cell))
        return grouped

    records = []
    for combo, row in zip(expanded["combos"], values):
        raw = column_values(row)
        record = {**combo}
        for field in plan:
            label = field["label"]
            refs = field["refs"]
            if len(refs) > 1:
                cells = raw.get(label, [])
                numbers = [(v, r["code"]) for v, r in zip(cells, refs)
                           if isinstance(v, (int, float))]
                value = max(numbers, key=lambda x: x[0])[0] if numbers else 0
                if numbers and len({v for v, _ in numbers}) > 1:
                    record[f"{label}__choices"] = {r["code"]: v for v, r in zip(cells, refs)}
            elif refs[0]["kind"] == "derived":
                definition = derived[refs[0]["name"]]
                deps = definition.get("deps") or []
                cells = raw.get(label, [])
                local = {}
                for dep, value in zip(deps, cells):
                    if isinstance(value, (int, float)):
                        local[dep["label"]] = float(value)
                value = _compute(definition, local)
            else:
                cells = raw.get(label, [])
                value = cells[0] if cells else None
            record[label] = value
            if field["unit"]:
                record[f"{label}__unit"] = field["unit"]
        records.append(record)
    return records


def _compute(definition: dict, values: dict):
    """按定义算派生值；缺依赖或分母为零时给 None，不静默回退成 0。"""
    from ifind_excel_tool.indicators.fetch import evaluate

    return evaluate(definition, values)


def to_csv(records: list[dict], path: str) -> dict:
    """把结果写成 CSV。用 utf-8-sig 保证 Excel 直接打开中文不乱码。"""
    import csv

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for record in records:
        for key in record:
            if key not in columns:
                columns.append(key)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow({k: (json.dumps(v, ensure_ascii=False)
                                 if isinstance(v, (dict, list)) else v)
                             for k, v in record.items()})
    return {"path": str(target.resolve()), "rows": len(records), "columns": len(columns)}
