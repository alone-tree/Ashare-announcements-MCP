# -*- coding: utf-8 -*-
"""历史行情周/月线聚合：先取日K，再按标准OHLCV口径本地聚合。

口径等价 market_data_mcp/providers/_common.py 的 resample_ohlcv：
- open=周期首日、high=极值、low=极值、close=周期末日；
- volume/amount=周期求和；其余列取周期末值；
- weekly 用 W-FRI、monthly 用 ME（周期标签即周五/月末）。

项目铁律：ifind_excel_tool 与 market-data 零 import 依赖，此处自带等价实现，
不 import market_data_mcp。
"""
from __future__ import annotations

import pandas as pd

RULE = {"weekly": "W-FRI", "monthly": "ME"}


def resample_ohlcv(records: list[dict], period: str, field_map: dict[str, str]) -> list[dict]:
    """把日线记录聚合为周线/月线。

    records: 日线记录列表，每条含 date 及各原始中文字段。
    period:  daily/weekly/monthly；daily 或空列表原样返回。
    field_map: 标准名到记录字段名的映射，需含 open/high/low/close/volume/amount。
    返回记录保留 date 与 field_map 涉及的字段；其余字段（如 code、unit 留痕）取周期末值。
    """
    if period == "daily" or not records:
        return records
    if period not in RULE:
        raise ValueError(f"不支持的周期 {period}（支持 daily/weekly/monthly）")

    canonical = ("open", "high", "low", "close", "volume", "amount")
    for key in canonical:
        if key not in field_map:
            raise ValueError(f"字段映射缺少 {key}：{field_map}")

    name_to_std = {v: k for k, v in field_map.items()}
    work = pd.DataFrame([dict(r) for r in records])
    work = work.rename(columns=name_to_std)
    work["date"] = pd.to_datetime(work["date"])
    work = work.set_index("date").sort_index()

    agg: dict[str, str] = {
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "amount": "sum",
    }
    # 其余列（含 code、__unit 留痕等）取周期末值，与 _common 一致。
    for col in work.columns:
        if col not in agg:
            agg[col] = "last"

    out = work.resample(RULE[period]).agg(agg).dropna(subset=["close"])
    out["date"] = out.index.strftime("%Y-%m-%d")
    out = out.reset_index(drop=True)
    # 还原中文字段名，保持返回结构与日线一致。
    out = out.rename(columns={std: name for std, name in field_map.items()})
    return out.to_dict("records")
