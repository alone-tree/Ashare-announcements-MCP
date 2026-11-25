# -*- coding: utf-8 -*-
"""固定报告拼装：把各板块导出的CSV按固定章节拼成Markdown数据骨架。

依据 docs/iFinD-CLI固定报告与绘图扩展方案-2026-11-25.md。
本模块只做拼装，不取数、不推算、不做公司分析。没有数据的板块留空节并标注缺口。
章节顺序与旧脚本 build_report 对齐；表格写法遵守研究项目报告写作规范（不用加粗）。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

GAP = "（本板块未取到数据，待补）"


def _read_csv(path: str | Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _headers(rows: list[dict], *, drop: tuple[str, ...] = ("code",)) -> list[str]:
    if not rows:
        return []
    return [k for k in rows[0] if k not in drop and not k.endswith("__unit")]


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    text = str(value)
    if text.startswith("{") or text.startswith("["):
        try:
            return json.dumps(json.loads(text), ensure_ascii=False)
        except (ValueError, TypeError):
            pass
    # 数字：整数千分位；小数保留两位去尾零，避免 4093391896.56 或 252366948.0 这类补位
    try:
        num = float(text)
    except (ValueError, TypeError):
        return text
    if num == int(num):
        return f"{int(num):,}"
    return f"{num:,.2f}".rstrip("0").rstrip(".")


def table(rows: list[dict], *, limit: int | None = None,
          drop: tuple[str, ...] = ("code",)) -> str:
    if not rows:
        return GAP
    headers = _headers(rows, drop=drop)
    if not headers:
        return GAP
    data = rows if limit is None else rows[:limit]
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in data:
        out.append("| " + " | ".join(_fmt(row.get(h)) for h in headers) + " |")
    return "\n".join(out)


def key_value(rows: list[dict], *, drop: tuple[str, ...] = ("code",)) -> str:
    """单条记录转纵向「字段 | 值」表，避免几十列挤成一行难读。"""
    if not rows:
        return GAP
    headers = _headers(rows, drop=drop)
    if not headers:
        return GAP
    row = rows[0]
    out = ["| 字段 | 值 |", "| --- | --- |"]
    for h in headers:
        out.append(f"| {h} | {_fmt(row.get(h))} |")
    return "\n".join(out)


def build_report(company: str, code: str, sections: dict[str, str],
                 *, chart_path: str | None = None) -> str:
    """按固定章节拼装报告骨架。sections 的键为板块名，值为CSV路径。"""
    basic = _read_csv(sections.get("工商信息"))
    holders = _read_csv(sections.get("十大股东"))
    quote = _read_csv(sections.get("历史行情"))
    valuation = _read_csv(sections.get("估值快照"))
    balance = _read_csv(sections.get("资产负债表"))
    income = _read_csv(sections.get("利润表"))
    cashflow = _read_csv(sections.get("现金流量表"))
    income_q = _read_csv(sections.get("利润表单季"))
    cashflow_q = _read_csv(sections.get("现金流量表单季"))

    lines = [f"# {company}（{code}）公司报告", ""]

    lines += ["## 一、公司基本信息", "", key_value(basic), ""]

    lines += ["## 二、股东与控制权", "", "### 十大股东", "", table(holders), ""]

    lines += ["## 三、资本运作", "", "### IPO信息与股价行情", "", GAP, ""]
    lines += ["## 四、行情走势及分红", ""]
    if chart_path and Path(chart_path).is_file():
        lines += [f"![]({chart_path})", ""]
    if valuation:
        lines += ["### 估值快照", "", table(valuation), ""]
    if quote:
        # 「非交易日判定」与收盘价同值，展示无意义，去掉
        lines += ["### 行情数据（前复权，节选）", "",
                  table(quote, limit=5, drop=("code", "非交易日判定")), ""]
    lines += ["### 分红", "", GAP, ""]

    lines += ["## 五、财报摘要", "", table(income), ""]
    if income_q:
        lines += ["### 单季利润表", "", table(income_q), ""]

    lines += ["## 六、公司业务", "", "### 营收结构", "", GAP, ""]

    lines += ["## 七、盈利预测与估值", "", GAP, ""]

    lines += ["---", "", "## 附录", "", "### A、资产负债表", "", table(balance), "",
              "### B、利润表", "", table(income), "",
              "### C、现金流量表", "", table(cashflow), ""]
    if cashflow_q:
        lines += ["### D、现金流量表单季", "", table(cashflow_q), ""]

    md = "\n".join(lines).replace("**", "")
    return md if md.endswith("\n") else md + "\n"


def export_report(req: dict) -> dict:
    """CLI命令：读各板块CSV，拼Markdown并写出。"""
    company = req.get("company") or ""
    code = req.get("code") or ""
    sections = req.get("sections") or {}
    output = req.get("output") or ""
    chart_path = req.get("chart_path")
    if not company or not code:
        return {"ok": False, "error": "company 与 code 必须提供"}
    if not output:
        return {"ok": False, "error": "output 必须提供（Markdown输出路径）"}
    available = ["工商信息", "十大股东", "历史行情", "估值快照", "资产负债表",
                 "利润表", "现金流量表", "利润表单季", "现金流量表单季"]
    missing = [n for n, p in sections.items() if p and not Path(p).is_file()]
    if missing:
        return {"ok": False, "error": f"板块CSV不存在：{missing}"}
    md = build_report(company, code, sections, chart_path=chart_path)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return {"ok": True, "output": str(out.resolve()), "chars": len(md),
            "sections_received": [n for n, p in sections.items() if p],
            "available_sections": available}
