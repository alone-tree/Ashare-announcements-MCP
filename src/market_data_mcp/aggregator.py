# -*- coding: utf-8 -*-
"""字段聚合器（中层）：读缓存 → 覆盖够直接返回 → 缺字段按独立源链补拉。

架构 §1.8：字段链按字段独立定义（可得性不同则链不同）；补拉时字段链总是从第一源
开始重试，接受对刚失败源的重复请求（东财限流间歇性）；不记录失败状态
（失败 = 缓存未更新，提示重试）；宽写窄读——请求模块把源返回全部列写入缓存，
本层按列名从缓存消费。
"""

from __future__ import annotations

from market_data_mcp import cache
from market_data_mcp.routing import MarketCode, parse_code


def ensure(
    root: str,
    mc: MarketCode,
    data_type: str,
    chain: list,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """确保某缓存数据覆盖 [start, end]（None 侧不约束）。

    chain：请求模块列表（每个可调用 fetch(root, mc, start, end) -> {ok, ...}），
    按字段链顺序尝试。返回 {ok, items, meta, source, notes}；全链失败 ok=False。
    """
    cur = cache.read_cache(root, f"{mc.code}.{mc.suffix}", data_type)
    if cur is not None and cache.coverage(cur.get("meta", {}), start, end):
        return {"ok": True, "items": cur["items"], "meta": cur["meta"],
                "source": cur["meta"].get("source"), "notes": None}

    notes = []
    last_error = None
    cur_before = cur
    for fetcher in chain:
        r = fetcher(root, mc, start=start, end=end)
        if r.get("ok") and r.get("path") is not None:
            cur = cache.read_cache(root, f"{mc.code}.{mc.suffix}", data_type)
            # 确认缓存真实更新（fetcher 返回 path 但未写入/写失败时 updated_at 不变）
            if cur is not None and (
                cur_before is None
                or cur["meta"].get("updated_at") != cur_before["meta"].get("updated_at")
            ):
                return {"ok": True, "items": cur["items"], "meta": cur["meta"],
                        "source": cur["meta"].get("source"), "notes": r.get("notes")}
            # 缓存未被更新：不当作成功，继续链上下一源
            cur = cur_before
        if r.get("ok"):
            # 请求成功但无新数据（无 path）：继续下一源或返回现有缓存
            last_error = None
            notes.append(r.get("notes") or "请求成功但无新数据")
            continue
        last_error = r.get("error") or "未知错误"
        notes.append(f"{r.get('source')}: {last_error}")
        # 失败 = 缓存未更新，不记录失败状态，继续链上下一源（决策 A）
        continue

    if cur is not None:
        # 有缓存但不完整：返回缓存 + 说明缺失
        return {"ok": True, "items": cur["items"], "meta": cur["meta"],
                "source": cur["meta"].get("source"),
                "notes": notes + [f"缓存覆盖不完整（{cur['meta'].get('date_range')}），补拉失败"]}
    return {"ok": False, "items": None, "meta": None, "source": None,
            "notes": notes, "error": last_error or "字段链全失败"}
