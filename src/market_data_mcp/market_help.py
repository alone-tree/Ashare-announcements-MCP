"""运行能力与本地缓存帮助；不导入数据提供器，不联网、不登录。"""
from pathlib import Path

from market_data_mcp import data_store, financial_items, forex
from market_data_mcp.financial_contract import META_KEYS, RATIOS, SEGMENTS, STATEMENTS, default_items as market_default_items
from market_data_mcp.routing import MarketCode, parse_code

TOOLS = {
    "get_quote": {"parameters": ["code", "vars", "adjust", "start_date", "end_date", "period", "export_path"],
                  "example": {"code": "600519.SH", "vars": ["close"], "start_date": "2025-01-01"},
                  "source": "SH/SZ/BJ股票：iFinD Excel；港美：既有新浪/iFinD；汇率：iFinD含固化历史；无失败换源",
                  "mainland": {"fields": ["open", "high", "low", "close", "avg_price", "volume", "amount", "turnover",
                      "company_total_shares", "security_total_shares", "company_total_market_cap", "security_total_market_cap"],
                      "aliases": {"total_shares": "company_total_shares", "total_market_cap": "company_total_market_cap"},
                      "note": "公司/证券四字段同批缓存，无默认层级；无公告建档前置；流通字段不支持；换手率为比值；日期列有成交日"},
                  "forex": {"codes": list(forex.CODES), "vars": ["close"],
                            "adjust": "raw", "history_end": forex.HISTORY_END,
                            "live_start": forex.LIVE_START,
                            "note": "CSV是iFinD原始数据；所有日期正常建字段缓存，历史空值不补拉；任意vars只返回close"}},
    "get_financial_data": {"parameters": ["code", "amount_basis", "periods", "statements", "items", "top_n", "include_versions", "force_refresh", "export_path"],
                           "required": ["code", "amount_basis"],
                           "example": {"code": "600519.SH", "amount_basis": "single", "periods": ["2025-09-30"], "items": ["营业收入", "毛利率"]},
                            "defaults": {"periods": "最近5个已披露报告期", "items": "常用科目", "all_items": ["ALL_ITEMS"], "top_n": 5}},
    "get_company_profile": {"parameters": ["code", "information_type", "force_refresh", "extra_parameters"],
                            "required": ["code", "information_type"],
                            "information_types": {"profile": "工商/概况", "ipo": "IPO", "dividends": "年度分红", "holders": "十大股东", "forecast": "盈利预测"},
                            "example": {"code": "600519.SH", "information_type": "forecast"},
                            "defaults": {"force_refresh": False, "extra_parameters": None},
                            "output": "整类完整数据，当前类型及市场可用的额外参数传法随结果返回"},
    "get_quote_chart": {"parameters": ["code", "adjust", "start_date", "end_date", "period", "log_scale", "field", "events", "keypoints", "drawdown_threshold"],
                        "example": {"code": "600519.SH", "start_date": "2025-01-01"}, "output": "PNG路径"},
    "get_market_data_help": {"parameters": ["tool", "market", "code", "topic"],
                             "parameter_notes": {"tool": "需要查看说明的工具名称",
                                                 "market": "市场范围",
                                                 "code": "需要检查本地缓存的带后缀股票代码",
                                                 "topic": "帮助主题，不是行情科目或财报科目"},
                             "topics": ["tools", "items", "ranges", "refresh", "cache", "export"],
                             "topic_notes": {"tools": "工具说明", "items": "科目/字段", "ranges": "覆盖边界",
                                             "refresh": "刷新规则", "cache": "本地缓存", "export": "导出"}},
    "close_ifind_excel": {"parameters": [], "example": {}, "output": "关闭本运行包专用Excel，不影响其他工作簿"},
}


def get_market_data_help(root, tool=None, market=None, code=None, topic=None):
    if tool is not None and tool not in TOOLS:
        return {"ok": False, "error": f"未知工具：{tool}"}
    topics = TOOLS["get_market_data_help"]["topics"]
    if topic is not None and topic not in topics:
        return {"ok": False, "error": f"topic须为{topics}"}
    if market is not None and market not in ("A", "BJ", "HK", "US", "SH", "SZ", "FX"):
        return {"ok": False, "error": "未知市场"}
    if code:
        try:
            normalized = code.strip().upper()
            if normalized in forex.CODES:
                bare, suffix = normalized.rsplit(".", 1)
                mc = MarketCode("FX", bare, suffix)
            else:
                mc = parse_code(code)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        code = f"{mc.code}.{mc.suffix}"
        if market and market not in (mc.market, mc.suffix):
            return {"ok": False, "error": "market与code不一致"}
        market = mc.market
    result = {"ok": True, "market": market, "code": code, "read_only": True}
    if market == "FX":
        if tool not in (None, "get_quote", "get_market_data_help"):
            return {"ok": False, "error": "汇率仅支持get_quote行情入口"}
        if topic in (None, "tools"):
            result["tools"] = {"get_quote": TOOLS["get_quote"]}
        if topic in (None, "items"):
            result["quote_fields"] = ["close"]
        if topic in (None, "ranges"):
            result["ranges"] = {"history_start": forex.HISTORY_START,
                                "history_end": forex.HISTORY_END, "live_start": forex.LIVE_START,
                                "note": "更早或首个有效值前返回null，历史空值已覆盖，不补拉"}
        if topic in (None, "refresh"):
            result["refresh"] = "全部日期沿用字段缓存及10分钟终点不足复用；CSV只在iFinD取数层作为历史原始数据读取"
        if topic in (None, "export"):
            result["export"] = "仅导出date/close；超过200行自动CSV，也可指定export_path"
        if topic in (None, "ranges", "cache"):
            result["source_data"] = {"kind": "ifind_raw_history", "path": str(forex.HISTORY_PATH),
                "date_range": {"start": forex.HISTORY_START, "end": forex.HISTORY_END}}
            if code:
                values = [(day, row[code]) for day, row in forex.read_history().items()]
                valid = [(day, value) for day, value in values if value is not None]
                result["source_data"].update(nonempty_count=len(valid), null_count=len(values) - len(valid),
                    first_valid_date=valid[0][0] if valid else None)
        if topic in (None, "cache"):
            result["cache"] = []
            if code:
                from market_data_mcp import cache as quote_cache
                cached = quote_cache.read_cache(root, code, "close")
                if cached:
                    result["cache"].append({"domain": "quote", "module": "close", "meta": cached["meta"],
                        "nonempty_count": sum(row.get("value") is not None for row in cached["items"])})
            result["cache_note"] = "cache仅显示工具数据目录中的实际字段缓存；CSV是iFinD原始数据，历史空值同样建缓存"
        return result
    if topic in (None, "tools"):
        result["tools"] = {tool: TOOLS[tool]} if tool else TOOLS
    if topic in (None, "items"):
        from market_data_mcp.service import VALID_VARS
        from market_data_mcp.quote_excel import PUBLIC_FIELDS
        result.update(default_items=market_default_items(market), derived_items=RATIOS, statements=STATEMENTS,
                      meta_items=list(META_KEYS),
                      segment_items=SEGMENTS, growth=["科目名同比增长率", "科目名环比增长率"],
                      quote_fields=VALID_VARS,
                      mainland_quote_fields=PUBLIC_FIELDS,
                      ratio_unit="比值（0.25表示25%）",
                      financial_units={"amount": "原币基础单位", "per_share": "原币/股", "shares": "股",
                                       "ratio": "比值（0.25表示25%）", "text": "文本"},
                      unsupported=["ROE", "ROA", "周转率", "TTM", "日频估值"])
    if topic in (None, "ranges"):
        result["ranges"] = {"financial": "按源实际报告截止日；不承诺固定起始年",
                            "ifind_series": "当前账号实测近5年；更早股本月频采样，非逐日精确变化",
                            "ifind_basic": "单点不受近5年限制，有效历史随字段而异",
                            "segments": "沪深A/B股及北交所已验证；主营top_n=1—99；客户/供应商为前五及合计；港美无已验证通道",
                            "company": "沪深A/B股及北交所iFinD已验证；港美暂保留已有能力",
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
                    coverage = {}
                    for report in payload.get("reports", []):
                        current = next((v for v in report.get("versions", []) if v.get("version_id") == report.get("current_version_id")), {})
                        for item in current.get("items", []):
                            key = str(item.get("item_code"))
                            entry = coverage.setdefault(key, {"item_name": financial_items.display_name(mc.market, key, item.get("item_name")), "first_valid_report_date": None,
                                                              "last_valid_report_date": None, "empty_count": 0})
                            if item.get("amount") is None:
                                entry["empty_count"] += 1
                            else:
                                entry["first_valid_report_date"] = min(entry["first_valid_report_date"] or report["report_date"], report["report_date"])
                                entry["last_valid_report_date"] = max(entry["last_valid_report_date"] or report["report_date"], report["report_date"])
                    cached.append({"domain": domain, "module": file.stem, "meta": payload.get("meta"),
                                   "checks": payload.get("checks", {}), "item_catalog": payload.get("item_catalog", []),
                                   "coverage": list(coverage.values()),
                                   "scope_checks": [{"query": entry.get("query"), "checked_at": entry.get("checked_at")}
                                                    for entry in payload.get("scopes", {}).values()],
                                   "period_checks": {period: entry.get("checked_at") for period, entry in payload.get("periods", {}).items() if isinstance(entry, dict)},
                                    **({"rank_checks": {period: {"top_n": entry.get("top_n", 5), "exhausted": bool(entry.get("exhausted"))}
                                                       for period, entry in payload.get("periods", {}).items()}}
                                       if file.stem in ("segments_product", "segments_industry", "segments_district") else {}),
                                   "periods": payload.get("periods", {} ) if file.stem == "report_probe" else
                                       sorted(payload.get("periods", {})) if "periods" in payload else
                                       [r["report_date"] for r in payload.get("reports", [])]})
        from market_data_mcp import cache as quote_cache
        for field in quote_cache.DATA_FILES:
            value = quote_cache.read_cache(root, code, field)
            if value:
                cached.append({"domain": "quote", "module": field, "meta": value["meta"],
                               "nonempty_count": sum(r.get("value") is not None for r in value["items"])})
        result["cache"] = cached
        result["cache_note"] = "仅表示本地已检查范围，未缓存不等于上游不支持"
    return result
