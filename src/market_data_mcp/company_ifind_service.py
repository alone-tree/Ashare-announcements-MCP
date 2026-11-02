"""公司信息按section、时间范围独立检查与提交。"""
from datetime import date, datetime, timezone
import hashlib
import json

from market_data_mcp import data_store
from market_data_mcp.providers import company_ifind


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
                "发行后市净率", "发行费用"}.issubset(cached.get("data", {}))
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
