# -*- coding: utf-8 -*-
"""ifind_excel_tool 极薄 CLI：只提供 lookup / run / text 三个命令。

设计意图：CLI 不做场景封装，只暴露库检索与原始执行能力。
AI 需要数据时先 lookup 查公式，再写一次性脚本调 engine；
只有反复使用的场景才沉淀为 recipes/ 下的脚本。

用法（stdin JSON → stdout JSON，顶层字段 cmd）：
  {"cmd":"lookup","keyword":"市盈率","limit":5}
  {"cmd":"run","matrix":[[=@thsiFinD(...)],...],"timeout":300}
  {"cmd":"text","formulas":["=@thsiFinD(...)"]}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ifind_excel_tool import engine

LIB = Path(__file__).resolve().parent / "formula_library"


def _load(name: str) -> list[dict]:
    path = LIB / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def lookup(req: dict) -> dict:
    kw = (req.get("keyword") or "").strip()
    limit = int(req.get("limit") or 5)
    if not kw:
        return {"ok": False, "error": "keyword 不能为空"}
    verified = _load("verified-formulas.jsonl")
    general = _load("general-notes.jsonl")
    hits = []
    for r in verified:
        haystack = " ".join([r["path"], r["name"], r["indicator"],
                             " ".join(r.get("aliases") or []), r.get("definition", "")])
        if all(k in haystack for k in kw.split()):
            item = {k: r[k] for k in ("path", "name", "indicator", "formula_template",
                                       "parameters", "unit", "verification", "notes")}
            item["general_notes"] = [{"id": g["id"], "note": g["note"]}
                                     for g in general if r["path"].startswith(g["scope"])]
            hits.append(item)
    return {"ok": True, "keyword": kw, "source": "verified", "hits": hits[:limit],
            "total": len(hits)}


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


CMDS = {"lookup": lookup, "run": run, "text": text}


def main() -> None:
    req = json.loads(sys.stdin.read())
    cmd = req.get("cmd")
    if cmd not in CMDS:
        resp = {"ok": False, "error": f"未知 cmd：{cmd}；支持 {list(CMDS)}"}
    else:
        try:
            resp = CMDS[cmd](req)
        except Exception as exc:
            resp = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(resp, ensure_ascii=False))


if __name__ == "__main__":
    main()
