# -*- coding: utf-8 -*-
"""场景取数：把 scenes/ 下的固定清单展开成公式矩阵，取数后按清单还原成带列名的结果。

设计边界（见 docs/iFinD场景清单与字段组方案-2026-11-23.md）：
- 场景只描述「要哪些数据、用什么默认值」，不含任何加工计算。
- 需要加工的分析由调用方取到数据后自行处理，不放这里。
- 多候选字段按 pick 规则取值，首版只支持 max。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCENES = Path(__file__).resolve().parent / "scenes"
LIBRARY = Path(__file__).resolve().parent / "formula_library"


def _load_library() -> dict[str, dict]:
    path = LIBRARY / "verified-formulas.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["indicator"]: r for r in rows}


def list_scenes() -> list[dict]:
    """列出可用场景及其字段数量，供 AI 知道自己能点什么。"""
    out = []
    for path in sorted(SCENES.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        item = {"name": spec.get("name") or path.stem,
                "description": spec.get("description", ""),
                "kind": spec.get("kind") or "matrix",
                "fields": len(spec.get("fields") or []),
                "dims": sorted((spec.get("dims") or {}).keys()),
                "defaults": spec.get("defaults") or {},
                "single_code_only": bool(spec.get("single_code_only"))}
        if item["kind"] == "table":
            item["inputs"] = spec.get("inputs") or []
            item["input_labels"] = spec.get("input_labels") or {}
        out.append(item)
    return out


def load_scene(name: str) -> dict:
    path = SCENES / f"{name}.json"
    if not path.is_file():
        available = [p.stem for p in sorted(SCENES.glob("*.json"))]
        raise ValueError(f"没有名为「{name}」的场景；可用：{available}")
    return json.loads(path.read_text(encoding="utf-8"))


def _fill(template: str, context: dict) -> str:
    text = template
    for placeholder in re.findall(r"\{(\w+)\}", template):
        if placeholder not in context:
            raise ValueError(f"公式缺少参数 {placeholder}：{template}")
        text = text.replace("{" + placeholder + "}", str(context[placeholder]))
    return text


def _combos(dims: dict) -> list[dict]:
    """维度笛卡尔积；无维度时返回单个空组合，即普通的一对一取数。"""
    combos = [{}]
    for key, values in dims.items():
        combos = [{**c, key: v} for c in combos for v in values]
    return combos


def _date_range(start: str, end: str) -> list[str]:
    """按自然日展开。周末与节假日由调用方按需过滤，此处不猜交易日历。"""
    from datetime import date, timedelta

    def parse(text: str) -> date:
        if text in ("today", "", None):
            return date.today()
        return date.fromisoformat(text)

    first, last = parse(start), parse(end)
    if first > last:
        raise ValueError(f"开始日期 {first} 晚于结束日期 {last}")
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def build(spec: dict, library: dict[str, dict], *, code: str,
          report_date: str | None = None, params: dict | None = None,
          start: str | None = None, end: str | None = None) -> dict:
    """把场景展开成待提交的公式与取数后的还原方案。

    返回 {"matrix": 二维公式列表, "plan": 还原方案, "combos": 维度组合}。
    有 dims.date_range 的场景（如行情）按自然日逐日展开为行。
    """
    dims = dict(spec.get("dims") or {})
    defaults = spec.get("defaults") or {}
    combos: list[dict]
    if dims.pop("date_range", False):
        days = _date_range(start or defaults.get("start") or "",
                           end or defaults.get("end") or "today")
        extra = _combos(dims) if dims else [{}]
        combos = [{**e, "date": d} for d in days for e in extra]
    else:
        combos = _combos(dims)
    base = {"code": code, "date": report_date or defaults.get("date") or "",
            **(params or {})}

    columns: list[tuple[int, int]] = []          # (字段序号, 候选序号)
    plan: list[dict] = []
    for field_index, field in enumerate(spec["fields"]):
        candidates = field.get("candidates") or [field["indicator"]]
        for candidate_index, indicator in enumerate(candidates):
            record = library.get(indicator)
            if record is None:
                raise ValueError(f"指标未入库：{indicator}（场景「{spec['name']}」的字段「{field['label']}」）")
            columns.append((field_index, candidate_index))
        plan.append({"label": field["label"],
                     "candidates": candidates,
                     "pick": field.get("pick"),
                     "unit": field.get("unit", "")})

    matrix = []
    for combo in combos:
        row = []
        for field_index, candidate_index in columns:
            field = spec["fields"][field_index]
            indicator = (field.get("candidates") or [field["indicator"]])[candidate_index]
            record = library[indicator]
            context = {**base, **(field.get("params") or {}), **combo}
            if not context.get("date"):
                context["date"] = defaults.get("date") or ""
            row.append(_fill(record["formula_template"], context))
        matrix.append(row)
    return {"matrix": matrix, "plan": plan, "columns": columns, "combos": combos}


def shape(spec: dict, plan: list[dict], columns: list[tuple[int, int]],
          combos: list[dict], values: list[list]) -> list[dict]:
    """把裸数值按还原方案变成带列名的记录。多候选取较大值并留下选择痕迹。"""
    records = []
    for combo, row in zip(combos, values):
        record = {**combo}
        column = 0
        for field in plan:
            count = len(field["candidates"])
            cells = row[column:column + count]
            column += count
            numbers = [(v, c) for v, c in zip(cells, field["candidates"]) if isinstance(v, (int, float))]
            if count == 1:
                value = cells[0] if cells else None
            elif not numbers:
                # 单候选之外：候选全是文本时取第一个非空值（本工具的多候选只用于数值科目）
                value = next((v for v in cells if v is not None), None)
            else:
                value, _ = max(numbers, key=lambda x: x[0])
            record[field["label"]] = value
            # 两值不同才留痕，正常数据不刷说明；便于与其他工具对数时解释差异
            if count > 1 and len({v for v, _ in numbers}) > 1:
                picked = max(numbers, key=lambda x: x[0])[1]
                record[f"{field['label']}__choices"] = {
                    "picked": picked,
                    "all": {c: v for v, c in zip(cells, field["candidates"])}}
            if field["unit"]:
                record[f"{field['label']}__unit"] = field["unit"]
        records.append(record)
    if spec.get("drop_non_trading_field"):
        records = _drop_non_trading(records, spec)
    # hidden 字段只用于筛选，不出现在结果里
    hidden = [f["label"] for f in plan if f.get("hidden")]
    if hidden:
        records = [{k: v for k, v in r.items() if k not in hidden} for r in records]
    return records


def to_csv(records: list[dict], path: str) -> dict:
    """把结果写成 CSV。用 utf-8-sig 保证 Excel 直接打开中文不乱码。

    多候选字段留痕产生的嵌套结构转成 JSON 文本，避免 CSV 里出现难以阅读的字典字面量。
    """
    import csv

    from pathlib import Path as _Path

    target = _Path(path)
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
            writer.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                             for k, v in record.items()})
    return {"path": str(target.resolve()), "rows": len(records), "columns": len(columns)}


def _drop_non_trading(records: list[dict], spec: dict) -> list[dict]:
    """剔除非交易日的空行，保留停牌日。

    按自然日展开时，周末与节假日的收盘价会取到前一个交易日的值，直接返回会让
    序列里混进重复价格。判据是清单里 drop_non_trading_field 指定的「不前推收盘价」：
    该值大于 0 表示当天市场开市，为 0 表示非交易日。

    不用成交量判定：停牌日与全天零成交日的成交量也是 0，用成交量会把真实开市
    但停牌的交易日一并删掉。口径与 market-data 一致——停牌日保留、量额记 0。
    """
    key = spec.get("drop_non_trading_field")
    if not key:
        return records
    kept = []
    for record in records:
        value = record.get(key)
        if isinstance(value, (int, float)) and value > 0:
            kept.append(record)
    return kept


# ---------------------------------------------------------------------------
# 表函数场景（kind = "table"）
#
# THS_RPT / THS_DR 这类函数一次返回整张表，与上面「一个指标一个值」的矩阵路径
# 完全不同：公式只有一条，数据由函数写到公式下方，行列由字段清单决定。
# 因此单独实现，不混进 build()/shape()。
# ---------------------------------------------------------------------------


def build_table(spec: dict, *, params: dict) -> dict:
    """把表函数场景拼成一条完整公式。

    清单字段：function 函数名、report 报表编码、inputs 输入参数名列表、
    fields 输出字段名列表、tail 固定尾部参数。

    实测（2026-11-24）：rows/cols 的具体数值不影响返回行数，函数按实际数据量输出；
    那个空参数不能省。公式全内联，不引用任何单元格。
    """
    report = spec["report"]
    pairs = []
    for name in spec["inputs"]:
        if name not in params:
            raise ValueError(f"缺少输入参数：{name}（场景「{spec['name']}」需要 {spec['inputs']}）")
        pairs.append(f'"{name}={params[name]}"')
    fields = "{" + ",".join(f'"{f}"' for f in spec["fields"]) + "}"
    tail = "".join(f',"{t}"' for t in (spec.get("tail") or []))
    if spec.get("function") == "THS_RPT":
        body = f'=@THS_RPT("{report}",' + ",".join(pairs) + f",{fields}{tail})"
    else:
        names = ",".join(spec["inputs"])
        values = ",".join(str(params[n]) for n in spec["inputs"])
        codes = ",".join(spec["fields"])
        body = f'=@THS_DR("{report}","{names}","{values}","{codes}")'
    return {"formula": body, "fields": list(spec["fields"]),
            "field_labels": spec.get("field_labels") or list(spec["fields"])}


def shape_table(spec: dict, raw_block, meta: dict | None = None) -> list[dict]:
    """把表函数写出的整块区域变成带列名的记录。

    实测落点：公式格起第 3 行为字段代码行、第 4 行为中文列名行、第 5 行起为数据。
    这里按「第一条全角数据行」自动定位，跳过前置的字段行与列名行。
    """
    labels = spec.get("field_labels") or spec.get("fields") or []
    width = len(spec.get("fields") or labels)

    def cells_of(row):
        return list(row) if isinstance(row, (list, tuple)) else [row]

    start = None
    for index, row in enumerate(raw_block):
        cells = cells_of(row)
        if len(cells) < width:
            continue
        head = cells[:width]
        if all(v is not None and (not isinstance(v, str) or v.strip()) for v in head):
            start = index
            break
    if start is None:
        return []

    records = []
    for row in raw_block[start:]:
        cells = cells_of(row)[:width]
        if all(v is None for v in cells):
            continue
        records.append({label: value for label, value in zip(labels, cells)})
    if meta:
        for record in records:
            record.update(meta)
    return records
