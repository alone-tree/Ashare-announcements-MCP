# -*- coding: utf-8 -*-
"""iFinD 请求模块（源 × 市场 × 档位）。

当前实现：
- `fetch_us_hfq`：**美股后复权 close**（iFinD 单源，全程分红再投口径，无回退）：
  ① THS_HQ 探测 .O/.N 后缀（脚本不猜，O 错试 N，都不对报错）
  ② THS_DS `close_price` + `107,OC` 近 5 年序列（窗口从【今天】往前 5 年，服务端视角）
  ③ THS_BD `日期,107,OC` 单点按纽交所交易日历（THS_Date_Query 212010）逐日补 5 年前
- （股本模块后续加入：THS_DS total_shares/floating_shares 近 5 年 + THS_BD 月频单点）

**铁律：iFinD 参数严禁猜测/试探变体**——所有参数写法来自官方手册与实测
（字段与数据源支持情况.md §7/§9，2026-08-09 用户提供公式速查；单点格式
`'2026-08-07,107,OC'` 2026-08-09 实测：与 THS_DS 107 同日期完全一致）。
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
DATA_TYPE = "quote_daily_hfq"

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


def _merge(existing: list[dict] | None, fresh: list[dict]) -> list[dict]:
    by_date = {r["date"]: r for r in (existing or [])}
    for r in fresh:
        by_date[r["date"]] = r
    return sorted(by_date.values(), key=lambda r: r["date"])


def fetch_us_hfq(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求美股后复权 close（iFinD，分红再投）并写缓存（date+close）。
    返回 {ok, source, path, new_items, date_range, error, notes}；单点补全部分失败不丢弃（notes 标注）。"""
    code = f"{mc.code}.{mc.suffix}"
    t0 = time.time()
    try:
        _ensure_login(root)
        full = mc.code + _detect_suffix(root, mc.code)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_HQ/THS_iFinDLogin",
                          adjust="hfq", start=start, end=end, ok=False, elapsed=elapsed, error=str(exc))
        return {"ok": False, "source": SOURCE, "path": None, "new_items": 0,
                "date_range": None, "error": str(exc), "notes": None}

    notes: list[str] = []
    today = date.today()
    ds_start = _five_years_ago(today)
    end_d = min(end or today.isoformat(), today.isoformat())
    fresh: list[dict] = []

    # ② THS_DS 近 5 年序列（仅当请求段与 5 年窗口有交集）
    if end_d >= ds_start.isoformat():
        ds_beg = max(start or ds_start.isoformat(), ds_start.isoformat())
        r = ths.THS_DS(full, "close_price", "107,OC", "", ds_beg, end_d)
        if r.errorcode != 0:
            elapsed = time.time() - t0
            audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS",
                              adjust="hfq", start=ds_beg, end=end_d, ok=False, elapsed=elapsed,
                              error=str(r.errmsg))
            return {"ok": False, "source": SOURCE, "path": None, "new_items": 0,
                    "date_range": None, "error": f"iFinD THS_DS 请求失败：{r.errmsg}", "notes": None}
        if r.data is not None and len(r.data):
            for _, row in r.data.iterrows():
                fresh.append({"date": str(row["time"]), "close": _clean_value(row["close_price"])})
            audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS",
                              fields="close_price(107,OC)", adjust="hfq", start=ds_beg, end=end_d,
                              ok=True, elapsed=time.time() - t0)

    # ③ THS_BD 单点补 5 年前（先近后远；跳过缓存已覆盖日期）
    if start is not None and start < ds_start.isoformat():
        existing = cache.read_cache(root, code, DATA_TYPE)
        covered = {r["date"] for r in existing["items"]} if existing else set()
        days = [d for d in _trade_days(start, (ds_start - timedelta(days=1)).isoformat()) if d not in covered]
        fail = 0
        for d in reversed(days):  # 先近后远：中断只丢最老数据
            r = ths.THS_BD(full, "close_price", f"{d},107,OC")
            if r.errorcode != 0 or r.data is None or len(r.data) == 0:
                fail += 1
                if fail <= 3:
                    notes.append(f"{d} 单点失败")
                continue
            fresh.append({"date": d, "close": _clean_value(r.data.iloc[0]["close_price"])})
            time.sleep(0.05)  # 串行限速，防配额过快
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_BD",
                          fields="close_price(107,OC)", adjust="hfq", start=start,
                          end=(ds_start - timedelta(days=1)).isoformat(), ok=fail == 0,
                          elapsed=time.time() - t0, error=f"失败 {fail} 个单点" if fail else None)
        if fail:
            notes.append(f"单点补全失败 {fail} 个交易日（缺失范围见日志）")

    if not fresh:
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                          adjust="hfq", start=start, end=end, ok=True, elapsed=elapsed)
        return {"ok": True, "source": SOURCE, "path": None, "new_items": 0,
                "date_range": None, "error": None, "notes": notes or None}

    existing = cache.read_cache(root, code, DATA_TYPE)
    existing_items = existing["items"] if existing else None
    merged = _merge(existing_items, fresh)
    date_range = {"start": merged[0]["date"], "end": merged[-1]["date"]}
    path = cache.write_cache(
        root, code, DATA_TYPE,
        meta={"code": code, "market": mc.market, "data_type": DATA_TYPE,
              "source": SOURCE, "date_range": date_range},
        items=merged,
    )
    audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                      fields="close_price(107,OC)", adjust="hfq", start=start, end=end,
                      ok=True, elapsed=time.time() - t0)
    return {"ok": True, "source": SOURCE, "path": path, "new_items": len(fresh),
            "date_range": date_range, "error": None, "notes": notes or None}
