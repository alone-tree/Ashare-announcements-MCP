# -*- coding: utf-8 -*-
"""market_data_mcp 工具层（service）：组装字段聚合器与请求模块，实现工具契约。

工具契约见 docs/market-data架构设计.md（§1.6/§2）。三层结构：本文件=工具层，
aggregator.py=字段聚合器，providers/=请求模块（源 × 市场 × 档位）。

2026-08-09 用户拍板：缓存为字段级独立 json（items [{date, value, source}]），
请求模块"拉到什么写什么"；本层从字段缓存组装 + **派生现算**（hfq OHL 还原、
qfq、市值、换手率、周月聚合——全部不落盘）。
"""

from __future__ import annotations

import csv
import json
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from market_data_mcp import aggregator, cache, financial_cache, financial_items
from market_data_mcp.providers import financial_statements, ifind, sina, yfinance
from market_data_mcp.routing import MARKET_NAMES, MarketCode, parse_code

VALID_ADJUSTS = ("raw", "hfq", "qfq")
VALID_PERIODS = ("daily", "weekly", "monthly")
VALID_VARS = ("open", "high", "low", "close", "volume", "amount",
              "turnover", "outstanding_share", "total_market_cap", "float_market_cap")

# 价格/量额原始字段（新浪 raw 宽拉列，A/港含 amount）
_PRICE_FIELDS = ("open", "high", "low", "close", "volume", "amount")


def _field_chains(mc: MarketCode) -> dict[str, list]:
    """字段 → 来源链。**每字段唯一源（2026-08-09 用户拍板：先不做来源回退，
    单一来源不够再增加；不同源数据可能不完全一致，混放需额外处理，且回退=重复请求浪费）**。"""
    if mc.market == "US":
        raw_chain = [sina.fetch_raw]
        amount_chain = [ifind.fetch_us_amount]  # 美股 amount=ifind 唯一源
        hfq_chain = [ifind.fetch_us_hfq]        # 美股 hfq=ifind 唯一源
    else:
        raw_chain = [sina.fetch_raw]
        amount_chain = [sina.fetch_raw]         # A/港 amount 在新浪 raw 宽写列
        hfq_chain = [sina.fetch_hfq]
    chains = {f: list(raw_chain) for f in _PRICE_FIELDS}
    chains["amount"] = amount_chain
    chains["close_hfq"] = hfq_chain
    chains["total_shares"] = [ifind.fetch_shares]  # 全市场唯一源 ifind（无回退）
    if mc.market in ("A", "BJ"):
        # A/北交所流通股本唯一源 = 新浪 outstanding_share（全历史逐日）
        chains["floating_shares"] = [sina.fetch_raw]
    else:
        # 港美股流通股本唯一源 = iFinD
        chains["floating_shares"] = [ifind.fetch_shares]
    return chains


def _ensure_fields(root: str, mc: MarketCode, fields: set[str],
                   start: str | None, end: str | None) -> dict[str, dict]:
    """逐字段 ensure（缓存复用：已覆盖字段不请求）。返回 {字段: {ok, items, source, notes}}。"""
    chains = _field_chains(mc)
    results: dict[str, dict] = {}
    for f in fields:
        if f not in chains:
            continue
        results[f] = aggregator.ensure(root, mc, f, chains[f], start, end)
    return results


def _values_by_date(items: list[dict] | None, preferred: str | None = None) -> dict[str, float | None]:
    """字段缓存 → {date: value}。优先取 preferred 来源记录；该源缺失日期回退任何来源。"""
    out: dict[str, float | None] = {}
    fallback: dict[str, float | None] = {}
    for r in (items or []):
        d, v = r.get("date"), r.get("value")
        if d is None:
            continue
        if preferred and r.get("source") == preferred:
            out[d] = v
        fallback.setdefault(d, v)
    for d, v in fallback.items():
        out.setdefault(d, v)
    return out


def _default_start(end: str) -> str:
    """end 为空时默认起点：最近 10 个交易日（≈14 自然日）。"""
    return (date.fromisoformat(end) - timedelta(days=14)).isoformat()


def _latest_share(share_series: dict[str, float | None], d: str) -> float | None:
    """前置填充：取 ≤ d 的最近股本点。"""
    last = None
    for sd in sorted(share_series):
        if sd > d:
            break
        if share_series.get(sd) is not None:
            last = share_series[sd]
    return last


def _resample(rows: list[dict], period: str) -> list[dict]:
    """周/月线由日线本地聚合（open=周期首日、high=最高、low=最低、close=末日、
    volume/amount=累计，其余取末日；weekly 用 W-FRI、monthly 用 ME）。"""
    if period == "daily" or not rows:
        return rows
    from datetime import datetime

    def bucket(d: str) -> str:
        dt = datetime.fromisoformat(d)
        if period == "weekly":
            friday = dt + timedelta(days=(4 - dt.weekday()) % 7)
            return friday.date().isoformat()
        return f"{dt.year:04d}-{dt.month:02d}"

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(bucket(r["date"]), []).append(r)
    out = []
    numeric = ("open", "high", "low", "close", "volume", "amount",
               "turnover", "outstanding_share", "total_market_cap", "float_market_cap")
    for b in sorted(groups):
        g = groups[b]
        row: dict = {"date": b}
        for k in numeric:
            vals = [x.get(k) for x in g if isinstance(x.get(k), (int, float))]
            if k == "open":
                row[k] = vals[0] if vals else None
            elif k == "high":
                row[k] = max(vals) if vals else None
            elif k == "low":
                row[k] = min(vals) if vals else None
            elif k == "close":
                row[k] = g[-1].get(k)
            elif k in ("volume", "amount"):
                row[k] = sum(vals) if vals else None
            else:
                row[k] = g[-1].get(k)
        out.append(row)
    return out


def _export_csv(path: str, rows: list[dict], cols: list[str]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def get_quote(
    root: str,
    code: str,
    vars: list[str] | None = None,
    adjust: str = "raw",
    start_date: str | None = None,
    end_date: str | None = None,
    period: str = "daily",
    export_path: str | None = None,
) -> dict:
    """获取日/周/月线行情。返回 {ok, market, code, start, end, adjust, period, vars, source, notes, rows}；
    超长自动导出 / 指定 export_path 时返回元信息不含 rows。"""
    try:
        mc = parse_code(code)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if adjust not in VALID_ADJUSTS:
        return {"ok": False, "error": f"不支持的复权方式 {adjust}（支持 raw/hfq/qfq）"}
    if period not in VALID_PERIODS:
        return {"ok": False, "error": f"不支持的周期 {period}（支持 daily/weekly/monthly）"}
    if vars is None:
        vars = ["close"]
    unknown = [v for v in vars if v not in VALID_VARS]
    if unknown:
        return {"ok": False, "error": f"未知字段 {unknown}（支持 {sorted(VALID_VARS)}，date 恒保留）"}

    end = end_date or date.today().isoformat()
    start = start_date or _default_start(end)
    notes: list[str] = []

    # 1. 需要的字段（缓存字段名）
    need_fields: set[str] = set()
    for v in vars:
        if v == "outstanding_share":
            need_fields.add("floating_shares")
        elif v in ("total_market_cap", "float_market_cap", "turnover"):
            need_fields.update({"close", "floating_shares", "total_shares"})
            if v == "total_market_cap":
                need_fields.add("total_shares")
            if v == "turnover":
                need_fields.add("volume")  # 换手率 = volume ÷ 流通股本
        elif v in _PRICE_FIELDS:
            need_fields.add(v)
    if adjust in ("hfq", "qfq"):
        need_fields.add("close_hfq")

    # 2. 逐字段 ensure（缓存复用）；字段级失败→部分成功：失败字段无数据 + notes 标注，不整单拒绝
    results = _ensure_fields(root, mc, need_fields, start, end)
    failed = {f: r for f, r in results.items() if not r["ok"]}
    ok_fields = [f for f, r in results.items() if r["ok"]]
    if not ok_fields:
        parts = []
        for f, r in failed.items():
            parts.append(f + ": " + str(r.get("error") or r.get("notes")))
        return {"ok": False, "error": "字段获取失败：" + "；".join(parts)}
    for f, r in failed.items():
        notes.append(f"字段 {f} 获取失败（{r.get('error') or r.get('notes')}），该列无数据")
    for f, r in results.items():
        for n in (r.get("notes") or []):
            if n and n not in notes:
                notes.append(n)

    # 3. 组装：骨架日期 = 各字段日期并集（请求范围内）；按聚合器结果源取数
    by_field: dict[str, dict[str, float | None]] = {}
    all_dates: set[str] = set()
    for f, r in results.items():
        by_field[f] = _values_by_date(r["items"], r.get("source"))
        all_dates.update(by_field[f].keys())
    dates = sorted(d for d in all_dates if start <= d <= end)

    # 4. 逐行组装原始值
    raw_close = by_field.get("close", {})
    rows = []
    for d in dates:
        row: dict = {"date": d}
        for f in _PRICE_FIELDS:
            if f in by_field:
                row[f] = by_field[f].get(d)
        row["_raw_close"] = raw_close.get(d)  # 内部保留：市值/复权用
        rows.append(row)

    # 5. 派生：hfq/qfq
    if adjust in ("hfq", "qfq"):
        hfq = by_field.get("close_hfq", {})
        if adjust == "hfq":
            for r in rows:
                hc = hfq.get(r["date"])
                rc = r.get("_raw_close")
                if hc is not None and rc:
                    f = hc / rc
                    for k in ("open", "high", "low"):
                        if r.get(k) is not None:
                            r[k] = round(r[k] * f, 4)
                    r["close"] = round(hc, 4)
                else:
                    for k in ("open", "high", "low", "close"):
                        r[k] = hc if k == "close" else None
        else:  # qfq：前复权本地现算（hfq × 最新缩放），不落盘
            latest_raw = next((r for r in reversed(rows) if r.get("_raw_close") is not None), None)
            lh = hfq.get(latest_raw["date"]) if latest_raw else None
            if latest_raw and lh:
                scale = latest_raw["_raw_close"] / lh
                for r in rows:
                    hc = hfq.get(r["date"])
                    rc = r.get("_raw_close")
                    if hc is not None and rc:
                        f = hc / rc * scale
                        for k in ("open", "high", "low"):
                            if r.get(k) is not None:
                                r[k] = round(r[k] * f, 4)
                        r["close"] = round(hc * scale, 4)
                    else:
                        for k in ("open", "high", "low", "close"):
                            r[k] = hc * scale if k == "close" and hc is not None else None
            else:
                notes.append("后复权数据缺失，前复权计算不完整")

    # 6. 派生：股本/市值/换手率（基于不复权 close —— 市值 = 股本 × 当日不复权收盘）
    total_shares = by_field.get("total_shares", {})
    floating_shares = by_field.get("floating_shares", {})
    need_mcap = "total_market_cap" in vars or "float_market_cap" in vars
    need_turnover = "turnover" in vars
    if need_mcap or need_turnover:
        for r in rows:
            rc = r.get("_raw_close")
            ts = _latest_share(total_shares, r["date"])
            fs = _latest_share(floating_shares, r["date"])
            if need_mcap and "total_market_cap" in vars and ts is not None and rc is not None:
                r["total_market_cap"] = ts * rc
            if need_mcap and "float_market_cap" in vars and fs is not None and rc is not None:
                r["float_market_cap"] = fs * rc
            if need_turnover and fs and r.get("volume") is not None:
                r["turnover"] = r["volume"] / fs
        if need_mcap:
            notes.append("总市值/流通市值为估算值（股本 × 不复权收盘价）")

    # 7. vars 映射输出（outstanding_share ← floating_shares；_raw_close 不输出）
    out_rows = []
    for r in rows:
        r.pop("_raw_close", None)
        out: dict = {"date": r["date"]}
        for v in vars:
            if v == "outstanding_share":
                out[v] = _latest_share(floating_shares, r["date"])
            elif v in r:
                out[v] = r.get(v)
        out_rows.append(out)

    # 8. 周/月聚合
    if period != "daily":
        out_rows = _resample(out_rows, period)
        notes.append(f"{period} 线由日线本地聚合（{'W-FRI' if period == 'weekly' else '月度'}）")

    if not out_rows:
        return {"ok": True, "market": mc.market, "code": f"{mc.code}.{mc.suffix}",
                "start": start, "end": end, "adjust": adjust, "period": period,
                "vars": vars, "source": None, "notes": notes + ["请求范围内无数据"], "rows": []}

    date_range = {"start": out_rows[0]["date"], "end": out_rows[-1]["date"]}
    sources = sorted({r.get("source") for r in results.values() if r.get("source")})
    source = ",".join(sources) if sources else None

    # 数据起点晚于请求起点（上游数据源范围所限/新股上市）→ 通用提示，不涉及具体个股
    if start_date and out_rows[0]["date"] > start_date:
        notes.append(f"数据自 {out_rows[0]['date']} 起（上游数据源实际可用范围）")

    cols = ["date"] + vars
    # 9. 导出
    if export_path:
        _export_csv(export_path, out_rows, cols)
        return {"ok": True, "market": mc.market, "code": f"{mc.code}.{mc.suffix}",
                "start": start, "end": end, "adjust": adjust, "period": period,
                "vars": vars, "path": export_path, "total_items": len(out_rows),
                "date_range": date_range, "source": source, "notes": notes or None}
    if len(out_rows) > 200:
        auto_path = os.path.join(root, "cache", "_auto_export",
                                 f"{mc.code}.{mc.suffix}_{adjust}_{period}_{start}_{end}.csv")
        _export_csv(auto_path, out_rows, cols)
        return {"ok": True, "market": mc.market, "code": f"{mc.code}.{mc.suffix}",
                "start": start, "end": end, "adjust": adjust, "period": period,
                "vars": vars, "auto_exported": True, "path": auto_path,
                "total_items": len(out_rows), "date_range": date_range,
                "source": source, "notes": notes + [f"数据超过 200 行，已自动导出到 {auto_path}"]}

    return {"ok": True, "market": mc.market, "code": f"{mc.code}.{mc.suffix}",
            "start": start, "end": end, "adjust": adjust, "period": period,
            "vars": vars, "source": source, "notes": notes or None, "rows": out_rows}


VALID_STATEMENTS = ("balance", "income", "cash_flow")
VALID_AMOUNT_BASES = ("cumulative", "single")
VALID_REPORT_TYPES = ("annual", "semiannual", "q1", "q3")


def get_data_catalog(
    root: str,
    code: str,
    statements: list[str] | None = None,
) -> dict:
    """只读本地财报缓存，返回公司×报表实际出现过非空金额的科目。"""
    try:
        mc = parse_code(code)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    selected = list(VALID_STATEMENTS) if statements is None else list(statements)
    if not selected or any(statement not in VALID_STATEMENTS for statement in selected):
        return {"ok": False, "error": f"statements 必须是 {list(VALID_STATEMENTS)} 的非空子集"}
    selected = list(dict.fromkeys(selected))
    full_code = f"{mc.code}.{mc.suffix}"
    bundle = financial_cache.read_bundle(root, full_code)
    if bundle is None:
        return {
            "ok": False,
            "code": full_code,
            "error": f"本地尚无 {full_code} 的完整财务报表缓存",
            "hint": "请先调用 get_financial_statements 获取该公司财报，再重新调用 get_data_catalog",
        }

    catalog: dict[tuple[str, str, str], dict] = {}
    for statement in selected:
        for report in bundle[statement].get("reports") or []:
            report_date = str(report.get("report_date") or "")
            for version in report.get("versions") or []:
                for item in version.get("items") or []:
                    if item.get("amount") is None:
                        continue
                    key = (
                        statement,
                        str(item.get("item_code") or ""),
                        str(item.get("item_name") or item.get("item_code") or ""),
                    )
                    entry = catalog.setdefault(
                        key,
                        {
                            "statement": statement,
                            "item_name": financial_items.display_name(mc.market, key[1], key[2]),
                            "first_report_date": report_date,
                            "last_report_date": report_date,
                        },
                    )
                    entry["first_report_date"] = min(entry["first_report_date"], report_date)
                    entry["last_report_date"] = max(entry["last_report_date"], report_date)
    return {
        "ok": True,
        "market": mc.market,
        "code": full_code,
        "statements": selected,
        "items": sorted(catalog.values(), key=lambda item: (item["statement"], item["item_name"])),
    }


def _financial_cache_is_fresh(bundle: dict, now: datetime) -> bool:
    payloads = [bundle[statement] for statement in VALID_STATEMENTS]
    payloads.append(bundle["metadata"])
    return all(financial_cache.is_fresh(payload, now=now) for payload in payloads)


def _financial_rows(
    bundle: dict,
    statements: list[str],
    start_date: str | None,
    end_date: str | None,
    include_versions: bool,
) -> list[dict]:
    rows: list[dict] = []
    for statement in statements:
        payload = bundle[statement]
        for report in payload.get("reports") or []:
            report_date = str(report.get("report_date") or "")
            if start_date and report_date < start_date:
                continue
            if end_date and report_date > end_date:
                continue
            versions = report.get("versions") or []
            if not include_versions:
                versions = [
                    version
                    for version in versions
                    if version.get("version_id") == report.get("current_version_id")
                ]
            version_count = len(report.get("versions") or [])
            for version in versions:
                report_metadata = version.get("metadata") or {}
                for item in version.get("items") or []:
                    rows.append(
                        {
                            "report_date": report_date,
                            "statement": statement,
                            "item_code": item.get("item_code"),
                            "item_name": item.get("item_name"),
                            "amount": item.get("amount"),
                            "source": item.get("source"),
                            "value_basis": "point_in_time" if statement == "balance" else "cumulative",
                            "version_id": version.get("version_id"),
                            "is_latest": version.get("version_id") == report.get("current_version_id"),
                            "version_count": version_count,
                            "has_revisions": version_count > 1,
                            "first_seen_at": version.get("first_seen_at"),
                            "source_update_date": report_metadata.get("UPDATE_DATE")
                            or report_metadata.get("NOTICE_DATE"),
                            "change_summary": version.get("change_summary"),
                            "report_metadata": report_metadata,
                        }
                    )
    rows.sort(key=lambda row: (row["report_date"], row["statement"], str(row["item_code"]), str(row["version_id"])))
    return rows


def _is_non_additive_item(row: dict) -> bool:
    code = str(row.get("item_code") or "").upper()
    name = str(row.get("item_name") or "").lower()
    code_markers = (
        "BASIC_EPS",
        "DILUTED_EPS",
        "PER_SHARE",
        "DIVIDEND_PER_SHARE",
        "WEIGHTED_AVERAGE_SHARE",
        "WEIGHTED_AVG_SHARE",
        "WEIGHTAVG_SHARE",
        "AVERAGE_SHARES",
        "AVG_SHARES",
        "_ROE",
        "_ROA",
        "MARGIN",
    )
    name_markers = (
        "每股",
        "加权平均股",
        "平均股数",
        "weighted average shares",
        "weighted average number of shares",
        "earnings per share",
        "dividend per share",
        "净资产收益率",
        "总资产收益率",
        "毛利率",
        "净利率",
        "利润率",
    )
    return any(marker in code for marker in code_markers) or any(marker in name for marker in name_markers)


def _period_identity(row: dict) -> tuple[str, int | None] | None:
    metadata = row.get("report_metadata") or {}
    report = str(metadata.get("REPORT") or "")
    if "/" in report:
        cycle, period = report.rsplit("/", 1)
        ordinal = {"Q1": 1, "Q6": 2, "Q9": 3, "FY": 4}.get(period.upper())
        return (f"report:{cycle}", ordinal) if ordinal is not None else None

    report_name = str(metadata.get("REPORT_DATE_NAME") or metadata.get("REPORT_TYPE") or "")
    ordinal = None
    for marker, value in (
        ("一季", 1),
        ("第一季", 1),
        ("半年", 2),
        ("中报", 2),
        ("三季", 3),
        ("第三季", 3),
        ("年报", 4),
    ):
        if marker in report_name:
            ordinal = value
            break
    if ordinal is not None:
        return (f"calendar:{row['report_date'][:4]}", ordinal)

    start_date = metadata.get("START_DATE")
    if start_date:
        return (f"start:{str(start_date)[:10]}", None)
    return None


def _report_type(row: dict) -> str | None:
    identity = _period_identity(row)
    if identity is None:
        return None
    return {1: "q1", 2: "semiannual", 3: "q3", 4: "annual"}.get(identity[1])


def _same_financial_basis(current: dict, previous: dict) -> bool:
    current_meta = current.get("report_metadata") or {}
    previous_meta = previous.get("report_metadata") or {}
    for key in ("CURRENCY", "ACCOUNT_STANDARD"):
        if current_meta.get(key) != previous_meta.get(key):
            return False
    return current.get("source") == previous.get("source")


def _derive_single_rows(rows: list[dict]) -> tuple[list[dict], list[str]]:
    output = [dict(row) for row in rows if row["statement"] == "balance"]
    skipped_dates: set[str] = set()
    grouped: dict[str, dict[str, list[dict]]] = {}
    for row in rows:
        if row["statement"] == "balance":
            continue
        grouped.setdefault(row["statement"], {}).setdefault(row["report_date"], []).append(row)

    for statement, by_date in grouped.items():
        periods: dict[str, list[tuple[int | None, str, list[dict]]]] = {}
        for report_date, report_rows in by_date.items():
            identity = _period_identity(report_rows[0])
            if identity is None:
                skipped_dates.add(report_date)
                continue
            cycle, ordinal = identity
            periods.setdefault(cycle, []).append((ordinal, report_date, report_rows))

        for cycle_periods in periods.values():
            cycle_periods.sort(key=lambda item: item[1])
            by_ordinal = {ordinal: report_rows for ordinal, _, report_rows in cycle_periods if ordinal is not None}
            for index, (ordinal, report_date, current_rows) in enumerate(cycle_periods):
                previous_rows = None
                if ordinal == 1 or (ordinal is None and index == 0):
                    previous_rows = []
                elif ordinal is not None:
                    previous_rows = by_ordinal.get(ordinal - 1)
                elif index > 0:
                    previous_rows = cycle_periods[index - 1][2]
                if previous_rows is None:
                    skipped_dates.add(report_date)
                    continue

                previous_by_code = {str(row.get("item_code")): row for row in previous_rows}
                for current in current_rows:
                    if _is_non_additive_item(current):
                        continue
                    derived = dict(current)
                    current_amount = current.get("amount")
                    if not previous_rows:
                        amount = current_amount
                        version_ids = [current.get("version_id")]
                    else:
                        previous = previous_by_code.get(str(current.get("item_code")))
                        if previous is None or not _same_financial_basis(current, previous):
                            amount = None
                            version_ids = [current.get("version_id")]
                        else:
                            previous_amount = previous.get("amount")
                            if isinstance(current_amount, (int, float)) and isinstance(previous_amount, (int, float)):
                                amount = current_amount - previous_amount
                            else:
                                amount = None
                            version_ids = [previous.get("version_id"), current.get("version_id")]
                    derived["amount"] = amount
                    derived["value_basis"] = "single"
                    derived["derived_from_version_ids"] = [value for value in version_ids if value]
                    output.append(derived)
    output.sort(key=lambda row: (row["report_date"], row["statement"], str(row["item_code"])))
    return output, sorted(skipped_dates)


def _export_financial_csv(path: str, rows: list[dict]) -> None:
    columns = [
        "report_date",
        "statement",
        "item_name",
        "amount",
        "source",
        "value_basis",
        "version_id",
        "is_latest",
        "version_count",
        "has_revisions",
        "first_seen_at",
        "source_update_date",
        "change_summary",
        "derived_from_version_ids",
        "report_metadata",
    ]
    serialised = []
    for row in rows:
        item = dict(row)
        for key in ("change_summary", "derived_from_version_ids", "report_metadata"):
            if key in item:
                item[key] = json.dumps(item[key], ensure_ascii=False, sort_keys=True)
        serialised.append(item)
    _export_csv(path, serialised, columns)


def _localize_financial_rows(rows: list[dict], market: str) -> list[dict]:
    """把上游科目转为面向 AI 的中文名；内部代码不对外返回。"""
    output = []
    for row in rows:
        item = dict(row)
        item["item_name"] = financial_items.display_name(
            market, item.get("item_code"), item.get("item_name")
        )
        item.pop("item_code", None)
        output.append(item)
    return output


def _ordered_keyword_match(query: str, name: str) -> bool:
    """查询字符按顺序出现在科目名中；营收→营业收入，但不会命中应收。"""
    characters = iter("".join(str(name).split()))
    return all(any(character == candidate for candidate in characters) for character in "".join(query.split()))


def _filter_financial_items(
    rows: list[dict], market: str, requested_items: list[str]
) -> tuple[list[dict], list[dict], list[str]]:
    by_code: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for row in rows:
        code = str(row.get("item_code") or "")
        by_code.setdefault(code, []).append(row)
        names[code] = financial_items.display_name(market, code, row.get("item_name"))
    selected_codes: set[str] = set()
    failed_items: list[dict] = []
    notes: list[str] = []
    for requested in requested_items:
        exact = [code for code, name in names.items() if name == requested]
        candidates = exact or [code for code, name in names.items() if _ordered_keyword_match(requested, name)]
        if len(candidates) == 1:
            selected_codes.add(candidates[0])
            if not exact:
                notes.append(f"科目“{requested}”按关键词匹配为“{names[candidates[0]]}”，并非精确名称匹配")
            continue
        if not candidates:
            failed_items.append({
                "requested_name": requested,
                "reason": "not_found",
                "hint": "报表中没有匹配科目；请调用 get_data_catalog 查看完整科目，工具不计算衍生指标",
            })
            continue
        candidate_items = []
        for code in sorted(candidates, key=lambda value: names[value]):
            non_null = [row for row in by_code[code] if row.get("amount") is not None]
            latest = max(non_null or by_code[code], key=lambda row: row["report_date"])
            metadata = latest.get("report_metadata") or {}
            candidate_items.append({
                "item_name": names[code],
                "latest_report_date": latest.get("report_date"),
                "latest_amount": latest.get("amount"),
                "currency": metadata.get("CURRENCY"),
            })
        failed_items.append({
            "requested_name": requested,
            "reason": "multiple_candidates",
            "match_type": "exact_duplicate" if exact else "keyword_candidates",
            "candidates": candidate_items,
        })
    selected = [row for row in rows if str(row.get("item_code") or "") in selected_codes]
    return selected, failed_items, notes


def get_financial_statements(
    root: str,
    code: str,
    amount_basis: str,
    statements: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    include_versions: bool = False,
    force_refresh: bool = False,
    export_path: str | None = None,
    items: list[str] | None = None,
    report_types: list[str] | None = None,
) -> dict:
    """获取三大财务报表；缓存累计原值，单期金额按最新累计版本现算。"""
    try:
        mc = parse_code(code)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if amount_basis not in VALID_AMOUNT_BASES:
        return {"ok": False, "error": "amount_basis 必须明确为 cumulative 或 single"}
    selected = list(VALID_STATEMENTS) if statements is None else list(statements)
    if not selected or any(statement not in VALID_STATEMENTS for statement in selected):
        return {"ok": False, "error": f"statements 必须是 {list(VALID_STATEMENTS)} 的非空子集"}
    selected = list(dict.fromkeys(selected))
    try:
        if start_date:
            date.fromisoformat(start_date)
        if end_date:
            date.fromisoformat(end_date)
    except ValueError:
        return {"ok": False, "error": "start_date/end_date 必须是 YYYY-MM-DD"}
    if start_date and end_date and start_date > end_date:
        return {"ok": False, "error": "start_date 不能晚于 end_date"}
    if items is not None and (not isinstance(items, list) or not items or any(not str(item).strip() for item in items)):
        return {"ok": False, "error": "items 必须是非空科目名称数组"}
    if report_types is not None and (
        not isinstance(report_types, list)
        or not report_types
        or any(report_type not in VALID_REPORT_TYPES for report_type in report_types)
    ):
        return {"ok": False, "error": f"report_types 必须是 {list(VALID_REPORT_TYPES)} 的非空子集"}

    full_code = f"{mc.code}.{mc.suffix}"
    now = datetime.now(timezone.utc)
    observed_at = now.isoformat()
    notes: list[str] = []
    try:
        bundle = financial_cache.read_bundle(root, full_code)
    except (OSError, ValueError) as exc:
        bundle = None
        notes.append(f"现有财报缓存不可用：{exc}")

    should_refresh = force_refresh or bundle is None or not _financial_cache_is_fresh(bundle, now)
    stale = False
    refresh_error = None
    if should_refresh:
        existing_metadata = bundle.get("metadata") if bundle else None
        fetched = financial_statements.fetch(root, mc, existing_metadata=existing_metadata)
        if not fetched.get("ok"):
            refresh_error = fetched.get("error") or "上游刷新失败"
            if bundle is None:
                return {"ok": False, "code": full_code, "market": mc.market, "error": refresh_error}
            stale = True
            notes.append(f"刷新失败，返回上一批缓存：{refresh_error}")
        else:
            batch_id = uuid.uuid4().hex
            statement_payloads = {}
            for statement in VALID_STATEMENTS:
                existing_statement = bundle.get(statement) if bundle else None
                statement_payloads[statement] = financial_cache.merge_statement(
                    existing_statement,
                    fetched["statements"][statement],
                    code=full_code,
                    market=mc.market,
                    statement=statement,
                    source=fetched.get("source") or "eastmoney",
                    observed_at=observed_at,
                    batch_id=batch_id,
                )
            metadata_payload = {
                "meta": {
                    "code": full_code,
                    "market": mc.market,
                    "update_batch_id": batch_id,
                    "last_successful_update": observed_at,
                    "last_refresh_attempt": observed_at,
                },
                **(fetched.get("metadata") or {}),
            }
            financial_cache.commit_bundle(root, full_code, metadata_payload, statement_payloads)
            bundle = financial_cache.read_bundle(root, full_code)
            notes.extend(fetched.get("notes") or [])

    assert bundle is not None
    rows = _financial_rows(
        bundle,
        selected,
        start_date if amount_basis == "cumulative" else None,
        end_date if amount_basis == "cumulative" else None,
        include_versions if amount_basis == "cumulative" else False,
    )
    if amount_basis == "single":
        rows, skipped_dates = _derive_single_rows(rows)
        rows = [
            row
            for row in rows
            if (not start_date or row["report_date"] >= start_date)
            and (not end_date or row["report_date"] <= end_date)
        ]
        skipped_dates = [
            report_date
            for report_date in skipped_dates
            if (not start_date or report_date >= start_date)
            and (not end_date or report_date <= end_date)
        ]
        notes.append(
            "single 不返回 EPS、每股股息、加权平均股数等非加总科目；这些科目只能从累计报表获取，额外加工由调用方自行处理，工具不提供支持"
        )
        if skipped_dates:
            notes.append(f"{len(skipped_dates)} 个报告期因无法确认累计区间连续性而未生成单期金额")
        if include_versions:
            notes.append("amount_basis=single 只使用各报告期最新累计版本现算；include_versions 不生成历史单期版本")
    if report_types is not None:
        selected_report_types = set(report_types)
        rows = [row for row in rows if _report_type(row) in selected_report_types]
    failed_items: list[dict] = []
    if items is not None:
        requested = list(dict.fromkeys(str(item).strip() for item in items))
        rows, failed_items, match_notes = _filter_financial_items(rows, mc.market, requested)
        notes.extend(match_notes)
    rows = _localize_financial_rows(rows, mc.market)
    last_successful_update = bundle["metadata"].get("meta", {}).get("last_successful_update")
    source_values = sorted(
        {
            str(value)
            for value in (bundle["metadata"].get("sources") or {}).values()
            if value
        }
    )
    result = {
        "ok": True,
        "market": mc.market,
        "code": full_code,
        "statements": selected,
        "amount_basis": amount_basis,
        "include_versions": include_versions,
        "stale": stale,
        "last_successful_update": last_successful_update,
        "refresh_error": refresh_error,
        "source": ",".join(source_values) or "eastmoney",
        "status": "success" if not failed_items else ("partial_success" if rows else "failed"),
        "failed_items": failed_items,
        "notes": notes or None,
        "rows": rows,
    }
    date_range = {
        "start": rows[0]["report_date"] if rows else None,
        "end": rows[-1]["report_date"] if rows else None,
    }
    if export_path:
        _export_financial_csv(export_path, rows)
        result.pop("rows")
        result.update({"path": export_path, "total_items": len(rows), "date_range": date_range})
    elif len(rows) > 200:
        auto_path = os.path.join(
            root,
            "cache",
            "_auto_export",
            f"{full_code}_financial_{amount_basis}_{start_date or 'all'}_{end_date or 'all'}.csv",
        )
        _export_financial_csv(auto_path, rows)
        result.pop("rows")
        result.update(
            {
                "auto_exported": True,
                "path": auto_path,
                "total_items": len(rows),
                "date_range": date_range,
            }
        )
        result["notes"] = (result.get("notes") or []) + [f"数据超过 200 行，已自动导出到 {auto_path}"]
    return result
