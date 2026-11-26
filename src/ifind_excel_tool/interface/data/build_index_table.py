# -*- coding: utf-8 -*-
"""从同花顺导出的指数Excel生成指数总表.csv。

用法：把用户重新导出的xlsx覆盖本目录的「同花顺股票指数.xlsx」，然后运行本脚本。

源文件的dimension标记有误，openpyxl读不到实际行数，因此直接解析xlsx底层XML。
遍历除「同花顺全部股票指数」外的每个类型sheet，按证券代码去重，
新增「所在类型」（多个类型用、连接）和「常用」两列，其余字段原样保留。

「常用」标记来自同目录的「常用指数基本信息.csv」，代码在其中标1。
"""
from __future__ import annotations

import csv
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "同花顺股票指数.xlsx"
COMMON = HERE / "常用指数基本信息.csv"
OUT = HERE / "指数总表.csv"

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
BAD_CODES = {"数据来源：同花顺iFinD", "数据来源:同花顺iFinD"}
TOTAL_SHEET = "同花顺全部股票指数"


def _sheet_paths(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {r.get("Id"): r.get("Target") for r in rels}
    out = []
    for sh in wb.find("m:sheets", NS):
        path = "xl/" + relmap[sh.get(RID)].lstrip("/").replace("xl/", "")
        out.append((sh.get("name"), path))
    return out


def _rows(z: zipfile.ZipFile, path: str) -> list[dict[str, str]]:
    root = ET.fromstring(z.read(path))
    rows = []
    for row in root.findall(".//m:sheetData/m:row", NS):
        cells = {}
        for cell in row.findall("m:c", NS):
            col = re.match(r"[A-Z]+", cell.get("r")).group()
            inline = cell.find("m:is/m:t", NS)
            value = cell.find("m:v", NS)
            text = inline.text if inline is not None else (value.text if value is not None else "")
            cells[col] = text or ""
        rows.append(cells)
    return rows


def _common_codes() -> set[str]:
    with COMMON.open(encoding="utf-8-sig", newline="") as f:
        return {row["证券代码"].strip() for row in csv.DictReader(f) if row.get("证券代码", "").strip()}


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"找不到源文件：{SOURCE}")
    common = _common_codes()
    types: dict[str, list[str]] = defaultdict(list)
    records: dict[str, dict[str, str]] = {}
    total_sheet_codes: set[str] = set()
    per_sheet_counts: dict[str, int] = {}

    with zipfile.ZipFile(SOURCE) as z:
        for name, path in _sheet_paths(z):
            rows = _rows(z, path)
            if not rows:
                continue
            header = rows[0]
            code_col = next((c for c, v in header.items() if v == "证券代码"), "A")
            valid = lambda c: c and c not in BAD_CODES and not c.startswith("数据来源")
            codes = [r.get(code_col, "").strip() for r in rows[1:]]
            codes = [c for c in codes if valid(c)]
            per_sheet_counts[name] = len(codes)

            if name == TOTAL_SHEET:
                total_sheet_codes = set(codes)
                continue

            for row in rows[1:]:
                code = row.get(code_col, "").strip()
                if not valid(code):
                    continue
                types[code].append(name)
                if code not in records:
                    record = {}
                    for col, key in header.items():
                        if key:  # 跳过空表头列
                            record[key] = row.get(col, "").strip()
                    records[code] = record

    # 加两列：所在类型、常用
    for code, record in records.items():
        record["所在类型"] = "、".join(types[code])
        record["常用"] = "1" if code in common else ""

    # 列顺序：原字段顺序 + 新列
    with zipfile.ZipFile(SOURCE) as z:
        first_path = next(p for n, p in _sheet_paths(z) if n != TOTAL_SHEET)
        header = _rows(z, first_path)[0]
    columns = [v for v in header.values() if v] + ["所在类型", "常用"]

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for code in sorted(records):
            writer.writerow(records[code])

    # 交叉校验
    type_total = sum(n for name, n in per_sheet_counts.items() if name != TOTAL_SHEET)
    print(f"类型sheet数：{len(per_sheet_counts) - 1}")
    print(f"类型sheet条数合计（含重复）：{type_total}")
    print(f"去重后指数数：{len(records)}")
    print(f"合计sheet条数：{len(total_sheet_codes)}")
    print(f"合计sheet与各类型并集一致：{total_sheet_codes == set(records)}")
    print(f"常用标记数：{sum(1 for r in records.values() if r['常用'])} / 常用表{len(common)}条")
    print(f"输出：{OUT}")


if __name__ == "__main__":
    main()
