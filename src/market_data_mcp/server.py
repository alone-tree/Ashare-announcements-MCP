# -*- coding: utf-8 -*-
"""market_data MCP 服务器：三市场（A股/北交所/港股/美股）行情与基本面数据。

工具：
- get_quote: 日/周/月线行情（raw/hfq/qfq + 量额/股本/市值，超长自动导出）

代码强制市场后缀（600519.SH / 920002.BJ / 00700.HK / AAPL.US），程序按后缀路由市场。
数据根目录：MARKET_DATA_ROOT 环境变量（默认当前目录），缓存与自动导出均在根目录下。
"""

from __future__ import annotations

import os
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[assignment]

# FastMCP 严格参数模式：任何未声明参数显式报错（Extra inputs are not permitted）
try:
    from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
    from pydantic import ConfigDict

    ArgModelBase.model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
except Exception:  # 兼容 mcp 版本差异
    pass

from market_data_mcp.service import get_quote as get_quote_service


def _data_root() -> str:
    return os.environ.get("MARKET_DATA_ROOT") or os.getcwd()


def _wrap(fn):
    """把 service 函数包成工具；异常转为 ok=false 返回（service 已结构化，此处兜底）。"""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def create_server() -> Any:
    mcp = FastMCP("market-data")

    @mcp.tool()
    def get_quote(
        code: str,
        vars: list[str] | None = None,
        adjust: str = "raw",
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "daily",
        export_path: str | None = None,
    ) -> dict[str, Any]:
        """获取日/周/月线行情（A股/北交所/港股/美股）。

        code: 带市场后缀代码（600519.SH / 920002.BJ / 00700.HK / AAPL.US）。
        vars: 返回字段列表（date 恒保留），可选 open/high/low/close/volume/amount/turnover/
              outstanding_share/total_market_cap/float_market_cap；不传默认 close。
        adjust: raw=除权价、hfq=后复权、qfq=前复权（本地现算）。
        start_date/end_date: YYYY-MM-DD；空 = 最近 10 个交易日 / 当天。
        period: daily/weekly/monthly（周/月由日线本地聚合）。
        export_path: 空 = 直接返回数据（超过 200 行自动导出到缓存目录并返回路径）；
                     指定 = 导出 CSV 并返回元信息。
        返回 rows 为数据本体；notes 说明降级/聚合/估算（市值为股本×收盘估算值；
        美股 amount 来自 iFinD；后复权美股为分红再投口径）。
        """
        return _wrap(get_quote_service)(
            _data_root(), code, vars=vars, adjust=adjust,
            start_date=start_date, end_date=end_date, period=period,
            export_path=export_path,
        )

    return mcp


def main() -> None:
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()
