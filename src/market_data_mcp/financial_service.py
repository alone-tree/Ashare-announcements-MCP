"""财报调度：依赖规划→覆盖检查→独立更新→只读→逐指标计算→输出。"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from market_data_mcp import data_store, financial_cache, financial_items, service
from market_data_mcp.financial_contract import (
    ALIASES, DEFAULT_ITEMS, META_KEYS, RATIOS, SEGMENTS, STATEMENTS, validate_financial_request,
)
from market_data_mcp.providers import company_ifind, financial_statements

DOMAIN = "financial_data"


def _now():
    return datetime.now(timezone.utc).isoformat()


def inspect_financial_cache(root, code, statement, periods=None, force=False):
    payload = data_store.read(root, code, DOMAIN, statement, "eastmoney")
    checks = (payload or {}).get("checks", {})
    pending = [] if periods is None else [p for p in periods if force or not data_store.fresh(checks.get(p))]
    due = force or not payload or (bool(pending) if periods is not None else not data_store.fresh(payload.get("meta", {}).get("last_successful_update")))
    return {"payload": payload, "needs_refresh": due, "unchecked_periods": pending}


def write_financial_cache(root, code, market, statement, old, reports, periods):
    """一个报表批次成功才更新检查时间；旧期、观察版本均保留。"""
    now = _now()
    payload = financial_cache.merge_statement(old, reports, code=code, market=market,
        statement=statement, source="eastmoney", observed_at=now, batch_id=uuid.uuid4().hex)
    payload["meta"]["schema_version"] = 2
    checks = dict((old or {}).get("checks", {}))
    for period in set(periods or []) | {r["report_date"] for r in reports}:
        checks[period] = now
    payload["checks"] = checks
    data_store.write(root, code, DOMAIN, statement, payload)


def refresh_financial_cache(root, mc, statement, periods, force=False):
    code = f"{mc.code}.{mc.suffix}"
    inspected = inspect_financial_cache(root, code, statement, periods, force)
    if not inspected["needs_refresh"]:
        return None
    reports = financial_statements.fetch_batch(root, mc, statement)
    if not isinstance(reports, list):
        raise ValueError("报表批次必须是报告期列表")
    write_financial_cache(root, code, mc.market, statement, inspected["payload"], reports, periods)
    # 不把写入成功当作每个科目都有值。
    return inspect_financial_cache(root, code, statement, periods)


def read_financial_cache(root, code, statements, include_versions=False):
    bundle = {s: data_store.read(root, code, DOMAIN, s, "eastmoney") or {"reports": []} for s in statements}
    return service._financial_rows(bundle, list(statements), None, include_versions)


def _names(row, market):
    return financial_items.match_names(market, row.get("item_code"), row.get("item_name"))


def _match(rows, query, market):
    names = [query, *ALIASES.get(query, [])]
    matches = [r for r in rows if r.get("item_code") == query or any(n in _names(r, market) for n in names)]
    if not matches:
        matches = [r for r in rows if any(service._ordered_keyword_match(query, n) for n in _names(r, market))]
    codes = {(r["statement"], r.get("item_code")) for r in matches}
    if len(codes) > 1:
        raise ValueError("科目多候选：" + "、".join(sorted(str(c) for _, c in codes)))
    return matches


def _item_statement(name):
    matches = [statement for statement in ("balance", "income", "cash_flow") if name in DEFAULT_ITEMS[statement]]
    if len(matches) == 1:
        return matches[0]
    if name in ("营业收入", "归母净利润"):
        return "income"
    return None


def plan_financial_item(name):
    if name in RATIOS:
        return {"name": name, "kind": "ratio", "dependencies": list(RATIOS[name])}
    for suffix, kind in (("同比增长率", "yoy"), ("环比增长率", "qoq")):
        if name.endswith(suffix):
            base = name[:-len(suffix)]
            if not base or base in RATIOS or service._is_non_additive_item({"item_name": base}):
                raise ValueError("增长率仅支持可加总金额科目")
            return {"name": name, "kind": kind, "dependencies": [base]}
    return {"name": name, "kind": "raw", "dependencies": [name], "statement": _item_statement(name)}


def merge_financial_requirements(plans, selected, all_items, market):
    required = set(selected) & {"balance", "income", "cash_flow"} if all_items else set()
    for plan in plans:
        for name in plan["dependencies"]:
            if name in SEGMENTS:
                continue
            if name in META_KEYS:
                required.add("income")
                continue
            found = [s for s in ("balance", "income", "cash_flow") if name in DEFAULT_ITEMS[s]]
            if not found and (name in {"营业收入", "归母净利润"} or plan["kind"] == "ratio" and name not in {"负债合计", "资产总计"}):
                found = ["income"]
            if not found:
                found = ["balance", "income", "cash_flow"]
            required.update(found)
    if "meta" in selected and all_items:
        required.add("income")
    return required


def _identity(row):
    identity = service._period_identity(row)
    if not identity or identity[1] is None:
        return None
    metadata = row.get("report_metadata") or {}
    if metadata.get("START_DATE") and not str(metadata.get("REPORT") or ""):
        return ("start:" + str(metadata["START_DATE"])[:10], identity[1])
    return identity


def _cycle_year(cycle):
    text = cycle.split(":", 1)[-1]
    return int(text[:4]) if text[:4].isdigit() else None


def _single(row, all_rows):
    if row["statement"] in ("balance", "meta"):
        return dict(row)
    if service._is_non_additive_item(row):
        raise ValueError("非加总科目不参与单季差分")
    identity = _identity(row)
    if not identity:
        raise ValueError("缺少可确认的财年及季度身份")
    cycle, ordinal = identity
    value = row.get("amount")
    ids = [row.get("version_id")]
    if ordinal != 1:
        previous = [r for r in all_rows if r["statement"] == row["statement"]
                    and r.get("item_code") == row.get("item_code")
                    and _identity(r) == (cycle, ordinal - 1)]
        if len(previous) != 1:
            raise ValueError("缺少同财年上一累计期")
        previous = previous[0]
        if not service._same_financial_basis(row, previous):
            raise ValueError("两期来源、币种或会计准则不一致")
        if not _numeric(value) or not _numeric(previous.get("amount")):
            raise ValueError("本期或上期金额为空或非数值")
        value -= previous["amount"]
        ids.insert(0, previous.get("version_id"))
    return {**row, "amount": value, "value_basis": "single", "derived_from_version_ids": ids}


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number_for_calculation(value):
    if _numeric(value):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        except ValueError:
            pass
    return None


def _one(rows, name, market, period, basis):
    statement = _item_statement(name)
    found = _match([r for r in rows if r["report_date"] == period and (not statement or r["statement"] == statement)], name, market)
    if not found:
        raise ValueError("科目未返回或该期未披露")
    row = found[0]
    return _single(row, rows) if basis == "single" else dict(row)


def _compare_period(row, rows, kind):
    identity = _identity(row)
    if not identity:
        raise ValueError("缺少可确认的财年及季度身份")
    cycle, ordinal = identity
    candidates = [r for r in rows if r["statement"] == row["statement"]
                  and r.get("item_code") == row.get("item_code") and r["report_date"] < row["report_date"]]
    if kind == "qoq" and ordinal > 1:
        candidates = [r for r in candidates if _identity(r) == (cycle, ordinal - 1)]
    else:
        target_ordinal = ordinal if kind == "yoy" else 4
        # 年度与季度身份取自上游；缺少相邻财年时不跳到更早年度。
        candidates = [r for r in candidates if _identity(r) and _identity(r)[1] == target_ordinal
                      and _cycle_year(cycle) is not None
                      and _cycle_year(_identity(r)[0]) == _cycle_year(cycle) - 1]
    if not candidates:
        raise ValueError("缺少比较期")
    return max(candidates, key=lambda r: r["report_date"])


def evaluate_financial_items(plans, periods, rows, market, basis, include_versions=False):
    output, failed = [], []
    for plan in plans:
        name = plan["name"]
        for period in periods:
            try:
                if plan["kind"] == "raw":
                    found = _match([r for r in rows if r["report_date"] == period
                                    and (not plan.get("statement") or r["statement"] == plan["statement"])], name, market)
                    if not found:
                        raise ValueError("科目未返回或该期未披露")
                    for row in found:
                        value = _single(row, rows) if basis == "single" else dict(row)
                        value["item_name"] = name
                        output.append(value)
                        if value.get("amount") is None:
                            failed.append({"item": name, "report_date": period, "reason": "已检查无值"})
                    continue
                current_rows = [r for r in rows if r.get("is_latest", True)]
                dependencies = [_one(current_rows, dep, market, period, basis if plan["kind"] != "qoq" else "single")
                                for dep in plan["dependencies"]]
                values = [r.get("amount") for r in dependencies]
                if not all(_numeric(v) for v in values):
                    raise ValueError("依赖金额为空或非数值")
                if len(dependencies) > 1 and not service._same_financial_basis(dependencies[0], dependencies[1]):
                    raise ValueError("依赖科目币种或准则不一致")
                if plan["kind"] in ("yoy", "qoq"):
                    source = _one(current_rows, plan["dependencies"][0], market, period, "cumulative")
                    prior = _compare_period(source, current_rows, plan["kind"])
                    if not service._same_financial_basis(source, prior):
                        raise ValueError("比较期来源、币种或准则不一致")
                    if basis == "single" or plan["kind"] == "qoq":
                        prior = _single(prior, current_rows)
                    previous = prior.get("amount")
                    if not _numeric(previous) or previous <= 0:
                        failed.append({"item": name, "report_date": period, "reason": "基期为空、为0或负数",
                                       "current_amount": values[0], "previous_amount": previous})
                        continue
                    value = (values[0] - previous) / previous
                    dependencies.append(prior)
                elif name == "毛利":
                    value = values[0] - values[1]
                elif name == "毛利率":
                    if values[0] == 0:
                        raise ValueError("营业收入为0")
                    value = (values[0] - values[1]) / values[0]
                else:
                    if values[1] == 0:
                        raise ValueError("分母为0")
                    value = values[0] / values[1]
                row = {**dependencies[0], "item_code": name, "item_name": name, "amount": value,
                       "is_latest": True, "unit": "原币基础单位" if name == "毛利" else "ratio",
                       "derived_from_version_ids": list(dict.fromkeys(v for r in dependencies
                           for v in (r.get("derived_from_version_ids") or [r.get("version_id")]) if v))}
                if plan["kind"] in ("yoy", "qoq"):
                    row["current_amount"], row["previous_amount"] = values[0], previous
                    row["value_basis"] = "single" if plan["kind"] == "qoq" else basis
                if name != "毛利" and any(v < 0 for v in values):
                    row["note"] = "含负数金额，按公式保留结果"
                output.append(row)
            except (ValueError, TypeError, KeyError) as exc:
                failed.append({"item": name, "report_date": period, "reason": str(exc)})
    return output, failed


def _segment_results(root, mc, periods, names, force, minimal, notes):
    code = f"{mc.code}.{mc.suffix}"
    output, failed = [], []
    if not names:
        return output, failed
    if mc.market not in ("A", "BJ"):
        return output, [{"item": n, "reason": "该市场营收结构尚无已验证通道"} for n in names]
    probe = data_store.read(root, code, DOMAIN, "report_probe", "ifind")
    if force or not probe or not data_store.fresh(probe.get("checked_at"), 1):
        try:
            anchor = company_ifind.latest_report(root, mc)
            probe = {"meta": {"schema_version": 2, "source": "ifind"}, "checked_at": _now(), "report_date": anchor}
            data_store.write(root, code, DOMAIN, "report_probe", probe)
        except Exception as exc:
            notes.append(f"iFinD最新报告期探测失败：{exc}")
    anchor = (probe or {}).get("report_date")
    for name in names:
        dimension = SEGMENTS[name]
        module = "segments_" + dimension
        payload = data_store.read(root, code, DOMAIN, module, "ifind") or {
            "meta": {"schema_version": 2, "source": "ifind"}, "periods": {}}
        for period in periods:
            cached = payload["periods"].get(period)
            try:
                if force or cached is None:
                    if not anchor or period > anchor:
                        raise ValueError("尚未确认该报告期已披露")
                    records = company_ifind.segments(root, mc, period, dimension)
                    candidate = {"rows": records, "checked_at": _now()}
                    updated = {**payload, "periods": {**payload["periods"], period: candidate}}
                    data_store.write(root, code, DOMAIN, module, updated)
                    payload, cached = updated, candidate
            except Exception as exc:
                failed.append({"item": name, "report_date": period, "reason": str(exc)})
            if cached:
                records = cached["rows"][:1] if minimal else cached["rows"]
                for record in records:
                    item = {"report_date": period, "dimension": name, "value_basis": "cumulative", "source": "ifind", **record}
                    if minimal:
                        item.pop("gross_profit", None)
                        item.pop("rank", None)
                    output.append(item)
    return output, failed


def get_financial_data(root, code, amount_basis, periods=None, statements=None, items=None,
                       include_versions=False, force_refresh=False, export_path=None):
    try:
        mc = validate_financial_request(code, amount_basis, periods, statements, items)
        return execute_financial_request(root, mc, amount_basis, periods, statements, items,
                                         include_versions, force_refresh, export_path)
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}


def execute_financial_request(root, mc, basis, periods, statements, items, include_versions, force, export_path):
    code = f"{mc.code}.{mc.suffix}"
    selected = list(dict.fromkeys(statements or STATEMENTS))
    all_items = items is not None and "ALL_ITEMS" in items
    names = [n for s in selected for n in DEFAULT_ITEMS[s]] if items is None else list(dict.fromkeys(items))
    segment_names = [n for n in SEGMENTS if "segments" in selected] if all_items else [n for n in names if n in SEGMENTS]
    meta_names = list(META_KEYS) if all_items and "meta" in selected else [n for n in names if n in META_KEYS]
    if statements is not None and "segments" not in selected:
        segment_names = []
    if statements is not None and "meta" not in selected:
        meta_names = []
    raw_names = [n for n in names if n != "ALL_ITEMS" and n not in SEGMENTS and n not in META_KEYS]
    plans, failed = [], []
    for name in raw_names:
        try:
            plans.append(plan_financial_item(name))
        except ValueError as exc:
            failed.append({"item": name, "reason": str(exc)})
    required = merge_financial_requirements(plans, selected, all_items, mc.market)
    if segment_names and items is not None:
        required.add("income")  # 营收占比依赖同报告期累计营业总收入。
    if meta_names:
        required.add("income")
    if not required and periods is None:
        required.add("income")  # 发现真实报告期，不按日历猜港美季度。
    notes, refresh_errors = [], []
    refreshed = False
    for statement in sorted(required):
        try:
            refreshed = refresh_financial_cache(root, mc, statement, periods, force) is not None or refreshed
        except Exception as exc:
            refresh_errors.append({"statement": statement, "reason": str(exc)})
    rows = read_financial_cache(root, code, required, include_versions and basis == "cumulative")
    latest_rows = [r for r in rows if r.get("is_latest")]
    sec = None
    if mc.market == "US":
        sec = data_store.read(root, code, DOMAIN, "sec_filings", "sec")
        if refreshed or force or not sec:
            try:
                filings = financial_statements._fetch_sec_filings(root, mc, (sec or {}).get("data"))
                sec = {"meta": {"schema_version": 2, "source": "sec", "last_successful_update": _now()}, "data": filings}
                data_store.write(root, code, DOMAIN, "sec_filings", sec)
            except Exception as exc:
                notes.append(f"SEC提交元信息刷新失败：{exc}")
    requested = sorted(set(periods)) if periods else sorted({r["report_date"] for r in latest_rows})[-5:]
    if not requested:
        return {"ok": False, "code": code, "error": "无可用的已披露报告期", "failed_items": failed + refresh_errors}
    # 补拉只检查成功批次范围；东财物理返回全历史，单季及比较期不另发重复请求。
    if all_items:
        output = []
        for row in rows:
            if row["report_date"] not in requested or row["statement"] not in selected:
                continue
            try:
                output.append(_single(row, latest_rows) if basis == "single" else row)
            except ValueError as exc:
                failed.append({"item": row.get("item_name"), "report_date": row["report_date"], "reason": str(exc)})
    else:
        output, item_failures = evaluate_financial_items(plans, requested, latest_rows if basis == "single" else rows,
                                                       mc.market, basis, include_versions)
        failed.extend(item_failures)
    if all_items and plans:
        extra, item_failures = evaluate_financial_items(plans, requested, latest_rows, mc.market, basis)
        output.extend(extra)
        failed.extend(item_failures)
    if statements is not None:
        outside = [r for r in output if r["statement"] not in selected]
        output = [r for r in output if r["statement"] in selected]
        failed.extend({"item": r.get("item_name"), "report_date": r["report_date"], "reason": "不在所选statements输出范围"} for r in outside)
    # 读取真实报告元信息；缺项保留null，不把审计意见与内控意见混为一项。
    for period in requested:
        period_rows = [r for r in latest_rows if r["report_date"] == period]
        metadata = period_rows[0].get("report_metadata", {}) if period_rows else {}
        for name in meta_names:
            value = period if name == "报告截止日" else metadata.get(META_KEYS[name])
            output.append({"report_date": period, "statement": "meta", "item_code": META_KEYS[name],
                           "item_name": name, "amount": value, "source": "eastmoney", "value_basis": "metadata",
                           "report_metadata": metadata})
    segments, segment_failures = _segment_results(root, mc, requested, segment_names, force, items is None, notes)
    if items is not None:
        for segment in segments:
            income, gross = _number_for_calculation(segment.get("income")), _number_for_calculation(segment.get("gross_profit"))
            segment["gross_margin"] = gross / income if _numeric(gross) and _numeric(income) and income != 0 else None
            try:
                total = _one(latest_rows, "营业总收入", mc.market, segment["report_date"], "cumulative")
                denominator = total.get("amount")
                segment["income_share"] = income / denominator if _numeric(income) and _numeric(denominator) and denominator != 0 else None
            except ValueError:
                segment["income_share"] = None
    failed.extend(segment_failures)
    if segments and basis == "single":
        notes.append("营收结构跳过单季差分，返回累计原值")
    if any(plan["kind"] == "qoq" for plan in plans):
        notes.append("环比增长率始终按单季度金额计算")
    if include_versions:
        notes.append("派生指标仅使用当前累计版本；历史版本仅用于原始报表审计")
    for row in output:
        row.setdefault("unit", "text" if row["statement"] == "meta" else "原币基础单位")
    output = service._localize_financial_rows(output, mc.market)
    successful = any(r.get("amount") is not None for r in output) or any(r.get("name") not in (None, "") for r in segments)
    failures = failed + refresh_errors
    result = {"ok": successful, "code": code, "market": mc.market,
              "statements": list(dict.fromkeys([r["statement"] for r in output] + (["segments"] if segments else []))),
              "amount_basis": basis, "periods": requested, "include_versions": include_versions,
              "date_range": {"start": min(requested), "end": max(requested)},
              "status": "partial_success" if successful and failures else "success" if successful else "failed",
              "stale": bool(refresh_errors), "failed_items": failures, "notes": notes,
              "source": "eastmoney,ifind" if segments else "eastmoney",
              "units": {"amount": "原币基础单位，币种见report_metadata", "ratio": "比值；0.25表示25%"},
              "report_metadata": {p: next((r.get("report_metadata", {}) for r in latest_rows if r["report_date"] == p), {}) for p in requested},
              "calculation_dependencies": [{"item": r["item_name"], "report_date": r["report_date"], "version_ids": r["derived_from_version_ids"]}
                                           for r in output if r.get("derived_from_version_ids")],
              "rows": output, "segments": segments}
    if sec:
        result["filings"] = sec["data"]
    if export_path or len(output) + len(segments) > 200:
        target = Path(export_path) if export_path else Path(root) / "cache" / "_auto_export" / f"{code}_financial_{basis}.csv"
        result.update(paths=[], total_items=len(output), auto_exported=not bool(export_path))
        try:
            service._export_financial_csv(str(target), output)
            result["path"] = str(target.resolve())
            result["paths"].append(str(target.resolve()))
            result.pop("rows")
        except (OSError, ValueError) as exc:
            result["failed_items"].append({"export": str(target), "reason": str(exc)})
            result["status"] = "partial_success" if successful else "failed"
        if segments:
            segment_path = target.with_name(target.stem + "_segments.csv")
            fields = list(dict.fromkeys(k for row in segments for k in row))
            try:
                service._export_csv(str(segment_path), segments, fields)
                result["paths"].append(str(segment_path.resolve()))
                result.pop("segments")
            except (OSError, ValueError) as exc:
                result["failed_items"].append({"export": str(segment_path), "reason": str(exc)})
                result["status"] = "partial_success" if successful else "failed"
    return result
