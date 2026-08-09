# -*- coding: utf-8 -*-
"""字段聚合器（中层）：读字段缓存 → 覆盖够直接返回 → 缺字段按独立源链补拉。

架构 §1.8（2026-08-09 用户拍板字段级缓存）：每个字段独立 json（items [{date,value,source}]），
字段链按字段独立定义；补拉时字段链总是从第一源开始重试，接受对刚失败源的重复请求
（间歇性故障可能撞上恢复窗口）；不记录失败状态（失败 = 缓存未更新，提示重试）。
请求模块"拉到什么写什么"——一次上游请求更新多个字段文件，本层按字段名从缓存消费，
同字段异 source 记录并存（merge 按 (date,source)），读取时按字段链优先级取源。
"""

from __future__ import annotations

from market_data_mcp import cache
from market_data_mcp.routing import MarketCode


def ensure(
    root: str,
    mc: MarketCode,
    field: str,
    chain: list,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """确保某字段缓存覆盖 [start, end]（None 侧不约束）。

    chain：请求模块列表（每个可调用 fetch(root, mc, start, end) -> {ok, source, fields, error, notes}，
    fields 为本次更新的字段名集合），按字段链顺序尝试。
    返回 {ok, items, source, notes}；items 为 [{date, value, source}]（可能多源并存）。
    """
    code = f"{mc.code}.{mc.suffix}"
    cur = cache.read_cache(root, code, field)
    if cur is not None and cache.coverage(cur["meta"], start, end, market=mc.market):
        return {"ok": True, "items": cur["items"], "source": cur["meta"].get("source"),
                "notes": None}

    notes = []
    last_error = None
    for fetcher in chain:
        r = fetcher(root, mc, start=start, end=end)
        if r.get("ok") and field in (r.get("fields") or {}):
            # fetcher 只在写缓存成功后返回 fields 声明——重新读缓存确认即可
            cur = cache.read_cache(root, code, field)
            if cur is not None:
                return {"ok": True, "items": cur["items"], "source": r.get("source"),
                        "notes": r.get("notes")}
            # 读不到缓存：不当作成功，继续链上下一源
        if r.get("ok"):
            # 请求成功但未更新该字段（该源不覆盖此字段/无新数据）：继续链上下一源
            last_error = None
            notes.append(r.get("notes") or "请求成功但未更新该字段")
            continue
        last_error = r.get("error") or "未知错误"
        notes.append(f"{r.get('source')}: {last_error}")
        # 失败 = 缓存未更新，不记录失败状态，继续链上下一源（决策 A）
        continue

    if cur is not None:
        # 有缓存但不完整：返回缓存 + 说明缺失
        return {"ok": True, "items": cur["items"], "source": cur["meta"].get("source"),
                "notes": notes + [f"缓存覆盖不完整（{cur['meta'].get('date_range')}），补拉失败"]}
    return {"ok": False, "items": None, "source": None,
            "notes": notes, "error": last_error or "字段链全失败"}
