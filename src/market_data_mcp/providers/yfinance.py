# -*- coding: utf-8 -*-
"""yfinance 请求模块（港美股股本回退通道）。

用途：iFinD 股本失败时的回退（架构 §2.4：港美股 iFinD → yfinance）。
- 港股：Yahoo 代码 4 位带前导零（00700.HK → 0700.HK，与 iFinD 格式一致）
- 美股：字母 ticker（AAPL）
- 接口：`Ticker.get_shares_full(start, end)` 逐日股本（yfinance 1.5.2 实测，
  2026-08-09；旧文档的"年度 5 期/季度 2 年/事件点 10 年"三档 balance_sheet 方式已过时）
- 写入：total_shares 字段（items [{date,value,source}]）；**缓存已有更高优先级源
  （iFinD）数据时不落盘**——yfinance Ordinary Shares 扣库存股，与 iFinD 口径不同，
  不跨源混写（用户 2026-08-09 拍板：items 带 source、同字段异源不互覆盖）

**代理要求**：yfinance 必须走代理 127.0.0.1:17891（直连被 Yahoo 限流，与国内源相反）。
代理只在函数内设置/恢复，不与其他 provider（新浪/iFinD 清代理）互相踩。
"""

from __future__ import annotations

import os
import time

import yfinance as yf

from market_data_mcp import audit, cache
from market_data_mcp.routing import MarketCode

SOURCE = "yfinance"
FIELD = "total_shares"

_PROXY = "http://127.0.0.1:17891"
_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")


def _ticker(mc: MarketCode) -> str:
    if mc.market == "HK":
        bare = mc.code.lstrip("0") or "0"
        return bare.zfill(4) + ".HK"  # Yahoo 港股代码 4 位带前导零
    return mc.code  # US 字母


def fetch_shares(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求 yfinance 股本（total_shares，逐日）并写缓存。仅港美股。
    返回 {ok, source, fields, error, notes}。"""
    if mc.market not in ("HK", "US"):
        return {"ok": False, "source": SOURCE, "fields": {},
                "error": f"yfinance 仅支持港美股（收到 {mc.market}）", "notes": None}
    code = f"{mc.code}.{mc.suffix}"
    ticker = _ticker(mc)
    t0 = time.time()
    for k in _PROXY_KEYS:
        os.environ[k] = _PROXY
    try:
        df = yf.Ticker(ticker).get_shares_full(start, end)
    except Exception as exc:  # noqa: BLE001
        for k in _PROXY_KEYS:
            os.environ.pop(k, None)
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code,
                          api="Ticker.get_shares_full", fields=FIELD,
                          start=start, end=end, ok=False, elapsed=elapsed, error=str(exc))
        return {"ok": False, "source": SOURCE, "fields": {},
                "error": f"yfinance 股本请求失败：{exc}", "notes": None}
    finally:
        for k in _PROXY_KEYS:
            os.environ.pop(k, None)

    fresh = []
    if df is not None and len(df):
        for ts, v in df.items():
            if v is None:
                continue
            fresh.append({"date": ts.strftime("%Y-%m-%d"), "value": float(v)})

    if not fresh:
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code,
                          api="Ticker.get_shares_full", fields=FIELD,
                          start=start, end=end, ok=True, elapsed=elapsed)
        return {"ok": True, "source": SOURCE, "fields": {}, "error": None, "notes": None}

    # 缓存已有更高优先级源（iFinD）数据：回退数据不落盘，避免覆盖/混源
    existing = cache.read_cache(root, code, FIELD)
    if existing and existing.get("meta", {}).get("source") != SOURCE:
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code,
                          api="Ticker.get_shares_full", fields=FIELD,
                          start=start, end=end, ok=True, elapsed=elapsed)
        return {"ok": True, "source": SOURCE, "fields": {}, "error": None,
                "notes": f"缓存已有更高优先级源（{existing['meta']['source']}）股本数据，yfinance 回退未落盘"}

    items = [{"date": r["date"], "value": r["value"], "source": SOURCE} for r in fresh]
    existing_items = existing["items"] if existing else None
    merged = cache.merge_items(existing_items, items)
    date_range = {"start": merged[0]["date"], "end": merged[-1]["date"]}
    path = cache.write_cache(root, code, FIELD,
                             meta={"code": code, "market": mc.market, "field": FIELD,
                                   "source": SOURCE, "date_range": date_range},
                             items=merged)
    elapsed = time.time() - t0
    audit.log_request(root, source=SOURCE, market=mc.market, code=code,
                      api="Ticker.get_shares_full", fields=FIELD,
                      start=start, end=end, ok=True, elapsed=elapsed)
    return {"ok": True, "source": SOURCE, "fields": {FIELD: date_range},
            "error": None, "notes": None}
