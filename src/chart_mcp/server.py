# -*- coding: utf-8 -*-
"""chart MCP 服务器：行情绘图（三 MCP 一体的第三块）。

工具：
- get_quote_chart: K线（蜡烛+成交量+MA5/10/20/60）/ 折线（单字段）行情图 PNG

代码强制市场后缀（300308.SZ / 00700.HK / AAPL.US），数据链路复用
market-data MCP 的 get_quote()（同仓库同 venv，import 直接调用，不复制取数代码）。
数据根目录：MARKET_DATA_ROOT 环境变量（默认当前目录），PNG 落盘 {root}/cache/_charts/。
"""

from __future__ import annotations

import os
import sys
from typing import Any

# 支持直接执行导出目录中的 server.py（与公告/market-data MCP 同款；不依赖 cwd）
if __package__ in (None, ""):
    sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

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

from chart_mcp.service import get_quote_chart as get_quote_chart_service


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
    mcp = FastMCP("chart")

    @mcp.tool()
    def get_quote_chart(
        code: str,
        adjust: str = "raw",
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "daily",
        log_scale: bool = False,
        field: str | None = None,
    ) -> dict[str, Any]:
        """绘制行情图（K线或折线），输出一张 PNG，返回文件路径（A股/北交所/港股/美股）。

        code: 带市场后缀代码（300308.SZ / 00700.HK / AAPL.US）。
        adjust: raw=除权价、hfq=后复权、qfq=前复权。
        start_date/end_date: YYYY-MM-DD；都不传 = 全部缓存数据（起点不限）；
            start_date 传了而 end_date 留空 = 该日起至今；只传 end_date = 起点不限、
            只取 ≤end_date 的早期数据。
        period: daily/weekly/monthly（周/月由行情层按日线聚合，均线按当前周期计算：
            周图 MA5 = 5 周均线）。
        log_scale: 对数坐标；对 K线/折线/成交量副图都生效，数据含负值或 0 自动退回普通坐标。
        field: 不传 = K线（蜡烛图 + 成交量副图 + MA5/10/20/60 均线）；传 open/high/low/close
            任一 = 单字段走势折线（不带副图、不带均线）。

        返回 {ok, path, code, chart_type, start, end, period, adjust, rows}；
        path 为 PNG 文件路径，图片内容需自行读取。失败 {ok:false, error}。
        """
        return _wrap(get_quote_chart_service)(
            _data_root(), code, adjust=adjust, start_date=start_date,
            end_date=end_date, period=period, log_scale=log_scale, field=field,
        )

    return mcp


def main() -> None:
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()
