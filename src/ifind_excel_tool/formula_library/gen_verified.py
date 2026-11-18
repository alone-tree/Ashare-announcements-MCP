# -*- coding: utf-8 -*-
"""生成 verified-formulas.jsonl：只生成用户亲自确认的2条。"""
from __future__ import annotations
import json
from pathlib import Path
OUT = Path(__file__).resolve().parent / "verified-formulas.jsonl"
# 2026-11-18：曾自动生成40条，其中多数 path/name/source/unit 为 AI 填写或取自不可靠的 catalog，
# 已全部清除。新增记录只接受用户提供的 iFinD 界面原文与值，或人工确认过的实测结果。
RECORDS = [
  json.loads(r) for r in [
  ]
]
if RECORDS:
    OUT.write_text(chr(10).join(json.dumps(r, ensure_ascii=False) for r in RECORDS)+chr(10), encoding="utf-8")
    print(f"wrote {len(RECORDS)} records")
else:
    print("无用户确认的记录，不生成文件；请直接向 verified-formulas.jsonl 追加用户提供的公式")