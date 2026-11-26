# -*- coding: utf-8 -*-
"""第四块 帮助：让调用的 AI 在动手前看清有什么、该怎么调。

三条原则：
- 先给「要什么就用什么」，再给细节清单，不让 AI 在长列表里翻。
- 只说当前有效的事实，不写历史变更。
- 返回结构稳定，字段不随意增减。
"""
from __future__ import annotations

from ifind_excel_tool.formulas import library
from ifind_excel_tool.indicators import definitions

PAGE = 100


def overview() -> dict:
    """一页看清能取什么、怎么取。"""
    packages = definitions.load_packages()
    derived = definitions.load_derived()
    single = library.load_single()
    batch = library.list_batch()
    return {
        "ok": True,
        "what_you_can_get": {
            "单个科目的值": f'{{"cmd":"get","indicator":"毛利率","code":"002796.SZ"}}；'
                            f'库里现有 {len(single)} 条原始公式、{len(derived)} 个衍生科目',
            "一组常用科目": f'{{"cmd":"get","indicator":"利润表常用科目","code":"002796.SZ"}}；'
                            f'现有 {len(packages)} 个科目组合',
            "一段时间序列": '{"cmd":"fetch_package","package":"历史行情","code":"600519.SH"}，默认最近14个日历日',
            "整张报表": '{"cmd":"fetch_batch","batch":"指数成分股","code":"000300.SH"}，'
                        f'现有 {len(batch)} 条批量公式',
            "证券代码": '{"cmd":"search","keyword":"腾讯","kind":"股票"}，kind 必须指定：股票/指数/外汇',
            "完整报告": '{"cmd":"report","code":"002796.SZ","output":"导出目录"}',
            "行情图": '{"cmd":"draw","template":"kline_volume","data_path":"...csv","output":"...png"}',
        },
        "start_here": [
            "不知道数据叫什么，先 find 搜；搜到了直接用 get 取，不要自己拼公式",
            "get 的类型自动分派：原始公式、衍生科目、科目组合都不用你判断",
            "取数的 code 必须是 iFinD 格式：港股四位如 0700.HK，不确定就用 search 查",
            "默认时间口径：财报类取最新已披露报告期，行情类取最近14个日历日，公司信息类取今天",
            "目录里已登记的全部能搜能取；没登记的用 lookup 查公式再 run，绝不要猜参数",
            "取到 0 或空但确认应有数据时，先 close 关掉专用工作簿重试——iFinD 插件会缓存结果",
        ],
        "counts": {"formulas": len(single), "derived": len(derived),
                   "packages": len(packages), "batch": len(batch)},
    }


def list_packages() -> dict:
    """列出全部科目组合：名称、说明、字段数、可选维度。"""
    items = []
    for name, spec in definitions.load_packages().items():
        item = {"name": name, "description": spec.get("description", ""),
                "kind": spec.get("kind") or "matrix",
                "fields": len(spec.get("fields") or [])}
        if item["kind"] == "batch":
            item["inputs"] = spec.get("input_labels") or spec.get("inputs")
        else:
            item["dims"] = sorted((spec.get("dims") or {}).keys())
            item["defaults"] = spec.get("defaults") or {}
            item["periods"] = (["daily", "weekly", "monthly"]
                               if spec.get("resample") else ["daily"])
        items.append(item)
    return {"ok": True, "total": len(items), "packages": items}


def package_info(name: str) -> dict:
    """某个组合要什么参数、有哪些字段、默认值是什么。"""
    spec = definitions.load_packages().get(name or "")
    if spec is None:
        available = list(definitions.load_packages())
        return {"ok": False, "error": f"没有名为「{name}」的科目组合",
                "available": available}
    out = {"ok": True, "name": name, "description": spec.get("description", ""),
           "kind": spec.get("kind") or "matrix",
           "code_required": True}
    if out["kind"] == "batch":
        out["required_inputs"] = {k: (spec.get("input_labels") or {}).get(k, k)
                                  for k in spec.get("inputs") or []}
        out["output_fields"] = [
            {"field": f,
             "label": (spec.get("field_labels") or spec.get("fields"))[i]
                      if i < len(spec.get("field_labels") or []) else f}
            for i, f in enumerate(spec.get("fields") or [])]
        return out
    out["optional_inputs"] = {
        "report_date": "报告期或交易日，YYYY-MM-DD；不传按该组合默认",
        "report_dates": "报告期列表，一次取多期",
        "start": "区间起点，YYYY-MM-DD（按日期展开的组合有效）",
        "end": "区间终点，YYYY-MM-DD，或 today",
        "dims": "覆盖维度取值，如 {\"year\":[\"2025\",\"2024\"]}",
        "params": "覆盖字段参数，如 {\"adjust\": 100}",
        "export_path": "结果写 CSV 的路径",
    }
    if spec.get("resample"):
        out["optional_inputs"]["period"] = "daily/weekly/monthly，默认 daily"
    out["defaults"] = spec.get("defaults") or {}
    out["dims"] = spec.get("dims") or {}
    out["fields"] = [{"label": f["label"],
                      "indicator": f.get("indicator") or f.get("derived") or "候选",
                      "unit": f.get("unit", "")} for f in spec.get("fields") or []]
    return out


def list_indicators(market: str = "", keyword: str = "", limit: int = PAGE) -> dict:
    """按市场或关键词列出可用的原始公式与衍生科目。"""
    items = []
    for record in library.load_single().values():
        path = record.get("path") or ""
        if market and market not in path:
            continue
        name = (record.get("name") or "").strip()
        if keyword and keyword not in name and keyword not in (record.get("indicator") or ""):
            continue
        items.append({"name": name, "indicator": record.get("indicator"),
                      "path": path, "unit": record.get("unit", "")})
    for name, item in definitions.load_derived().items():
        if keyword and keyword not in name:
            continue
        items.append({"name": name, "indicator": name, "path": "衍生科目",
                      "unit": item.get("unit", "")})
    markets = sorted({(r.get("path") or "").split("/")[0]
                      for r in library.load_single().values() if r.get("path")})
    return {"ok": True, "total": len(items), "shown": min(len(items), limit),
            "indicators": items[:limit], "markets": markets}
