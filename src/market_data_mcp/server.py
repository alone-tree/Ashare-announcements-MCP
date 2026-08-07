# -*- coding: utf-8 -*-
"""market_data MCP 服务器：三市场（A股/港股/美股）行情与基本面数据。

工具：
- get_quote:          日线行情（前复权/后复权/不复权 + 成交量/额/流通股本）
- get_financial_statements: 原始财务报表（三表，多报告期 × 报表范围可选）
- get_financial_ratios:     财务衍生指标（ROE/毛利率等，多报告期）
- get_company_profile:      公司基本信息（概况/分红/盈利预测，sections 可选）

代码自动路由：6位数字=A股、5位数字=港股、字母=美股；可加 A:/HK:/US: 前缀强制。
"""

from __future__ import annotations

import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[assignment]

from market_data_mcp.service import get_company_profile, get_financial_ratios, get_financial_statements, get_quote


def _wrap(fn):
    """把 service 函数包成工具；ValueError 转为 ok=false 返回。"""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def create_server() -> Any:
    mcp = FastMCP("market-data")

    @mcp.tool()
    def get_quote(
        code: str,
        start: str,
        end: str,
        adjust: str = "qfq",
    ) -> dict[str, Any]:
        """获取日线行情（A股/港股/美股）。

        code: 6位数字=A股、5位数字=港股、字母=美股；可用 A:/HK:/US: 前缀强制市场。
        adjust: qfq=前复权、hfq=后复权、none=不复权（传空字符串）。
        返回每日 开盘/收盘/最高/最低/成交量/成交额/换手率/流通股本，及数据源。
        """
        return _wrap(get_quote)(code=code, start=start, end=end, adjust=adjust)

    @mcp.tool()
    def get_financial_statements(
        code: str,
        periods: list[str] | None = None,
        statements: list[str] | None = None,
    ) -> dict[str, Any]:
        """获取原始财务报表（利润表/资产负债表/现金流量表）。

        code: 同 get_quote 的市场路由。
        periods: 报告期年份列表（如 ["2025","2024"]），匹配该年份所有季度报告期；不传=全部。
        statements: 报表范围 ["income","balance","cash_flow"]；不传=三张表全部。
        返回按报告期组织的原始报表数据（字段为东财原始列名）。
        """
        return _wrap(get_financial_statements)(code=code, periods=periods, statements=statements)

    @mcp.tool()
    def get_financial_ratios(
        code: str,
        periods: list[str] | None = None,
    ) -> dict[str, Any]:
        """获取财务衍生指标（ROE/毛利率/负债率等，东财原始指标）。

        code: 同 get_quote 的市场路由。
        periods: 报告期年份列表；不传=全部。
        A股按报告期多期；港股仅最新；美股按年报多期。
        """
        return _wrap(get_financial_ratios)(code=code, periods=periods)

    @mcp.tool()
    def get_company_profile(
        code: str,
        sections: list[str] | None = None,
    ) -> dict[str, Any]:
        """获取公司基本信息：公司概况 / 分红历史 / 盈利预测。

        code: 同 get_quote 的市场路由。
        sections: ["profile","dividends","forecast"]；不传=全部。
        港股/美股缺失的类别（如美股概况/分红）返回 note 提示从公告获取。
        """
        return _wrap(get_company_profile)(code=code, sections=sections)

    return mcp


def main() -> None:
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()
