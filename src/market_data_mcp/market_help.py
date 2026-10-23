"""运行能力与本地缓存帮助；不导入数据提供器，不联网、不登录。"""
from pathlib import Path
import json

from market_data_mcp import data_store
from market_data_mcp.financial_contract import DEFAULT_ITEMS, RATIOS, SEGMENTS, STATEMENTS
from market_data_mcp.routing import parse_code

TOOLS = {
    "get_quote": {"parameters": ["code", "vars", "adjust", "start_date", "end_date", "period", "export_path"],
                  "example": {"code": "600519.SH", "vars": ["close"], "start_date": "2025-01-01"},
                  "source": "新浪；美股后复权/成交额与部分股本用iFinD；无失败换源"},
    "get_financial_data": {"parameters": ["code", "amount_basis", "periods", "statements", "items", "include_versions", "force_refresh", "export_path"],
                           "required": ["code", "amount_basis"],
                           "example": {"code": "600519.SH", "amount_basis": "single", "periods": ["2025-09-30"], "items": ["营业收入", "毛利率"]},
                           "defaults": {"periods": "最近5个已披露报告期", "items": "常用科目", "all_items": ["ALL_ITEMS"]}},
    "get_company_profile": {"parameters": ["code", "sections", "periods", "years", "as_of_date", "force_refresh"],
                            "example": {"code": "600519.SH", "sections": ["forecast"], "years": [2026, 2027]},
                            "defaults": {"holders.periods": "最新一期", "forecast.years": "必填", "forecast.as_of_date": "最新快照"}},
    "get_quote_chart": {"parameters": ["code", "adjust", "start_date", "end_date", "period", "log_scale", "field", "events", "keypoints", "drawdown_threshold"],
                        "example": {"code": "600519.SH", "start_date": "2025-01-01"}, "output": "PNG路径"},
    "get_market_data_help": {"parameters": ["tool", "market", "code", "topic"],
                             "topics": ["tools", "items", "ranges", "refresh", "cache", "export"]},
}


def get_market_data_help(root, tool=None, market=None, code=None, topic=None):
    if tool is not None and tool not in TOOLS:
        return {"ok": False, "error": f"未知工具：{tool}"}
    topics = TOOLS["get_market_data_help"]["topics"]
    if topic is not None and topic not in topics:
        return {"ok": False, "error": f"topic须为{topics}"}
    if market is not None and market not in ("A", "BJ", "HK", "US", "SH", "SZ"):
        return {"ok": False, "error": "未知市场"}
    if code:
        try:
            mc = parse_code(code)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        code = f"{mc.code}.{mc.suffix}"
        if market and market not in (mc.market, mc.suffix):
            return {"ok": False, "error": "market与code不一致"}
        market = mc.market
    result = {"ok": True, "market": market, "code": code, "read_only": True}
    if topic in (None, "tools"):
        result["tools"] = {tool: TOOLS[tool]} if tool else TOOLS
    if topic in (None, "items"):
        result.update(default_items=DEFAULT_ITEMS, derived_items=RATIOS, statements=STATEMENTS,
                      segment_items=SEGMENTS, growth=["科目名同比增长率", "科目名环比增长率"],
                      ratio_unit="比值（0.25表示25%）", unsupported=["ROE", "ROA", "周转率", "TTM", "日频估值"])
    if topic in (None, "ranges"):
        result["ranges"] = {"financial": "按源实际报告截止日；不承诺固定起始年",
                            "ifind_series": "当前账号实测近5年；更早股本月频采样，非逐日精确变化",
                            "ifind_basic": "单点不受近5年限制，有效历史随字段而异",
                            "segments": "A/北交所已验证；B股未单独验证；港美无已验证通道",
                            "company": "A/北交所iFinD；港美暂保留已有能力；B股须单独验证",
                            "limits": "精确速率和部分计点规则未知"}
    if topic in (None, "refresh"):
        result["refresh"] = {"eastmoney_financial": "成功检查范围30天；新范围立即检查",
                             "ifind_financial": "探针1天；已披露期已检查有值/无值不自动重拉；force_refresh重查",
                             "company": "section及时间范围独立30天", "quote": "日期覆盖与终点不足时10分钟复用"}
    if topic in (None, "export"):
        result["export"] = {"items": ["ALL_ITEMS"], "periods": "明确报告截止日列表；不传最近5期",
                            "threshold": "超过200行自动CSV；export_path直接CSV",
                            "segments": "独立_segments.csv；single仍为累计", "batch": "CLI tool=get_financial_data_batch，codes数组"}
    if code and topic in (None, "cache", "items"):
        cached = []
        for domain in ("financial_data", "company_data"):
            folder = Path(root) / "cache" / code / domain
            if not folder.exists():
                continue
            for file in sorted(folder.glob("*.json")):
                payload = data_store.read(root, code, domain, file.stem)
                if payload:
                    cached.append({"domain": domain, "module": file.stem, "meta": payload.get("meta"),
                                   "checks": payload.get("checks", {}), "item_catalog": payload.get("item_catalog", []),
                                   "periods": payload.get("periods", {} ) if file.stem == "report_probe" else
                                       sorted(payload.get("periods", {})) if "periods" in payload else
                                       [r["report_date"] for r in payload.get("reports", [])]})
        result["cache"] = cached
        result["cache_note"] = "仅表示本地已检查范围，未缓存不等于上游不支持"
    return result
