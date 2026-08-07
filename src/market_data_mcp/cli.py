# -*- coding: utf-8 -*-
"""market_data CLI：批量获取行情/财报/指标/公司信息，输出 JSON/Markdown。

用法：
    python -m market_data_mcp.cli --tool get_quote --code 300476 --start 2025-01-01 --end 2026-12-31
    python -m market_data_mcp.cli --tool get_financial_statements --code 300476 --periods 2025,2024
    python -m market_data_mcp.cli --tool get_financial_ratios --code 00700
    python -m market_data_mcp.cli --tool get_company_profile --code AAPL
    python -m market_data_mcp.cli --batch codes=300476,00700,AAPL --tool get_financial_statements --out DIR --format md

请求 JSON 形态（与 MCP 工具同名）：
    {"tool": "get_quote", "code": "300476", "start": "...", "end": "...", "adjust": "qfq"}
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from market_data_mcp.service import get_company_profile, get_financial_ratios, get_financial_statements, get_quote

TOOLS = {
    "get_quote": get_quote,
    "get_financial_statements": get_financial_statements,
    "get_financial_ratios": get_financial_ratios,
    "get_company_profile": get_company_profile,
}


def _dispatch(request: dict[str, Any]) -> dict[str, Any]:
    tool = request.get("tool")
    if tool not in TOOLS:
        raise ValueError(f"未知 tool：{tool}（可选：{', '.join(TOOLS)}）")
    fn = TOOLS[tool]
    params = {k: v for k, v in request.items() if k != "tool"}
    try:
        return fn(**params)
    except Exception as exc:
        return {"ok": False, "tool": tool, "error": str(exc)}


def _records_of(result: dict[str, Any]) -> list[dict[str, Any]]:
    """从统一返回结构提取记录列表（用于批量汇总）。"""
    if result.get("rows"):
        return result["rows"]
    out: list[dict[str, Any]] = []
    for value in result.values():
        if isinstance(value, dict) and value.get("rows"):
            out.extend(value["rows"])
    return out


def _result_to_markdown(result: dict[str, Any], code: str) -> str:
    """把单公司结果转 Markdown（供 AI 在研究报告框架中使用）。"""
    lines = [f"## {code} 数据"]
    if not result.get("ok", True):
        return f"## {code} 数据\n\n获取失败：{result.get('error', '未知错误')}"
    for key, value in result.items():
        if key in ("ok", "market", "code"):
            continue
        elif isinstance(value, dict) and value.get("rows"):
            label = value.get("label", key)
            rows = value["rows"]
            if not rows:
                continue
            lines.append(f"\n### {label}")
            lines.append(f"共 {len(rows)} 条")
            headers = list(rows[0].keys())
            lines.append("| " + " | ".join(str(h) for h in headers) + " |")
            lines.append("|" + "|".join(["---"] * len(headers)) + "|")
            for row in rows[:30]:
                cells = []
                for h in headers:
                    v = row.get(h)
                    if v is None:
                        cells.append("")
                    else:
                        cells.append(str(v).replace("|", "\\|"))
                lines.append("| " + " | ".join(cells) + " |")
            if len(rows) > 30:
                lines.append(f"（仅显示前 30 条，共 {len(rows)} 条）")
        elif isinstance(value, dict) and value.get("note"):
            lines.append(f"\n### {key}\n\n{value['note']}")
        elif isinstance(value, list) and value:
            lines.append(f"\n### {key}\n\n{json.dumps(value, ensure_ascii=False, indent=1)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="market_data CLI：行情/财报/指标/公司信息")
    parser.add_argument("--tool", help="工具名：get_quote/get_financial_statements/get_financial_ratios/get_company_profile")
    parser.add_argument("--code", help="证券代码（6位A股/5位港股/美股字母）")
    parser.add_argument("--codes", help="批量：逗号分隔多个代码")
    parser.add_argument("--start", default=None, help="行情开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="行情结束日期 YYYY-MM-DD")
    parser.add_argument("--adjust", default="qfq", help="qfq/hfq/none")
    parser.add_argument("--period", default="daily", help="daily/weekly/monthly")
    parser.add_argument("--fields", default=None, help="返回字段，逗号分隔（如 date,close）")
    parser.add_argument("--periods", default=None, help="报告期年份，逗号分隔（如 2025,2024）")
    parser.add_argument("--statements", default=None, help="报表范围：income/balance/cash_flow，逗号分隔")
    parser.add_argument("--sections", default=None, help="公司信息部分：profile/dividends/forecast")
    parser.add_argument("--format", default="json", choices=["json", "md"], help="输出格式")
    parser.add_argument("--out", default=None, help="输出目录（批量时）")
    parser.add_argument("--batch", action="store_true", help="批量模式：--codes 逗号分隔")
    args = parser.parse_args()

    if not args.tool:
        raise SystemExit("缺少 --tool")

    def build(code: str) -> dict[str, Any]:
        req: dict[str, Any] = {"tool": args.tool, "code": code}
        if args.start:
            req["start"] = args.start
        if args.end:
            req["end"] = args.end
        if args.adjust != "qfq":
            req["adjust"] = args.adjust
        if args.period != "daily":
            req["period"] = args.period
        if args.fields:
            req["fields"] = [f.strip() for f in args.fields.split(",")]
        if args.periods:
            req["periods"] = [p.strip() for p in args.periods.split(",")]
        if args.statements:
            req["statements"] = [s.strip() for s in args.statements.split(",")]
        if args.sections:
            req["sections"] = [s.strip() for s in args.sections.split(",")]
        return req

    codes = [c.strip() for c in args.codes.split(",")] if args.codes else ([args.code] if args.code else [])
    if not codes:
        raise SystemExit("缺少 --code 或 --codes")

    results = [_dispatch(build(code)) for code in codes]

    if args.format == "md":
        md = []
        for code, result in zip(codes, results):
            md.append(_result_to_markdown(result, code))
        text = "\n\n".join(md)
        if args.out:
            import os

            os.makedirs(args.out, exist_ok=True)
            import pathlib

            path = pathlib.Path(args.out) / f"{args.tool}_{'_'.join(codes)}.md"
            path.write_text(text, encoding="utf-8")
            print(f"已写入 {path}")
        else:
            print(text)
    else:
        payload = {"ok": True, "requested": len(codes), "results": list(zip(codes, results))}
        print(json.dumps(payload, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
