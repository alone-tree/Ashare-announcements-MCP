# -*- coding: utf-8 -*-
"""第一块 公式录入：iFinD 公式的存放、读取与渲染。

这块只管「公式本身」：录了什么公式、怎么把模板填成可执行的公式、取回来怎么还原。
不判断业务含义，不知道有毛利率这种东西，也不碰 Excel。

两类公式：
  单点公式  一条公式取一个值（如某天某股前复权收盘价）。存 single.jsonl。
  批量公式  一条公式让函数把整张表写到下方（如指数成分股）。存 batch/*.json。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


def load_single() -> dict[str, dict]:
    """全部单点公式，按指标码索引。"""
    path = HERE / "single.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return {row["indicator"]: row for row in rows}


def load_notes() -> list[dict]:
    """通用说明：按公式路径前缀生效的注意事项。"""
    path = HERE / "notes.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def list_batch() -> list[dict]:
    """全部批量公式定义。"""
    path = HERE / "batch.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_batch(name: str) -> dict:
    for spec in list_batch():
        if spec.get("name") == name:
            return spec
    available = [s.get("name") for s in list_batch()]
    raise ValueError(f"没有名为「{name}」的批量公式；可用：{available}")


def coerce(value):
    """iFinD 部分指标把数字当文本返回（如 "124154176.7600"），统一转成 float。
    只认纯数字串，名称类文本（含字母、逗号、百分号等）原样保留。"""
    if isinstance(value, str) and _NUMERIC.match(value.strip()):
        return float(value)
    return value


def fill(template: str, context: dict) -> str:
    """把公式模板里的 {占位符} 换成实际值。缺参数时报错，不猜默认值。"""
    text = template
    for placeholder in re.findall(r"\{(\w+)\}", template):
        if placeholder not in context:
            raise ValueError(f"公式缺少参数 {placeholder}：{template}")
        text = text.replace("{" + placeholder + "}", str(context[placeholder]))
    return text


def normalize_code(code: str) -> str:
    """港股代码五位转四位（00700.HK→0700.HK）。实测五位在行情与估值公式返回0。"""
    if (code or "").upper().endswith(".HK"):
        digits = code.split(".", 1)[0]
        if len(digits) == 5 and digits.startswith("0"):
            return digits[1:] + ".HK"
    return code


def render(record: dict, context: dict) -> str:
    """按库内登记的参数默认值补全上下文，再填模板。

    调用方没给、库里也没登记默认值的参数一律报错——iFinD 参数严禁猜测。
    """
    merged = dict(context)
    merged["code"] = normalize_code(str(merged.get("code") or ""))
    for param in record.get("parameters") or []:
        name = param.get("name") or ""
        if not name or param.get("default") is None:
            continue
        merged.setdefault(name.lower(), param["default"])
    return fill(record["formula_template"], merged)


def build_batch(spec: dict, params: dict) -> dict:
    """把批量公式定义拼成一条完整公式。

    字段：function 函数名、report 报表编码、inputs 输入参数名、fields 输出字段名、tail 尾部参数。
    实测（2026-11-24）：rows/cols 的数值不影响返回行数，函数按实际数据量输出；
    那个空参数不能省。公式全内联，不引用单元格。
    """
    report = spec["report"]
    missing = [n for n in spec["inputs"] if n not in params]
    if missing:
        raise ValueError(f"缺少输入参数：{missing}（「{spec['name']}」需要 {spec['inputs']}）")
    if spec.get("function") == "THS_RPT":
        pairs = [f'"{name}={params[name]}"' for name in spec["inputs"]]
        fields = "{" + ",".join(f'"{f}"' for f in spec["fields"]) + "}"
        tail = "".join(f',"{t}"' for t in (spec.get("tail") or []))
        body = f'=@THS_RPT("{report}",' + ",".join(pairs) + f",{fields}{tail})"
    else:
        names = ",".join(spec["inputs"])
        values = ",".join(str(params[n]) for n in spec["inputs"])
        codes = ",".join(spec["fields"])
        body = f'=@THS_DR("{report}","{names}","{values}","{codes}")'
    return {"formula": body, "fields": list(spec["fields"]),
            "field_labels": spec.get("field_labels") or list(spec["fields"])}


def shape_batch(spec: dict, raw_block, meta: dict | None = None) -> list[dict]:
    """把批量公式写出的整块区域变成带列名的记录。

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
