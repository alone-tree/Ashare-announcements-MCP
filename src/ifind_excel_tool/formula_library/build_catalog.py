# -*- coding: utf-8 -*-
"""从 iFinD 插件自带 excel_description.dat 生成全量指标索引 catalog.jsonl。

来源：C:\Program Files\iFinD\etc\datacube\excel_description.dat（SQLite，30281行）。
每行保留定义/算法/参数原文/来源/单位五段，并解析出参数位置与枚举。
只做忠实转录，不判断当前插件是否仍支持，不推测参数位序。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

DB = Path("C:/Program Files/iFinD/etc/datacube/excel_description.dat")
OUT = Path(__file__).resolve().parent / "catalog.jsonl"

PARAM_RE = re.compile(r"^\s{4,}(\w+)[:：](.*)$")
ENUM_RE = re.compile(r"^\s+(\S+?)[－-]\s*(.+)$")
FORMULA_RE = re.compile(r"Formula：\s*([A-Za-z_][\w\.]*)")


def section(body: str, name: str) -> str:
    m = re.search(name + r"：\s*(.*?)(?=\n\S|\Z)", body, re.S)
    return m.group(1).strip() if m else ""


def parse_params(body: str) -> list[dict]:
    seg = section(body, "参数")
    out: list[dict] = []
    current: dict | None = None
    for line in seg.split("\n"):
        m = PARAM_RE.match(line)
        if m:
            current = {"name": m.group(1), "raw": m.group(2).strip(),
                       "options": [], "position": len(out)}
            out.append(current)
            continue
        e = ENUM_RE.match(line)
        if e and current is not None:
            current["options"].append({"value": e.group(1).strip(),
                                        "meaning": e.group(2).strip()})
    return out


def main() -> None:
    con = sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)
    rows = con.execute("select descbody from description").fetchall()
    count = 0
    with OUT.open("w", encoding="utf-8", newline="\n") as stream:
        for (body,) in rows:
            body = body or ""
            fm = FORMULA_RE.search(body)
            record = {
                "indicator": fm.group(1) if fm else "",
                "definition": section(body, "定义"),
                "algorithm": section(body, "算法"),
                "parameters_raw": section(body, "参数"),
                "parameters": parse_params(body),
                "source": section(body, "来源"),
                "unit": section(body, "单位"),
                "ui_path": re.search(r"(_同花顺函数库_[^\n]*)", body).group(1).strip()
                           if re.search(r"(_同花顺函数库_[^\n]*)", body) else "",
                "verification": "unverified",
                "origin": "excel_description.dat",
            }
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    print(f"wrote {count} records to {OUT}")


if __name__ == "__main__":
    main()
