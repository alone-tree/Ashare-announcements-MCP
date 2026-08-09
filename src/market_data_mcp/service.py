# -*- coding: utf-8 -*-
"""market_data_mcp 工具层（service）：组装字段聚合器与请求模块，实现工具契约。

工具契约见 docs/market-data架构设计.md（§1.6/§2）。三层结构：本文件=工具层，
aggregator.py=字段聚合器，providers/=请求模块（源 × 市场 × 档位）。
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

# 返回结构里 vars 顺序：date 恒首列，其余按 vars 传入顺序
_RAW_KEYS = ("open", "high", "low", "close", "volume", "amount", "turnover", "outstanding_share")


def _ensure_raw(root: str, mc: MarketCode, start: str | None, end: str | None) -> dict:
    return aggregator.ensure(root, mc, "quote_daily_raw", [sina.fetch_raw], start, end)


def _ensure_hfq(root: str, mc: MarketCode, start: str | None, end: str | None) -> dict:
    chain = [ifind.fetch_us_hfq] if mc.market == "US" else [sina.fetch_hfq]
    return aggregator.ensure(root, mc, "quote_daily_hfq", chain, start, end)


def _ensure_amount(root: str, mc: MarketCode, start: str | None, end: str | None) -> dict:
    """美股 amount 单源（iFinD）；A/港 amount 在新浪 raw 宽写列里。"""
    if mc.market == "US":
        return aggregator.ensure(root, mc, "quote_daily_amount", [ifind.fetch_us_amount], start, end)
    return {"ok": True, "items": None, "meta": None, "source": "sina", "notes": None}


def _ensure_shares(root: str, mc: MarketCode, start: str | None, end: str | None) -> dict:
    chain = [ifind.fetch_shares, yfinance.fetch_shares] if mc.market in ("HK", "US") else [ifind.fetch_shares]
    return aggregator.ensure(root, mc, "shares", chain, start, end)


def _by_date(items: list[dict] | None) -> dict[str, dict]:
    return {r["date"]: r for r in (items or [])}


def _default_start(end: str) -> str:
    """end 为空时默认起点：最近 10 个交易日（≈14 自然日）。"""
    return (date.fromisoformat(end) - timedelta(days=14)).isoformat()


def _market_cap(raw_by_date: dict, shares_by_date: dict, mc: MarketCode,
                raw_items: list[dict]) -> tuple[dict, dict]:
    """市值现算：total = total_shares × close；float = 流通股本 × close。
    A/B 股流通股本用新浪 outstanding_share（raw 列）；港美股用 iFinD floating_shares。"""
    total, float_ = {}, {}
    # 逐日对齐：close 取 raw，股本取该日最近的 shares 点（前置填充）
    share_dates = sorted(shares_by_date)
    for r in raw_items:
        d = r["date"]
        close = r.get("close")
        if close is None:
            continue
        # 前置填充：取 ≤ d 的最近股本点
        near = [sd for sd in share_dates if sd <= d]
        sr = shares_by_date[near[-1]] if near else None
        total_shares = (sr or {}).get("total_shares")
        if total_shares is not None:
            total[d] = total_shares * close
        if mc.market == "A":
            fs = r.get("outstanding_share")  # 新浪流通股本
        else:
            fs = (sr or {}).get("floating_shares")
        if fs is not None:
            float_[d] = fs * close
    return total, float_


def _resample(rows: list[dict], period: str, keys: tuple) -> list[dict]:
    """周/月线由日线本地聚合（open=周期首日、high=最高、low=最低、close=末日、
    volume/amount=累计；weekly 用 W-FRI、monthly 用 ME）。返回升序周期行。"""
    if period == "daily" or not rows:
        return rows
    from datetime import datetime

    def bucket(d: str) -> str:
        dt = datetime.fromisoformat(d)
        if period == "weekly":
            # W-FRI：本周五
            friday = dt + timedelta(days=(4 - dt.weekday()) % 7)
            return friday.date().isoformat()
        return f"{dt.year:04d}-{dt.month:02d}"

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(bucket(r["date"]), []).append(r)
    out = []
    for b in sorted(groups):
        g = groups[b]
        row: dict = {"date": b}
        for k in keys:
            vals = [x.get(k) for x in g if x.get(k) is not None]
            if k in ("open",):
                row[k] = vals[0] if vals else None
            elif k in ("high",):
                row[k] = max(vals) if vals else None
            elif k in ("low",):
                row[k] = min(vals) if vals else None
            elif k in ("close",):
                row[k] = g[-1].get(k)
            elif k in ("volume", "amount"):
                row[k] = sum(vals) if vals else None
            else:  # 其他（turnover/outstanding_share 等）取末日
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

    # 1. 字段链补拉
    need_raw = bool(set(vars) & set(_RAW_KEYS)) or "total_market_cap" in vars or "float_market_cap" in vars
    need_hfq = adjust in ("hfq", "qfq")
    need_amount = "amount" in vars and mc.market == "US"
    need_shares = "total_market_cap" in vars or "float_market_cap" in vars

    rr = _ensure_raw(root, mc, start, end) if need_raw else {"ok": True, "items": None}
    if not rr["ok"]:
        return {"ok": False, "error": f"行情获取失败：{'；'.join(rr['notes'] or [rr.get('error', '')])}"}
    hr = _ensure_hfq(root, mc, start, end) if need_hfq else {"ok": True, "items": None}
    if not hr["ok"]:
        return {"ok": False, "error": f"后复权获取失败：{'；'.join(hr['notes'] or [hr.get('error', '')])}"}
    ar = _ensure_amount(root, mc, start, end) if need_amount else {"ok": True, "items": None}
    if not ar["ok"]:
        return {"ok": False, "error": f"成交额获取失败：{'；'.join(ar['notes'] or [ar.get('error', '')])}"}
    sr = _ensure_shares(root, mc, start, end) if need_shares else {"ok": True, "items": None}
    if not sr["ok"]:
        return {"ok": False, "error": f"股本获取失败：{'；'.join(sr['notes'] or [sr.get('error', '')])}"}

    raw_items = rr["items"] or []
    raw_by_date = _by_date(raw_items)
    # 2. 组装 base rows（raw 列）
    rows = [dict(r) for r in raw_items if start <= r["date"] <= end]

    # 3. 美股 amount（iFinD 独立缓存）
    if need_amount:
        amt_by_date = _by_date(ar["items"])
        for r in rows:
            a = amt_by_date.get(r["date"])
            r["amount"] = a.get("amt") if a else None

    # 4. 复权
    if need_hfq:
        hfq_by_date = _by_date(hr["items"])
        if adjust == "hfq":
            for r in rows:
                h = hfq_by_date.get(r["date"])
                if h and h.get("close") is not None and r.get("close"):
                    # 逐日因子还原 OHL：hfq_OHL(t) = raw_OHL(t) × F(t)
                    f = h["close"] / r["close"]
                    for k in ("open", "high", "low", "close"):
                        if r.get(k) is not None:
                            r[k] = round(r[k] * f, 4)
                else:
                    for k in ("open", "high", "low", "close"):
                        r[k] = h.get("close") if k == "close" and h else None
        else:  # qfq：前复权本地现算，不落盘
            latest_raw = next((r for r in reversed(rows) if r.get("close") is not None), None)
            if latest_raw:
                lh = hfq_by_date.get(latest_raw["date"])
                if lh and lh.get("close"):
                    scale = latest_raw["close"] / lh["close"]
                    for r in rows:
                        h = hfq_by_date.get(r["date"])
                        if h and h.get("close") is not None and r.get("close"):
                            f = h["close"] / r["close"] * scale
                            for k in ("open", "high", "low", "close"):
                                if r.get(k) is not None:
                                    r[k] = round(r[k] * f, 4)
                else:
                    notes.append("后复权数据缺失，前复权计算不完整")
            else:
                notes.append("无最新收盘价，前复权未计算")

    # 5. 市值现算（基于不复权 close —— 市值 = 股本 × 当日不复权收盘）
    if "total_market_cap" in vars or "float_market_cap" in vars:
        raw_rows = [r for r in raw_items if start <= r["date"] <= end]
        total_cap, float_cap = _market_cap(raw_by_date, _by_date(sr["items"]), mc, raw_rows)
        for r in rows:
            if "total_market_cap" in vars:
                r["total_market_cap"] = total_cap.get(r["date"])
            if "float_market_cap" in vars:
                r["float_market_cap"] = float_cap.get(r["date"])
        notes.append("总市值/流通市值为估算值（股本 × 不复权收盘价）")

    # 6. 周/月聚合
    if period != "daily":
        rows = _resample(rows, period, tuple(vars))
        notes.append(f"{period} 线由日线本地聚合（{'W-FRI' if period == 'weekly' else '月度'}）")

    # 7. 列过滤（date 恒首列）
    cols = ["date"] + [v for v in vars]
    out_rows = [{k: r.get(k) for k in cols} for r in rows]
    if not out_rows:
        return {"ok": True, "market": mc.market, "code": f"{mc.code}.{mc.suffix}",
                "start": start, "end": end, "adjust": adjust, "period": period,
                "vars": vars, "source": rr.get("source") if rr.get("source") else None,
                "notes": notes + ["请求范围内无数据"], "rows": []}

    date_range = {"start": out_rows[0]["date"], "end": out_rows[-1]["date"]}
    source = rr.get("source") if rr.get("source") else (hr.get("source") if need_hfq else None)
    if need_amount and mc.market == "US":
        source = f"{source or ''},ifind" if source else "ifind"
    notes += [n for n in (rr.get("notes") or []) if n]
    notes += [n for n in (hr.get("notes") or []) if n]
    notes += [n for n in (ar.get("notes") or []) if n]
    notes += [n for n in (sr.get("notes") or []) if n]

    # 8. 导出
    if export_path:
        _export_csv(export_path, out_rows, cols)
        return {"ok": True, "path": export_path, "total_items": len(out_rows),
                "date_range": date_range, "source": source, "notes": notes or None}
    if len(out_rows) > 200:
        auto_path = os.path.join(root, "cache", "_auto_export",
                                 f"{mc.code}.{mc.suffix}_{adjust}_{period}_{start}_{end}.csv")
        _export_csv(auto_path, out_rows, cols)
        return {"ok": True, "auto_exported": True, "path": auto_path,
                "total_items": len(out_rows), "date_range": date_range,
                "source": source, "notes": notes + [f"数据超过 200 行，已自动导出到 {auto_path}"]}

    return {"ok": True, "market": mc.market, "code": f"{mc.code}.{mc.suffix}",
            "start": start, "end": end, "adjust": adjust, "period": period,
            "vars": vars, "source": source, "notes": notes or None, "rows": out_rows}
