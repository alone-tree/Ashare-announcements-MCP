# -*- coding: utf-8 -*-
"""供确定性批处理脚本调用的 market-data JSON CLI。

从 stdin 读取一个 JSON 请求，stdout 只输出一个 JSON 响应。
tool 支持：get_quote_batch / get_financial_data_batch / get_market_data_help /
get_company_profile_batch / get_quote_chart_batch。
顶层请求字段是 `tool`（与公告 MCP CLI 一致），响应字段也是 `tool`。
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

from market_data_mcp import chart_service, company_service, financial_service, market_help, service


def _data_root() -> str:
    return os.environ.get("MARKET_DATA_ROOT") or os.getcwd()


def _status(items: list[dict[str, Any]]) -> str:
    """按docs/market-data架构设计.md §1.6汇总完成度，保留子结果的部分成功与过期状态。"""
    succeeded = sum(bool(item.get("ok")) for item in items)
    if succeeded == len(items) and all(
        item.get("status", "success") == "success" and not item.get("stale") for item in items
    ):
        return "success"
    return "partial_success" if succeeded else "failed"


def _batch_response(tool: str, items: list[dict[str, Any]], result_key: str) -> dict[str, Any]:
    succeeded = sum(bool(item.get("ok")) for item in items)
    return {
        "ok": succeeded == len(items),
        "tool": tool,
        "status": _status(items),
        "requested": len(items),
        "succeeded": succeeded,
        "failed": len(items) - succeeded,
        result_key: items,
    }


def get_quote_batch(request: dict[str, Any]) -> dict[str, Any]:
    codes = request.get("codes")
    if not isinstance(codes, list) or not codes:
        raise ValueError("codes 必须是非空数组")

    common = {k: request.get(k) for k in
              ("vars", "adjust", "start_date", "end_date", "period", "export_path")}
    items = []
    for value in codes:
        code = str(value)
        try:
            result = service.get_quote(_data_root(), code, **{k: v for k, v in common.items() if v is not None})
            items.append({"code": code, **result})
        except Exception as exc:  # noqa: BLE001 —— 单家公司失败不阻断批次
            items.append({"code": code, "ok": False, "error": str(exc)})
    return _batch_response("get_quote_batch", items, "results")


def get_financial_data_batch(request: dict[str, Any]) -> dict[str, Any]:
    codes = request.get("codes")
    if not isinstance(codes, list) or not codes:
        raise ValueError("codes 必须是非空数组")
    if request.get("amount_basis") is None:
        raise ValueError("amount_basis 必须明确为 cumulative 或 single")

    common = {
        key: request.get(key)
        for key in (
            "amount_basis",
            "statements",
            "periods",
            "include_versions",
            "force_refresh",
            "export_path",
            "items",
        )
    }
    items = []
    for value in codes:
        code = str(value)
        try:
            parameters = {key: value for key, value in common.items() if value is not None}
            if len(codes) > 1 and parameters.get("export_path"):
                target = Path(parameters["export_path"])
                parameters["export_path"] = str(target.with_name(f"{target.stem}_{code}{target.suffix}"))
            result = financial_service.get_financial_data(
                _data_root(),
                code,
                **parameters,
            )
            items.append({"code": code, **result})
        except Exception as exc:  # noqa: BLE001 —— 单家公司失败不阻断批次
            items.append({"code": code, "ok": False, "error": str(exc)})
    return _batch_response("get_financial_data_batch", items, "results")


def get_market_data_help(request: dict[str, Any]) -> dict[str, Any]:
    arguments = request.get("arguments") or {}
    if not isinstance(arguments, dict) or set(arguments) - {"tool", "market", "code", "topic"}:
        raise ValueError("帮助工具arguments仅接受tool/market/code/topic")
    return {**market_help.get_market_data_help(_data_root(), **arguments), "tool": "get_market_data_help"}


def get_company_profile_batch(request: dict[str, Any]) -> dict[str, Any]:
    codes = request.get("codes")
    if not isinstance(codes, list) or not codes:
        raise ValueError("codes 必须是非空数组")
    items = []
    for value in codes:
        code = str(value)
        try:
            result = company_service.get_company_profile(
                _data_root(), code,
                sections=request.get("sections"),
                force_refresh=bool(request.get("force_refresh")),
                periods=request.get("periods"), years=request.get("years"),
                as_of_date=request.get("as_of_date"),
            )
            items.append({"code": code, **result})
        except Exception as exc:  # noqa: BLE001 —— 单家公司失败不阻断批次
            items.append({"code": code, "ok": False, "error": str(exc)})
    return _batch_response("get_company_profile_batch", items, "results")


def get_quote_chart_batch(request: dict[str, Any]) -> dict[str, Any]:
    codes = request.get("codes")
    if not isinstance(codes, list) or not codes:
        raise ValueError("codes 必须是非空数组")

    common = {k: request.get(k) for k in
              ("adjust", "start_date", "end_date", "period", "log_scale", "field",
               "events", "keypoints", "drawdown_threshold")}
    items = []
    for value in codes:
        code = str(value)
        try:
            result = chart_service.get_quote_chart(
                _data_root(), code, **{k: v for k, v in common.items() if v is not None}
            )
            items.append({"code": code, **result})
        except Exception as exc:  # noqa: BLE001 —— 单家公司失败不阻断批次
            items.append({"code": code, "ok": False, "error": str(exc)})
    return _batch_response("get_quote_chart_batch", items, "results")


ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "get_quote_batch": get_quote_batch,
    "get_financial_data_batch": get_financial_data_batch,
    "get_market_data_help": get_market_data_help,
    "get_company_profile_batch": get_company_profile_batch,
    "get_quote_chart_batch": get_quote_chart_batch,
}


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    tool = str(request.get("tool") or "")
    handler = ACTIONS.get(tool)
    if handler is None:
        raise ValueError(f"未知 tool：{tool or '<empty>'}")
    parameters = {
        "get_quote_batch": {"tool", "codes", "vars", "adjust", "start_date", "end_date", "period", "export_path"},
        "get_quote_chart_batch": {"tool", "codes", "adjust", "start_date", "end_date", "period", "log_scale", "field", "events", "keypoints", "drawdown_threshold"},
        "get_financial_data_batch": {"tool", "codes", "amount_basis", "statements", "periods", "items", "include_versions", "force_refresh", "export_path"},
        "get_market_data_help": {"tool", "arguments"},
        "get_company_profile_batch": {"tool", "codes", "sections", "periods", "years", "as_of_date", "force_refresh"},
    }
    if tool in parameters and set(request) - parameters[tool]:
        raise ValueError(f"未知参数：{sorted(set(request) - parameters[tool])}")
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
