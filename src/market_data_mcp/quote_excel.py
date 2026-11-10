"""SH/SZ/BJ 的 Excel 行情闭环；独立于公告MCP，口径见架构§2。"""
from datetime import date, timedelta
import os

from market_data_mcp import aggregator, cache, company_ifind_service
from market_data_mcp.providers import excel

ALIASES = {"total_shares": "company_total_shares", "total_market_cap": "company_total_market_cap"}
PUBLIC_FIELDS = tuple(excel.PRICE_CODES) + ("volume", "amount", "turnover",
    "company_total_shares", "security_total_shares", "company_total_market_cap", "security_total_market_cap")


def _hfq_key(field):
    """后复权缓存键：close 走 close_no_forward 独立字段（方案见 docs/内地行情开市日过滤与后复权收盘切换方案-2026-11-06.md），其余价类仍为 *_hfq。"""
    return "close_no_forward" if field == "close" else f"{field}_hfq"


def _cached(root, code, field):
    payload = cache.read_cache(root, code, field)
    if payload and payload.get("meta", {}).get("source") == excel.SOURCE:
        return payload
    return None


def ensure_fields(root, mc, required, start, end, *, all_history=False):
    """一次检查、一次整包补取；绝不因其他字段再次执行同区间Excel。"""
    code = f"{mc.code}.{mc.suffix}"
    current = {f: _cached(root, code, f) for f in required}
    opened = current.get("close_no_forward")
    open_days = [r["date"] for r in (opened or {}).get("items", []) if
                 isinstance(r.get("value"), (int, float)) and r["value"] > 0]
    # 日历尾部可能是休市日或尚未更新的当日；不能因此宣称永久覆盖。
    last_open = max(open_days) if open_days else None
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    watermark = min(last_open, yesterday) if last_open else None
    def coverage_meta(payload):
        meta = payload["meta"]
        end_date = meta["date_range"]["end"]
        return {**meta, "date_range": {**meta["date_range"],
            "end": min(end_date, watermark) if watermark else None}}
    missing = []
    expected_start = None
    if all_history:
        # start=all 覆盖前提：骨架字段缓存起点不晚于上市日。上市日读本地security记录
        # （A股source=ifind SDK、港股source=ifind_excel），不在此处触发SDK；
        # 其他字段不做起点校验（上游历史边界各自不同，如B股成交额）。
        from market_data_mcp import data_store
        source_tag = "ifind_excel" if mc.market == "HK" else "ifind"
        record = data_store.read(root, code, "company_data", "security", source_tag)
        ipo = str((record or {}).get("data", {}).get("上市日期") or "")
        if len(ipo) == 8 and ipo.isdigit():
            expected_start = f"{ipo[:4]}-{ipo[4:6]}-{ipo[6:]}"
    for f, payload in current.items():
        cov_start = expected_start if (all_history and f == "close_no_forward") else (
            None if all_history else start)
        if not payload or not cache.coverage(coverage_meta(payload), cov_start, end):
            missing.append(f)
    notes = []
    if missing:
        security = {}
        try:
            security = company_ifind_service.get_quote_security(root, mc)
        except Exception as exc:
            notes.append(f"最小证券资料获取失败：{exc}；不影响无需股份分类的价格字段")
        pull_start = min(((coverage_meta(current[f])["date_range"]["end"] or start)
            if current[f] and (all_history or current[f]["meta"]["date_range"]["start"] <= start) else start)
            for f in missing)
        if all_history and "close_no_forward" in missing:
            nf_start = (current.get("close_no_forward") or {}).get("meta", {}).get(
                "date_range", {}).get("start")
            if nf_start and expected_start and nf_start > expected_start:
                pull_start = min(pull_start, expected_start)
        if all_history and pull_start == "1990-01-01":
            ipo = str(security.get("上市日期") or "")
            if len(ipo) == 8 and ipo.isdigit():
                pull_start = f"{ipo[:4]}-{ipo[4:6]}-{ipo[6:]}"
        if pull_start <= end:
            result = excel.fetch_quote(root, mc, pull_start, end, security)
            result = aggregator.commit_quote_batch(root, mc, result)
            notes.extend(result.get("notes") or [])
            if not result.get("ok"):
                notes.append(f"Excel取数失败：{result.get('error')}；未切换其他通道")
    results = {f: _cached(root, code, f) for f in required}
    return results, notes


def get_quote(root, mc, vars=None, adjust="raw", start_date=None, end_date=None,
              period="daily", export_path=None):
    from market_data_mcp.service import _auto_export_name, _default_start, _export_csv, _resample

    code = f"{mc.code}.{mc.suffix}"
    selected = ["close"] if vars is None else vars
    if not isinstance(selected, list) or not selected or any(not isinstance(v, str) for v in selected) or any(
            v not in PUBLIC_FIELDS and v not in ALIASES for v in selected):
        return {"ok": False, "error": f"Excel行情支持字段：{list(PUBLIC_FIELDS)}；流通股本及流通市值已移出"}
    selected = list(dict.fromkeys(selected))
    if adjust not in ("raw", "hfq", "qfq") or period not in ("daily", "weekly", "monthly"):
        return {"ok": False, "error": "adjust支持raw/hfq/qfq；period支持daily/weekly/monthly"}
    try:
        end = end_date or date.today().isoformat()
        date.fromisoformat(end)
        start = "1990-01-01" if start_date == "all" else start_date or _default_start(end)
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("开始日期不能晚于结束日期")
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": f"日期参数错误：{exc}"}
    fields = {ALIASES.get(f, f) for f in selected}
    # 开市日以 close_no_forward>0 识别（0=周末节假日休市；港股节假日同理）；
    # 公司停牌及全天零成交日保留，量额换手为0；成交量=成交额÷对应口径均价。
    required = {"amount", "avg_price", "close_no_forward"}
    if adjust != "raw":
        required.add("avg_price_hfq")  # hfq/qfq成交量=额÷对应口径均价（脑图口径），恒需后复权均价
    for field in fields:
        if field == "avg_price" and adjust != "raw":
            required.add("avg_price_hfq")
        elif field != "volume":
            required.add(field)
    if adjust == "qfq" and fields & set(excel.PRICE_CODES):
        required.update({"close", "close_no_forward"})
        if "avg_price" in fields:
            required.update({"avg_price", "avg_price_hfq"})
    cached, notes = ensure_fields(root, mc, required, start, end, all_history=start_date == "all")
    for field in ("company_total_market_cap", "security_total_market_cap"):
        if field not in cached:
            cached[field] = _cached(root, code, field)
    series = {f: {r["date"]: r["value"] for r in payload["items"] if r.get("source") == excel.SOURCE}
              for f, payload in cached.items() if payload}
    days = sorted({d for values in series.values() for d in values if start <= d <= end})
    active = [d for d in days if isinstance(series.get("close_no_forward", {}).get(d), (int, float))
              and series["close_no_forward"][d] > 0]
    missing = sorted(f for f in required if not cached.get(f))
    if missing:
        notes.append("缺少行情字段：" + "、".join(missing))
    if not series:
        return {"ok": False, "error": "；".join(notes) or "Excel未返回可用数据"}
    notes.append("日期列出全部市场开市日（close_no_forward大于0）；公司停牌及全天零成交日保留，量额换手为0")
    scales = {}
    if adjust == "qfq":
        for field in ("close", "avg_price"):
            hfq_key = _hfq_key(field)
            anchors = [d for d in active if isinstance(series.get(field, {}).get(d), (int, float))
                and isinstance(series.get(hfq_key, {}).get(d), (int, float))
                and series[hfq_key][d] != 0]
            if anchors:
                d = anchors[-1]
                scales[field] = series[field][d] / series[hfq_key][d]
        if fields & set(excel.PRICE_CODES) and "close" not in scales:
            notes.append("缺少同日原始/后复权收盘价，无法确定前复权基点")
    rows = []
    for day in active:
        amount = series.get("amount", {}).get(day)
        avg_raw = series.get("avg_price", {}).get(day)
        avg_hfq = series.get("avg_price_hfq", {}).get(day)
        close_raw = series.get("close", {}).get(day)
        close_hfq = series.get("close_no_forward", {}).get(day)
        # 开高低后复权=除权×F(t)（F=收后复权÷收）；active行cnf>0，分母必有效。
        factor = (close_hfq / close_raw
                  if isinstance(close_hfq, (int, float)) and close_hfq
                  and isinstance(close_raw, (int, float)) and close_raw else None)
        avg_for_volume = {"raw": avg_raw, "hfq": avg_hfq}.get(
            adjust, avg_raw * scales["avg_price"] if "avg_price" in scales else None)
        row = {"date": day, "amount": amount,
               "volume": amount / avg_for_volume
               if isinstance(amount, (int, float)) and isinstance(avg_for_volume, (int, float))
               and avg_for_volume != 0 else None}
        for field in fields:
            if field in ("volume", "amount"):
                continue
            raw = series.get(field, {}).get(day)
            if field == "close" and adjust != "raw":
                value = close_hfq  # 后复权收盘直取cnf，保持与缓存逐位一致
            elif field == "avg_price" and adjust != "raw":
                value = avg_hfq
            elif field in excel.PRICE_CODES and adjust != "raw":
                value = raw * factor if raw is not None and factor is not None else None
            else:
                value = raw
            if field in excel.PRICE_CODES and adjust == "qfq":
                scale = scales.get("avg_price" if field == "avg_price" else "close")
                value = value * scale if value is not None and scale is not None else None
            if field == "turnover" and value is not None:
                value /= 100
            row[field] = value
        company = series.get("company_total_market_cap", {}).get(day)
        security = series.get("security_total_market_cap", {}).get(day)
        if company is not None and security is not None and company < security:
            warning = "上游公司总市值小于证券总市值；两者保留原值"
            if warning not in notes:
                notes.append(warning)
        rows.append(row)
    if period != "daily":
        rows = _resample(rows, period, sum_fields=("volume", "amount", "turnover"))
        notes.append(f"{period}线由开市日日线聚合；量额及换手率累计，股本市值取期末")
    output = [{"date": r["date"], **{f: r.get(ALIASES.get(f, f)) for f in selected}} for r in rows]
    # 日期骨架来自 close_no_forward；只有它可用而请求字段全空时，不能将请求字段标为成功。
    available = any(r.get(f) is not None for r in output for f in selected)
    incomplete = bool(missing) or any(r.get(f) is None for r in output for f in selected) or any(
        "失败" in n or "返回：" in n for n in notes)
    kind = _share_type(root, mc)
    if mc.market == "HK":
        price_unit, amount_unit = "港元", "港元"
    else:
        price_unit = ("美元" if mc.suffix == "SH" and kind == "B股"
                      else "港元" if mc.suffix == "SZ" and kind == "B股"
                      else "元" if kind in ("A股",) or mc.suffix == "BJ"
                      else "原币（股份类型未确认）")
        amount_unit = "元"
    ok = available or (not active and not missing)
    result = {"ok": ok,
        "status": "failed" if not ok else "partial_success" if incomplete else "success",
        "code": code, "market": mc.market, "start": start_date if start_date == "all" else start,
        "end": end, "adjust": adjust, "period": period, "vars": selected, "source": excel.SOURCE, "notes": notes,
        "units": {f: "ratio" if ALIASES.get(f, f) == "turnover" else "股" if f == "volume" or "shares" in f
                  else amount_unit if "market_cap" in f or f in ("amount", "avg_price") else
                  price_unit for f in selected}}
    if not result["ok"]:
        result["error"] = "；".join(notes)
    if output:
        result["date_range"] = {"start": output[0]["date"], "end": output[-1]["date"]}
    if export_path or len(output) > 200:
        target = export_path or os.path.join(root, "cache", "_auto_export",
            _auto_export_name(code, adjust, period, selected))
        _export_csv(target, output, ["date"] + selected)
        result.update(path=target, total_items=len(output))
        if not export_path:
            result["auto_exported"] = True
    else:
        result["rows"] = output
    return result


def _share_type(root, mc):
    from market_data_mcp import data_store
    source = "ifind_excel" if mc.market == "HK" else "ifind"
    record = data_store.read(root, f"{mc.code}.{mc.suffix}", "company_data", "security", source)
    return (record or {}).get("data", {}).get("股份类型")
