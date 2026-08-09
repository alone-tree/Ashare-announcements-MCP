# -*- coding: utf-8 -*-
"""公司信息 section 聚合器与工具入口（get_company_profile）。

架构 docs/market-data架构设计.md §5（2026-08-09 定稿）：
- 五类 sections：profile/ipo/dividends/forecast/holders；按 section 分缓存文件
- 多源合并策略 A：主源优先、缺的信息从补充源补（每字段单一来源）；
  **无失败回退**（主源失败即结构化报错，可重试）；补充源仅字段补全，不参与失败回退
- 刷新：30 天新鲜期 + force_refresh（与财报一致）
- 美股 section：返回 available=false + "用公告 MCP 查 SEC" 提示（不是错误）
- 港股 profile：公司概况 + 证券资料两接口字段并集

数据形态：上游字段名原样保留（不映射、不翻译）。
"""

from __future__ import annotations

from typing import Any, Callable

from market_data_mcp import company_cache
from market_data_mcp.providers import company_info
from market_data_mcp.routing import MarketCode, parse_code

VALID_SECTIONS = ("profile", "ipo", "dividends", "forecast", "holders")

_US_REASON = "美股无结构化公司信息，请用公告 MCP 查询 SEC 提交（get_company_profile 不提供）"
_HK_US_REASON = "该市场无结构化数据，请用公告 MCP 查询公告原文"


# section → 市场 → (主源 fetcher, [补充源 fetcher])
# 补充源只做字段补全；None = 该市场无可用来源（返回 available=false）
_SECTION_PLAN: dict[str, dict[str, Any]] = {
    "profile": {
        "A": (company_info.fetch_cninfo_profile, []),
        "BJ": (company_info.fetch_cninfo_profile, []),
        "HK": (company_info.fetch_hk_company_profile,
               [company_info.fetch_hk_security_profile]),  # 两接口字段并集（互补无重叠）
        "US": None,
    },
    "ipo": {
        "A": (company_info.fetch_cninfo_ipo, [company_info.fetch_sina_ipo]),
        "BJ": (company_info.fetch_cninfo_ipo, [company_info.fetch_sina_ipo]),
        "HK": None,
        "US": None,
    },
    "dividends": {
        "A": (company_info.fetch_em_dividends,
              [company_info.fetch_ths_dividends, company_info.fetch_cninfo_dividends]),
        "BJ": (company_info.fetch_em_dividends,
               [company_info.fetch_ths_dividends, company_info.fetch_cninfo_dividends]),
        "HK": (company_info.fetch_hk_dividends, []),
        "US": None,
    },
    "forecast": {
        "A": (company_info.fetch_em_forecast, [company_info.fetch_ths_forecast]),
        "BJ": (company_info.fetch_em_forecast, [company_info.fetch_ths_forecast]),
        "HK": (company_info.fetch_et_forecast, []),
        "US": None,
    },
    "holders": {
        "A": (company_info.fetch_sina_holders, []),
        "BJ": (company_info.fetch_sina_holders, []),
        "HK": None,
        "US": None,
    },
}

# 各 section 补充源的记录 join 键（用于把补充源的行对齐到主源行）
_JOIN_KEYS = {
    "dividends": "报告期",  # 东财 A 股分红报告期（YYYY-MM-DD）；同花顺同列名、巨潮为"报告时间"
    "forecast": "年度",     # 同花顺预测按年度并入东财一致预期行
}


def _normalize_report_period(text: Any) -> str:
    """报告期文本规范化：'2011年报'→'2011-12-31'、'2012中报'→'2012-06-30'、
    '2013一季报'→'2013-03-31'、'2014三季报'→'2014-09-30'（东财主源用 YYYY-MM-DD）。"""
    s = str(text or "").strip()
    mapping = {"年报": "-12-31", "中报": "-06-30", "一季报": "-03-31", "三季报": "-09-30"}
    for suffix, tail in mapping.items():
        if s.endswith(suffix):
            year = s[: -len(suffix)]
            if year.isdigit() and len(year) == 4:
                return year + tail
    return s


def _merge_dict(primary: dict, extra: dict) -> tuple[dict, list[str]]:
    """dict 字段并集补全：补充源里主源没有的 key 补进去。返回 (合并后, 补充的 key 列表)。"""
    added = [str(k) for k in extra if k not in primary and extra.get(k) is not None]
    merged = dict(primary)
    for k in added:
        merged[k] = extra[k]
    return merged, added


def _merge_records(primary: list[dict], extra: list[dict], join_key: str) -> tuple[list[dict], list[str]]:
    """list 行级补全：按 join_key 文本匹配主源行，把补充行中主源缺失的字段补进匹配行；
    匹配不上的补充行（如"不分配"记录）原样追加到列表末尾。返回 (合并后, 补充的字段列表)。"""
    if not extra:
        return primary, []
    added_fields: list[str] = []
    by_join: dict[str, dict] = {}
    for row in primary:
        key = str(row.get(join_key) or "").strip()
        if key:
            by_join.setdefault(key, row)
    merged = list(primary)
    appended: list[dict] = []
    for row in extra:
        key = str(row.get(join_key) or "").strip()
        target = by_join.get(key)
        if target is None:
            appended.append(dict(row))
            continue
        for k, v in row.items():
            if k not in target and v is not None:
                target[k] = v
                if k not in added_fields:
                    added_fields.append(k)
    merged.extend(appended)
    return merged, added_fields


def _merge_forecast(primary: dict, extra_rows: list[dict]) -> tuple[dict, list[str]]:
    """forecast 合并：主源=东财一致预期 1 行 dict；补充=同花顺年度分布 list。
    按"年度"键构建 '预测分布' 子对象（{年度: {机构数/min/均值/max/行业均值}}）并入主源。"""
    distribution: dict[str, dict] = {}
    for row in extra_rows:
        year = str(row.get("年度") or "").strip()
        if not year:
            continue
        distribution[year] = {k: v for k, v in row.items() if k != "年度" and v is not None}
    if not distribution:
        return primary, []
    merged = dict(primary)
    merged["预测分布"] = distribution
    return merged, ["预测分布"]


def _merge(section: str, primary_data: Any, extra_data: Any, source: str) -> tuple[Any, list[str]]:
    """按 section × 补充源形状合并：
    - dict 并集（profile 港股证券资料 / ipo 新浪 key-value）
    - list 按 join 键行级补全（dividends 同花顺/巨潮；报告期文本先规范化）
    - forecast：主源 dict + 同花顺 list → '预测分布' 子对象
    """
    if section == "forecast" and isinstance(primary_data, dict) and isinstance(extra_data, list):
        return _merge_forecast(primary_data, extra_data)
    if isinstance(primary_data, dict) and isinstance(extra_data, dict):
        return _merge_dict(primary_data, extra_data)
    if isinstance(primary_data, list) and isinstance(extra_data, list):
        if section == "dividends":
            join_key = "报告时间" if source == "cninfo" else "报告期"
            extra_rows = []
            for row in extra_data:
                row = dict(row)
                if join_key in row:
                    row[join_key] = _normalize_report_period(row[join_key])
                extra_rows.append(row)
            return _merge_records(primary_data, extra_rows, join_key)
        join_key = _JOIN_KEYS.get(section)
        if join_key:
            return _merge_records(primary_data, extra_data, join_key)
        return primary_data + extra_data, []
    return primary_data, []


def _unavailable(market: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": _HK_US_REASON if market == "HK" else _US_REASON,
    }


def _ensure_section(
    root: str,
    mc: MarketCode,
    section: str,
    force_refresh: bool,
) -> dict[str, Any]:
    """确保某 section 数据可用（缓存 30 天新鲜期 → 市场路由 → 主源 → 补充补全 → 写缓存）。"""
    code = f"{mc.code}.{mc.suffix}"
    cached = company_cache.read_section(root, code, section)
    if cached is not None and not force_refresh and company_cache.is_fresh(cached["meta"]):
        return {"ok": True, "section": section, "cached": True,
                "source": cached["meta"].get("source"),
                "data": cached["data"], "notes": cached["meta"].get("notes")}

    plan = _SECTION_PLAN[section].get(mc.market)
    if plan is None:
        return {"ok": True, "section": section, "available": False,
                "reason": _unavailable(mc.market)["reason"], "data": None, "notes": None}

    primary, supplements = plan
    result = primary(root, mc)
    if not result["ok"]:
        # 无失败回退：主源失败即结构化报错（可重试），不做第二来源顶替
        return {"ok": False, "section": section,
                "error": f"主源 {result['source']} 获取失败：{result['error']}"}
    data = result["data"]
    notes: list[str] = []

    # 补充源字段补全（仅主源成功且缺字段时调用；失败只记 notes，不影响主数据）
    for extra_fn in supplements:
        try:
            extra = extra_fn(root, mc)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"补充源调用异常：{exc}")
            continue
        if not extra["ok"]:
            notes.append(f"补充源 {extra['source']} 获取失败（{extra['error']}），已跳过")
            continue
        if not extra.get("data"):
            continue
        merged, added = _merge(section, data, extra["data"], extra["source"])
        if added:
            data = merged
            notes.append(f"已从 {extra['source']} 补全字段：{sorted(added)}")
        else:
            notes.append(f"{extra['source']} 无新增字段（主源已覆盖）")

    company_cache.write_section(
        root, code, section, market=mc.market, source=result["source"], data=data, notes=notes,
    )
    return {"ok": True, "section": section, "cached": False,
            "source": result["source"], "data": data, "notes": notes}


def get_company_profile(
    root: str,
    code: str,
    sections: list[str] | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """获取公司信息（概况/IPO/分红/盈利预测/股东）。

    返回 {ok, market, code, sections: {...}, notes}；每个 section：
    - 有数据：{data, source, cached, notes?}
    - 该市场无结构化来源（美股/港股 IPO 等）：{available: false, reason}
    美股一律提示用公告 MCP 查 SEC；30 天新鲜期 + force_refresh 强制刷新。
    """
    try:
        mc = parse_code(code)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    selected = list(VALID_SECTIONS) if sections is None else list(sections)
    if not selected:
        return {"ok": False, "error": f"sections 必须是 {list(VALID_SECTIONS)} 的非空子集"}
    unknown = [s for s in selected if s not in VALID_SECTIONS]
    if unknown:
        return {"ok": False, "error": f"未知 section {unknown}（支持 {list(VALID_SECTIONS)}）"}
    selected = list(dict.fromkeys(selected))

    full_code = f"{mc.code}.{mc.suffix}"
    out_sections: dict[str, Any] = {}
    notes: list[str] = []
    failed: list[str] = []
    for section in selected:
        result = _ensure_section(root, mc, section, force_refresh)
        if not result["ok"]:
            failed.append(section)
            out_sections[section] = {"ok": False, "error": result["error"]}
            continue
        if result.get("available") is False:
            out_sections[section] = {"available": False, "reason": result["reason"]}
            continue
        item: dict[str, Any] = {
            "data": result["data"],
            "source": result.get("source"),
            "cached": bool(result.get("cached")),
        }
        if result.get("notes"):
            item["notes"] = result["notes"]
            notes.extend(result["notes"])
        out_sections[section] = item

    response: dict[str, Any] = {
        "ok": not failed,
        "market": mc.market,
        "code": full_code,
        "sections": out_sections,
    }
    if notes:
        response["notes"] = notes
    if failed:
        response["failed_sections"] = failed
        response["error"] = f"section 获取失败：{','.join(failed)}"
    return response
