# -*- coding: utf-8 -*-
"""行情更新调度：只读覆盖检查、向指定源取批次、独立写字段缓存后再读取。

同组批次由工具调用范围复用；源模块不写业务缓存。来源选择见service._field_chains。
"""

from __future__ import annotations

from market_data_mcp import cache
from market_data_mcp.routing import MarketCode


def commit_quote_batch(root: str, mc: MarketCode, result: dict) -> dict:
    """将成功取数批次按字段落盘；源模块只返回原值。"""
    if not result.get("ok") or "data" not in result:
        return result
    code = f"{mc.code}.{mc.suffix}"
    updated, errors = {}, []
    for field, records in result["data"].items():
        try:
            old = cache.read_cache(root, code, field)
            if not records:
                dr = cache.refresh_cache(root, code, field) if old else None
                if dr:
                    updated[field] = dr
                continue
            # 该字段的唯一来源由调度定义，旧的其他来源不混入当前输出。
            existing = [r for r in old["items"] if r.get("source") == result["source"]] if old else []
            merged = cache.merge_items(existing, records)
            dr = {"start": merged[0]["date"], "end": merged[-1]["date"]}
            cache.write_cache(root, code, field, meta={"code": code, "market": mc.market,
                "field": field, "source": result["source"], "date_range": dr}, items=merged)
            updated[field] = dr
        except (OSError, ValueError) as exc:
            errors.append(f"{field}写入失败：{exc}")
    return {**result, "fields": updated, "notes": (result.get("notes") or []) + errors}


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

    # 仅终点不足时，从缓存实际末日开始重叠一天补拉：既减少请求范围，也允许上游
    # 修订最后一条记录。起点不足时仍按原请求起点补拉。
    fetch_start = start
    if cur is not None:
        dr = cur["meta"].get("date_range") or {}
        c_start, c_end = dr.get("start"), dr.get("end")
        if c_end is not None and (start is None or (c_start is not None and c_start <= start)):
            fetch_start = c_end

    notes = []
    last_error = None
    for fetcher in chain:
        r = fetcher(root, mc, start=fetch_start, end=end)
        r = commit_quote_batch(root, mc, r)
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
