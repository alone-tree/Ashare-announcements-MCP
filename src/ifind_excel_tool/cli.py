# -*- coding: utf-8 -*-
"""ifind_excel_tool 极薄 CLI：只提供 lookup / run / text / close 四个命令。

设计意图：CLI 不做场景封装，只暴露库检索与原始执行能力。
AI 需要数据时先 lookup 查公式，再写一次性脚本调 engine；
只有反复使用的场景才沉淀为 recipes/ 下的脚本。

用法（stdin JSON → stdout JSON，顶层字段 cmd）：
  {"cmd":"lookup","keyword":"市盈率","limit":5}
  {"cmd":"run","matrix":[[=@thsiFinD(...)],...],"timeout":300}
  {"cmd":"text","formulas":["=@thsiFinD(...)"]}
  {"cmd":"close"}
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


# 匹配强度：数字越小越靠前。用途是让 AI 一眼看出哪条才是用户要的科目，
# 避免「搜净资产取第一条却拿到归母口径」这类错。
MATCH_EXACT_INDICATOR = 1   # 指标码完全相同
MATCH_EXACT_NAME = 2        # 正式名称完全相同
MATCH_EXACT_ALIAS = 3       # 别名完全相同
MATCH_NAME_CONTAINS = 4     # 正式名称包含
MATCH_ALIAS_CONTAINS = 5    # 别名包含
MATCH_INDICATOR_CONTAINS = 6  # 指标码包含
MATCH_DEFINITION = 7        # 仅定义正文命中


def _match_rank(record: dict, keyword: str) -> int | None:
    """返回该记录对关键词的匹配强度；不命中返回 None。

    多词关键词（空格分隔）沿用历史语义：全部词都要出现在检索范围内才命中，
    匹配强度按整串关键词在字段中的位置判定。
    """
    words = keyword.split()
    name = (record.get("name") or "").strip()
    aliases = [a.strip() for a in (record.get("aliases") or [])]
    indicator = record.get("indicator") or ""
    definition = record.get("definition") or ""
    path = record.get("path") or ""

    # 全部词必须出现在合并检索范围内，否则不命中（保持原有可用性）
    haystack = " ".join([path, name, indicator, " ".join(aliases), definition])
    if not all(w in haystack for w in words):
        return None

    # 单字关键词才能做完全匹配判定；多词按包含处理
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


def lookup(req: dict) -> dict:
    kw = (req.get("keyword") or "").strip()
    limit = int(req.get("limit") or 5)
    offset = max(0, int(req.get("offset") or 0))
    if not kw:
        return {"ok": False, "error": "keyword 不能为空"}
    verified = _load("verified-formulas.jsonl")
    general = _load("general-notes.jsonl")
    ranked = []
    for order, r in enumerate(verified):
        rank = _match_rank(r, kw)
        if rank is None:
            continue
        item = {k: r[k] for k in ("path", "name", "indicator", "formula_template",
                                   "parameters", "unit", "verification", "notes")}
        # reading_mode 决定该走数值通道还是文本通道，缺了它 AI 会用错命令
        item["reading_mode"] = r.get("reading_mode") or "matrix"
        item["aliases"] = r.get("aliases") or []
        item["match"] = {MATCH_EXACT_INDICATOR: "指标码完全匹配",
                         MATCH_EXACT_NAME: "名称完全匹配",
                         MATCH_EXACT_ALIAS: "别名完全匹配",
                         MATCH_NAME_CONTAINS: "名称包含",
                         MATCH_ALIAS_CONTAINS: "别名包含",
                         MATCH_INDICATOR_CONTAINS: "指标码包含",
                         MATCH_DEFINITION: "仅定义正文命中"}[rank]
        item["general_notes"] = [{"id": g["id"], "note": g["note"]}
                                 for g in general if r["path"].startswith(g["scope"])]
        ranked.append((rank, order, item))
    # 先按匹配强度，同强度保持库内原有顺序
    ranked.sort(key=lambda x: (x[0], x[1]))
    hits = [item for _, _, item in ranked]
    return {"ok": True, "keyword": kw, "source": "verified",
            "hits": hits[offset:offset + limit], "total": len(hits),
            "offset": offset, "limit": limit}


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


CMDS = {"lookup": lookup, "run": run, "text": text, "close": close,
        "status": status, "open": open_excel}


def main() -> None:
    try:
        req = json.loads(sys.stdin.read())
    except json.JSONDecodeError as error:
        print(json.dumps({"ok": False, "error": f"输入不是合法JSON：{error}"},
                         ensure_ascii=False))
        return
    if not isinstance(req, dict):
        print(json.dumps({"ok": False, "error": "输入必须是JSON对象"},
                         ensure_ascii=False))
        return
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
