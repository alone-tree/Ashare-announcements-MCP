# -*- coding: utf-8 -*-
"""运行日志（审计）：每次对上游的请求记一条日志。

落点：{root}/logs/requests.jsonl（JSON Lines，一行一条）。
字段：ts/source/market/code/api/fields/adjust/start/end/ok/elapsed/error。
日志是 append-only 审计，**不参与任何决策逻辑**，评估数据源可靠性用。
审计失败（磁盘满等）不影响主流程。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any


def log_request(
    root: str,
    *,
    source: str,
    market: str,
    code: str,
    api: str,
    fields: str | None = None,
    adjust: str | None = None,
    start: str | None = None,
    end: str | None = None,
    ok: bool,
    elapsed: float,
    error: str | None = None,
) -> None:
    """追加一条上游请求记录。root 为数据根目录（含 logs/ 子目录）。"""
    try:
        path = os.path.join(root, "logs", "requests.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": source,
            "market": market,
            "code": code,
            "api": api,
            "fields": fields,
            "adjust": adjust,
            "start": start,
            "end": end,
            "ok": ok,
            "elapsed": round(elapsed, 3),
            "error": error,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
