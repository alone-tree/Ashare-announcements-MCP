"""随代码保存的iFinD原始汇率资源；正常缓存流程见架构§2.7。"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

CODES = ("HKDCNY.FX", "USDHKD.FX", "USDCNY.IN")
HISTORY_PATH = Path(__file__).resolve().parent / "data" / "fx_history.csv"
HISTORY_START = "1995-01-01"
HISTORY_END = "2026-09-30"
LIVE_START = "2026-10-01"


@lru_cache(maxsize=1)
def read_history() -> dict[str, dict[str, float | None]]:
    """读取唯一原始CSV；空单元格保留为None，写缓存由原调度层执行。"""
    with HISTORY_PATH.open(encoding="utf-8", newline="") as stream:
        return {row["date"]: {code: float(row[code]) if row[code] else None
                              for code in CODES}
                for row in csv.DictReader(stream)}
