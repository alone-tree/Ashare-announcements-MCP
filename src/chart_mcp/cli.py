# -*- coding: utf-8 -*-
"""供确定性批处理脚本调用的 chart JSON CLI（与 market-data CLI 同模式）。

从 stdin 读取一个 JSON 请求，stdout 只输出一个 JSON 响应。
tool 支持：get_quote_chart_batch。
顶层请求字段是 `tool`（与公告/market-data MCP CLI 一致），响应字段也是 `tool`。
数据根目录：MARKET_DATA_ROOT 环境变量（默认当前目录）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chart_mcp.service import get_quote_chart


def _data_root() -> str:
    return os.environ.get("MARKET_DATA_ROOT") or os.getcwd()


def _status(items: list[dict[str, Any]]) -> str:
    succeeded = sum(bool(item.get("ok")) for item in items)
    if succeeded == len(items):
        return "success"
    return "partial_success" if succeeded else "failed"


def _batch_response(tool: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    succeeded = sum(bool(item.get("ok")) for item in items)
    return {
        "ok": succeeded == len(items),
        "tool": tool,
        "status": _status(items),
        "requested": len(items),
        "succeeded": succeeded,
        "failed": len(items) - succeeded,
        "results": items,
    }


def get_quote_chart_batch(request: dict[str, Any]) -> dict[str, Any]:
    codes = request.get("codes")
    if not isinstance(codes, list) or not codes:
        raise ValueError("codes 必须是非空数组")

    common = {k: request.get(k) for k in
              ("adjust", "start_date", "end_date", "period", "log_scale", "field")}
    items = []
    for value in codes:
        code = str(value)
        try:
            result = get_quote_chart(
                _data_root(), code, **{k: v for k, v in common.items() if v is not None}
            )
            items.append({"code": code, **result})
        except Exception as exc:  # noqa: BLE001 —— 单家公司失败不阻断批次
            items.append({"code": code, "ok": False, "error": str(exc)})
    return _batch_response("get_quote_chart_batch", items)


ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "get_quote_chart_batch": get_quote_chart_batch,
}


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    tool = str(request.get("tool") or "")
    handler = ACTIONS.get(tool)
    if handler is None:
        raise ValueError(f"未知 tool：{tool or '<empty>'}")
    return handler(request)


def main() -> None:
    raw = sys.stdin.read()
    request = json.loads(raw)
    try:
        response = dispatch(request)
        response["ok"] = bool(response.get("ok", True))
    except Exception as exc:  # noqa: BLE001
        response = {"ok": False, "tool": str(request.get("tool") or ""), "error": str(exc)}
    sys.stdout.write(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
