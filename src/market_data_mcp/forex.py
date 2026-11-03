"""汇率本地历史与新增日期调度；行为规范见架构§2.7。"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from market_data_mcp import aggregator
from market_data_mcp.routing import MarketCode

CODES = ("HKDCNY.FX", "USDHKD.FX", "USDCNY.IN")
HISTORY_PATH = Path(__file__).resolve().parent / "data" / "fx_history.csv"
HISTORY_START = "1995-01-01"
HISTORY_END = "2026-09-30"
LIVE_START = "2026-10-01"


@lru_cache(maxsize=1)
def read_history() -> dict[str, dict[str, float | None]]:
    """读取唯一固化CSV；空单元格保留为None，不联网或补写缓存。"""
    with HISTORY_PATH.open(encoding="utf-8", newline="") as stream:
        return {row["date"]: {code: float(row[code]) if row[code] else None
                              for code in CODES}
                for row in csv.DictReader(stream)}


def ensure_close(root: str, mc: MarketCode, start: str, end: str | None) -> dict:
    """固定分界独立于有效值范围，历史缺值也视为已经覆盖。"""
    from market_data_mcp.providers import ifind

    code = f"{mc.code}.{mc.suffix}"
    end = end or date.today().isoformat()
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        return {"ok": False, "error": "开始日期不能晚于结束日期"}
    items, notes = [], []
    historical_end = min(last, date.fromisoformat(HISTORY_END))
    if first <= historical_end:
        history = read_history()
        day = first
        while day <= historical_end:
            stamp = day.isoformat()
            items.append({"date": stamp, "value": history.get(stamp, {}).get(code),
                          "source": "ifind"})
            day += timedelta(days=1)
        notes.append(f"截至{HISTORY_END}使用固化历史；早期无值返回null，不请求iFinD")
    if end > HISTORY_END:
        recent = aggregator.ensure(root, mc, "close", [ifind.fetch_fx],
                                   max(start, LIVE_START), end)
        if not recent["ok"]:
            if not items:
                return recent
            notes.append(f"新增汇率获取失败：{recent.get('error') or recent.get('notes')}；仅返回历史段")
        else:
            items.extend(row for row in recent["items"]
                         if max(start, LIVE_START) <= row["date"] <= end)
            notes.extend(recent.get("notes") or [])
    return {"ok": True, "items": items, "source": "ifind", "notes": notes}
