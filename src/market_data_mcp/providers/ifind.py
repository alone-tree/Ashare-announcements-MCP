# -*- coding: utf-8 -*-
"""iFinD 请求模块（源 × 市场 × 档位）。

当前实现（拉到什么写什么，2026-08-09 用户拍板：字段级独立 json，items [{date,value,source}]）：
- `fetch_us_hfq`：**美股后复权收盘**（iFinD 单源，全程分红再投口径，无回退）→ 写 close_hfq
  （① THS_HQ 探测 .O/.N 后缀 → ② THS_DS `close_price`+`107,OC` 近 5 年序列
   → ③ THS_BD `日期,107,OC` 单点按纽交所交易日历逐日补 5 年前）
- `fetch_us_amount`：**美股成交额**（iFinD 单源）→ 写 amount
  （THS_DS `amt`+`OC` 近 5 年 + THS_BD 单点逐日补 5 年前；**单点非交易日返回空值**，
  必须严格按交易日历，不能用股本方案的日历月末采样）
- `fetch_shares`：**全市场股本**（iFinD 主源）→ 写 total_shares + floating_shares
  （THS_DS 近 5 年逐日 + THS_BD 月频单点补更早，日历月末采样）

**铁律：iFinD 参数严禁猜测/试探变体**——所有参数写法来自官方手册与实测
（字段与数据源支持情况.md §7/§9，2026-08-09 用户提供公式速查）。
月度配额（用户提供官方信息）：THS_BD 60万 / THS_DS 60万 / THS_HQ 100万数据点，独立限额不共享。
国内服务，清代理直连。登录惰性一次（THS_iFinDLogin），退出 THS_iFinDLogout。
"""

from __future__ import annotations

import math
import os
import time
from datetime import date, timedelta

import iFinDPy as ths

from market_data_mcp import audit, cache
from market_data_mcp.routing import MarketCode

# iFinD 为国内服务：清代理直连（与新浪/东财一致）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

SOURCE = "ifind"

_LOGIN_STATE = {"done": False}
_SUFFIX_CACHE: dict[str, str] = {}

# 纽交所交易日历代码（美股 NYSE/NASDAQ/AMEX 统一日历，2026-08-09 实测）
_NYSE_CALENDAR = "212010"


def _load_accounts(root: str) -> tuple[str, str]:
    """从 .secrets/ifind_accounts.txt 读账号2（jdkgjt009 可用，账号1 不可用）。"""
    path = os.path.join(root, ".secrets", "ifind_accounts.txt")
    if not os.path.exists(path):
        path = os.path.join(os.getcwd(), ".secrets", "ifind_accounts.txt")
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    for i, l in enumerate(lines):
        if l.startswith("账号2："):
            return l.split("：", 1)[1].strip(), lines[i + 1].split("：", 1)[1].strip()
    raise RuntimeError(".secrets/ifind_accounts.txt 中未找到账号2")


def _ensure_login(root: str) -> None:
    if _LOGIN_STATE["done"]:
        return
    acc, pwd = _load_accounts(root)
    code = ths.THS_iFinDLogin(acc, pwd)
    if code != 0:
        raise RuntimeError(f"iFinD 登录失败（errorcode={code}）")
    _LOGIN_STATE["done"] = True


def _clean_value(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _detect_suffix(root: str, base: str) -> str:
    """THS_HQ 探测美股 .O/.N 后缀（周线有数据即后缀正确）。结果进程内缓存。"""
    if base in _SUFFIX_CACHE:
        return _SUFFIX_CACHE[base]
    end_d = date.today()
    start_d = end_d - timedelta(days=10)
    for s in (".O", ".N"):
        r = ths.THS_HQ(base + s, "close", "Interval:W", start_d.isoformat(), end_d.isoformat())
        if r.errorcode == 0 and r.data is not None and len(r.data) > 0:
            _SUFFIX_CACHE[base] = s
            return s
    raise RuntimeError(f"美股 {base} 的 iFinD 后缀探测失败（.O/.N 均无数据）")


def _trade_days(start: str, end: str) -> list[str]:
    """纽交所交易日列表（THS_Date_Query 212010，返回逗号分隔日期串）。"""
    r = ths.THS_Date_Query(_NYSE_CALENDAR, "mode:1,dateType:0,period:D,dateFormat:0", start, end)
    if r.errorcode != 0 or not r.data:
        raise RuntimeError(f"iFinD 交易日历请求失败：{r.errmsg}")
    return [d for d in str(r.data).split(",") if d]


def _five_years_ago(today: date) -> date:
    try:
        return today.replace(year=today.year - 5)
    except ValueError:  # 2/29 无对应日
        return date(today.year - 5, 12, 31)


def _write_field(root: str, code: str, market: str, field: str, fresh: list[dict]) -> dict | None:
    """写单个字段缓存（同源合并）。fresh 为 [{date, value}]。返回 date_range。"""
    items = [{"date": r["date"], "value": r["value"], "source": SOURCE} for r in fresh]
    existing = cache.read_cache(root, code, field)
    existing_items = existing["items"] if existing else None
    merged = cache.merge_items(existing_items, items)
    date_range = None
    if merged:
        date_range = {"start": merged[0]["date"], "end": merged[-1]["date"]}
    cache.write_cache(root, code, field,
                      meta={"code": code, "market": market, "field": field,
                            "source": SOURCE, "date_range": date_range},
                      items=merged)
    return date_range


def _fetch_us_daily(
    root: str,
    mc: MarketCode,
    *,
    indicator: str,
    param: str,
    field: str,
    adjust: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """iFinD 美股逐日序列通用链路（hfq close / amount 共用）：

    ① THS_HQ 探测 .O/.N 后缀 → ② THS_DS 近 5 年序列（窗口从今天倒推，服务端视角）
    → ③ THS_BD 单点按纽交所交易日历（THS_Date_Query 212010）逐日补 5 年前，先近后远。
    返回 {ok, source, fields, error, notes}；部分失败不丢弃（notes 标注）。
    """
    code = f"{mc.code}.{mc.suffix}"
    t0 = time.time()
    try:
        _ensure_login(root)
        full = mc.code + _detect_suffix(root, mc.code)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_HQ/THS_iFinDLogin",
                          fields=indicator, adjust=adjust, start=start, end=end,
                          ok=False, elapsed=elapsed, error=str(exc))
        return {"ok": False, "source": SOURCE, "fields": {}, "error": str(exc), "notes": None}

    notes: list[str] = []
    today = date.today()
    ds_start = _five_years_ago(today)
    end_d = min(end or today.isoformat(), today.isoformat())
    fresh: list[dict] = []

    # ② THS_DS 近 5 年序列（仅当请求段与 5 年窗口有交集）
    if end_d >= ds_start.isoformat():
        ds_beg = max(start or ds_start.isoformat(), ds_start.isoformat())
        r = ths.THS_DS(full, indicator, param, "", ds_beg, end_d)
        if r.errorcode != 0:
            elapsed = time.time() - t0
            audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS",
                              fields=indicator, adjust=adjust, start=ds_beg, end=end_d,
                              ok=False, elapsed=elapsed, error=str(r.errmsg))
            return {"ok": False, "source": SOURCE, "fields": {},
                    "error": f"iFinD THS_DS 请求失败：{r.errmsg}", "notes": None}
        if r.data is not None and len(r.data):
            for _, row in r.data.iterrows():
                fresh.append({"date": str(row["time"]), "value": _clean_value(row[indicator])})
            audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS",
                              fields=f"{indicator}({param})", adjust=adjust, start=ds_beg, end=end_d,
                              ok=True, elapsed=time.time() - t0)

    # ③ THS_BD 单点补 5 年前（严格按交易日历，先近后远；跳过缓存已覆盖日期）
    if start is not None and start < ds_start.isoformat():
        existing = cache.read_cache(root, code, field)
        covered = {r["date"] for r in existing["items"] if r.get("source") == SOURCE} if existing else None
        days = [d for d in _trade_days(start, (ds_start - timedelta(days=1)).isoformat())]
        if covered:
            days = [d for d in days if d not in covered]
        fail = 0
        for d in reversed(days):  # 先近后远：中断只丢最老数据
            r = ths.THS_BD(full, indicator, f"{d},{param}")
            if r.errorcode != 0 or r.data is None or len(r.data) == 0:
                fail += 1
                if fail <= 3:
                    notes.append(f"{d} 单点失败")
                continue
            fresh.append({"date": d, "value": _clean_value(r.data.iloc[0][indicator])})
            time.sleep(0.05)  # 串行限速，防配额过快
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_BD",
                          fields=f"{indicator}({param})", adjust=adjust, start=start,
                          end=(ds_start - timedelta(days=1)).isoformat(), ok=fail == 0,
                          elapsed=time.time() - t0, error=f"失败 {fail} 个单点" if fail else None)
        if fail:
            notes.append(f"单点补全失败 {fail} 个交易日（缺失范围见日志）")

    if not fresh:
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                          fields=indicator, adjust=adjust, start=start, end=end,
                          ok=True, elapsed=elapsed)
        return {"ok": True, "source": SOURCE, "fields": {}, "error": None, "notes": notes or None}

    date_range = _write_field(root, code, mc.market, field, fresh)
    audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                      fields=f"{indicator}({param})", adjust=adjust, start=start, end=end,
                      ok=True, elapsed=time.time() - t0)
    return {"ok": True, "source": SOURCE, "fields": {field: date_range},
            "error": None, "notes": notes or None}


def fetch_us_hfq(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求美股后复权收盘（iFinD，分红再投）→ 写 close_hfq（date/value/source）。"""
    return _fetch_us_daily(root, mc, indicator="close_price", param="107,OC",
                           field="close_hfq", adjust="hfq", start=start, end=end)


def fetch_us_amount(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求美股成交额 amt（iFinD，单源无回退）→ 写 amount（date/value/source）。

    公式（用户提供官方版，2026-08-09 实测）：THS_DS('AAPL.O','amt','OC','',...) 近 5 年
    仅交易日行；THS_BD('AAPL.O','amt','日期,OC') 单点，非交易日返回空值——
    5 年前补全必须严格按交易日历逐日（不能用股本方案的日历月末采样）。
    """
    return _fetch_us_daily(root, mc, indicator="amt", param="OC",
                           field="amount", start=start, end=end)


def _month_ends(start: str, end: str) -> list[str]:
    """[start, end] 内每月日历月末日（THS_BD 非交易日自动返回最近交易日值，
    日历月末请求 = 该月最后一个交易日股本，与交易日历月末一致，省日历调用）。"""
    import calendar

    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        d = f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
        if d > end:
            break  # 升序：该月月末已超出 end，后续月份更大
        out.append(d)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fetch_shares(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求股本（total_shares/floating_shares）→ 分写两个字段 json。

    iFinD 近 5 年 THS_DS 序列 + 更早 THS_BD 月频单点（先近后远），部分失败不丢弃（notes 标注）。
    代码格式：A/B/北交所原样（600519.SH/920002.BJ），港股 4 位带前导零（0700.HK），
    美股探测 .O/.N。返回 {ok, source, fields, error, notes}。
    """
    code = f"{mc.code}.{mc.suffix}"
    t0 = time.time()
    try:
        _ensure_login(root)
        if mc.market == "US":
            full = mc.code + _detect_suffix(root, mc.code)
        else:
            from market_data_mcp.routing import to_ifind
            full = to_ifind(mc)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_HQ/THS_iFinDLogin",
                          fields="total_shares;floating_shares", start=start, end=end,
                          ok=False, elapsed=elapsed, error=str(exc))
        return {"ok": False, "source": SOURCE, "fields": {}, "error": str(exc), "notes": None}

    notes: list[str] = []
    today = date.today()
    ds_start = _five_years_ago(today)
    end_d = min(end or today.isoformat(), today.isoformat())
    fresh: list[dict] = []

    # ① THS_DS 近 5 年逐日
    if end_d >= ds_start.isoformat():
        ds_beg = max(start or ds_start.isoformat(), ds_start.isoformat())
        r = ths.THS_DS(full, "total_shares;floating_shares", ";", "", ds_beg, end_d)
        if r.errorcode != 0:
            elapsed = time.time() - t0
            audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS",
                              fields="total_shares;floating_shares", start=ds_beg, end=end_d,
                              ok=False, elapsed=elapsed, error=str(r.errmsg))
            return {"ok": False, "source": SOURCE, "fields": {},
                    "error": f"iFinD THS_DS 股本请求失败：{r.errmsg}", "notes": None}
        if r.data is not None and len(r.data):
            for _, row in r.data.iterrows():
                fresh.append({"date": str(row["time"]),
                              "total_shares": _clean_value(row["total_shares"]),
                              "floating_shares": _clean_value(row["floating_shares"])})

    # ② THS_BD 月频单点补 [start, ds_start)，先近后远；跳过缓存已覆盖日期
    if start is not None and start < ds_start.isoformat():
        existing = cache.read_cache(root, code, "total_shares")
        covered = {r["date"] for r in existing["items"] if r.get("source") == SOURCE} if existing else None
        months = _month_ends(start, (ds_start - timedelta(days=1)).isoformat())
        if covered:
            months = [d for d in months if d not in covered]
        fail = 0
        for d in reversed(months):  # 先近后远：中断只丢最老数据
            r = ths.THS_BD(full, "total_shares;floating_shares", f"{d};{d}")
            if r.errorcode != 0 or r.data is None or len(r.data) == 0:
                fail += 1
                if fail <= 3:
                    notes.append(f"{d} 单点失败")
                continue
            row = r.data.iloc[0]
            fresh.append({"date": d,
                          "total_shares": _clean_value(row["total_shares"]),
                          "floating_shares": _clean_value(row["floating_shares"])})
            time.sleep(0.05)
        if fail:
            notes.append(f"股本月频补全失败 {fail} 个月点（缺失范围见日志）")
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_BD",
                          fields="total_shares;floating_shares", start=start,
                          end=(ds_start - timedelta(days=1)).isoformat(), ok=fail == 0,
                          elapsed=time.time() - t0, error=f"失败 {fail} 个单点" if fail else None)

    if not fresh:
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                          fields="total_shares;floating_shares", start=start, end=end,
                          ok=True, elapsed=elapsed)
        return {"ok": True, "source": SOURCE, "fields": {}, "error": None, "notes": notes or None}

    fields = {
        "total_shares": _write_field(root, code, mc.market, "total_shares",
                                     [{"date": r["date"], "value": r["total_shares"]} for r in fresh]),
    }
    # floating_shares 字段归属：A/北交所 = sina（outstanding_share，全历史逐日，用户拍板口径）；
    # 港美股 = iFinD（新浪港股/美股无股本列）。避免同字段同日期双写（2026-08-09 用户指出）。
    if mc.market in ("HK", "US"):
        fields["floating_shares"] = _write_field(
            root, code, mc.market, "floating_shares",
            [{"date": r["date"], "value": r["floating_shares"]} for r in fresh])
    audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                      fields="total_shares;floating_shares", start=start, end=end,
                      ok=True, elapsed=time.time() - t0)
    return {"ok": True, "source": SOURCE, "fields": fields, "error": None, "notes": notes or None}
