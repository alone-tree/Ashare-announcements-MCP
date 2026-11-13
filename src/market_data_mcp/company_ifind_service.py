"""公司信息按section、时间范围独立检查与提交。"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import time

from market_data_mcp import data_store
from market_data_mcp.providers import company_ifind


def get_quote_security(root, mc):
    """数据MCP自身的最小行情资料；不读取公告档案，不补取整份工商/IPO。

    A/B/北交所走iFinD SDK三字段；港股仅上市日期，走Excel单公式（文本模式），
    缓存source=ifind_excel，"YYYY-MM-DD"规范化为8位数字。
    """
    code = f"{mc.code}.{mc.suffix}"
    if mc.market == "HK":
        source = "ifind_excel"
        cached = data_store.read(root, code, "company_data", "security", source)
        if cached and data_store.fresh(cached.get("checked_at")) and "上市日期" in cached.get("data", {}):
            return cached["data"]
        from market_data_mcp import ifind_excel, routing
        formula = '=@thsiFinD("ths_ipo_date_hks","{}")'.format(routing.to_ifind(mc))
        digits = ""
        result = None
        # 单列接口返回一维values；日期必须整项读取，不能截取字符串首字符。
        # 保留既有异常重试与预热流程，不把无效日期文本推断为登录状态码。
        for attempt in range(3):
            if attempt:
                time.sleep(5)
                try:
                    warm_day = (date.today() - timedelta(days=7)).isoformat()
                    warm = ('=@thsiFinD("ths_close_price_hks","{}","{}",100,"")'.format(
                        routing.to_ifind(mc), warm_day),)
                    ifind_excel.fetch_matrix([list(warm)], visible=True, timeout=300)
                except Exception:
                    pass  # 预热仅触发登录，结果不校验
            result = ifind_excel.fetch_formulas([formula], text_ok=True)
            digits = str(result["values"][0]).replace("-", "").strip()
            if len(digits) == 8 and digits.isdigit():
                break
            if attempt < 2:
                ifind_excel.close_excel(timeout=120)
        else:
            raise RuntimeError(f"港股上市日期返回异常：{result['values'][0][0]!r}")
        value = {"上市日期": digits}
        data_store.write(root, code, "company_data", "security", {
            "meta": {"schema_version": 2, "source": source}, "data": value,
            "checked_at": datetime.now(timezone.utc).isoformat()})
        return value
    fields = {"交易所": "ths_listing_exchange_stock",
              "股份类型": "ths_stock_varieties_stock", "上市日期": "ths_ipo_date_stock"}
    cached = data_store.read(root, code, "company_data", "security", "ifind")
    if cached and data_store.fresh(cached.get("checked_at")) and set(fields) <= set(cached.get("data", {})):
        return cached["data"]
    value = company_ifind.basic(root, mc, fields)
    data_store.write(root, code, "company_data", "security", {
        "meta": {"schema_version": 2, "source": "ifind"}, "data": value,
        "checked_at": datetime.now(timezone.utc).isoformat()})
    return value


def get_section(root, mc, section, periods, years, as_of_date, force):
    code = f"{mc.code}.{mc.suffix}"
    payload = data_store.read(root, code, "company_data", section, "ifind") or {
        "meta": {"schema_version": 2, "source": "ifind"}, "scopes": {}}
    latest_failures = []
    if section == "forecast" and not years:
        return {"ok": False, "error": "forecast必须传years"}
    if section == "holders" and periods is None:
        probe = data_store.read(root, code, "company_data", "holders_latest", "ifind")
        if not force and probe and data_store.fresh(probe.get("checked_at")):
            periods = [probe["report_date"]]
        else:
            try:
                latest = company_ifind.latest_report(root, mc)
                probe = {"meta": {"schema_version": 2, "source": "ifind"}, "checked_at": datetime.now(timezone.utc).isoformat(), "report_date": latest}
                data_store.write(root, code, "company_data", "holders_latest", probe)
                periods = [latest]
            except Exception as exc:
                if not probe:
                    return {"ok": False, "error": str(exc)}
                periods = [probe["report_date"]]
                latest_failures.append({"scope": "最新报告期检查", "reason": str(exc)})
    if section == "dividends" and years is None:
        years = list(range(date.today().year - 4, date.today().year + 1))
    scopes = periods if section == "holders" else years if section in ("forecast", "dividends") else [None]
    output, failures, checks = [], latest_failures, []
    reused = True
    for scope in scopes:
        query = {"scope": scope, "as_of_date": as_of_date if section == "forecast" else None}
        key = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
        cached = payload["scopes"].get(key)
        try:
            missing_ipo_fields = section == "ipo" and cached and not {
                "发行后市净率", "发行费用", "上市日期"}.issubset(cached.get("data", {}))
            if force or not cached or missing_ipo_fields or not data_store.fresh(cached.get("checked_at")):
                value = company_ifind.section(root, mc, section,
                    periods=[scope] if section == "holders" else None,
                    years=[scope] if section in ("forecast", "dividends") else None,
                    as_of_date=as_of_date or date.today().isoformat())
                candidate = {"query": query, "data": value, "checked_at": datetime.now(timezone.utc).isoformat()}
                updated = {**payload, "scopes": {**payload["scopes"], key: candidate}}
                data_store.write(root, code, "company_data", section, updated)
                payload, cached = updated, candidate
                reused = False
        except Exception as exc:
            failures.append({"scope": scope, "reason": str(exc)})
        if cached:
            value = cached["data"]
            output.extend(value if isinstance(value, list) else [value])
            checks.append({"query": cached["query"], "checked_at": cached["checked_at"]})
    result = {"ok": bool(output), "data": output[0] if section in ("profile", "ipo") and output else output,
              "source": "ifind", "cached": bool(checks) and reused, "stale": bool(failures), "checks": checks,
              "failed": failures}
    if failures:
        result["error"] = "部分范围刷新失败，可用旧值已保留" if output else "全部范围请求失败"
    if section == "forecast" and as_of_date is None:
        result["notes"] = ["未指定数据日期，按请求日取最新可用快照；as_of_date为查询日期，上游未披露实际更新日"]
    if section == "ipo":
        result["units"] = {"发行费用": "原币基础单位", "发行后市净率": "倍"}
    return result
