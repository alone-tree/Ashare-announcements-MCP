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
import os
import time
from datetime import date, timedelta

from market_data_mcp import aggregator, cache
from market_data_mcp.providers import ifind, sina, yfinance
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
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
