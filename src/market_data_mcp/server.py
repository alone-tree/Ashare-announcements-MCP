# -*- coding: utf-8 -*-
"""market_data MCP 服务器：三市场（A股/北交所/港股/美股）行情与基本面数据。

工具：
- get_quote: 日/周/月线行情（raw/hfq/qfq + 量额/股本/市值，超长自动导出）
- get_financial_statements: 三市场三表（累计/单期、版本、30 天缓存、超长自动导出）
- get_data_catalog: 纯本地查询公司三表缓存支持的科目

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

from market_data_mcp import company_service
from market_data_mcp.service import get_data_catalog as get_data_catalog_service
from market_data_mcp.service import get_financial_statements as get_financial_statements_service
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

    @mcp.tool()
    def get_financial_statements(
        code: str,
        amount_basis: str,
        statements: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        include_versions: bool = False,
        force_refresh: bool = False,
        export_path: str | None = None,
        items: list[str] | None = None,
        report_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """获取三大财务报表原始科目（A股/北交所/港股/美股）。

        code: 带市场后缀代码（600519.SH / 920002.BJ / 00700.HK / AAPL.US）。
        amount_basis: 必填；cumulative=累计报原值，single=用最新累计版本现算当期金额。
            资产负债表始终为时点值。single 不返回 EPS、每股股息、加权平均股数等
            非加总科目；这些科目只能从 cumulative 获取。额外加工由调用方自行处理，
            本工具不提供支持。
        statements: 可选 balance/income/cash_flow 子集；不传返回三表。上游刷新始终同时
            获取三表，任一失败整批不更新。
        start_date/end_date: 按原始报告截止日筛选，格式 YYYY-MM-DD，含边界；不传为全部历史。
        include_versions: false=每个报告期仅最新版本；true=累计口径返回全部历史版本。
            single 始终只使用最新累计版本，不生成历史单期版本。
        force_refresh: true=忽略固定 30 天新鲜期，强制联网刷新。
        export_path: 指定则导出 CSV；未指定且超过 200 行时自动导出并返回路径。
        items: 可选中文科目名称列表。精确匹配优先；否则按字符顺序匹配关键词。
            单一候选直接返回并提示，多候选计入 failed_items 并返回各候选最近金额；
            不存在的科目报失败，工具不计算毛利、毛利率等衍生指标。
        report_types: 可选 annual/semiannual/q1/q3 列表；可组合。不传返回全部报告节点。
            与 amount_basis 组合时，annual+single 表示第四季度单季，semiannual+single
            表示第二季度单季，q3+single 表示第三季度单季。
        返回 rows 包含中文优先的科目名、金额、来源、报告级元信息和版本信息；有可靠
        中文名时不暴露英文代码，未映射时保留原名。不返回同比/环比比例，不自行修正上游值。
        """
        return _wrap(get_financial_statements_service)(
            _data_root(),
            code,
            amount_basis=amount_basis,
            statements=statements,
            start_date=start_date,
            end_date=end_date,
            include_versions=include_versions,
            force_refresh=force_refresh,
            export_path=export_path,
            items=items,
            report_types=report_types,
        )

    @mcp.tool()
    def get_data_catalog(
        code: str,
        statements: list[str] | None = None,
    ) -> dict[str, Any]:
        """查询公司财务三表缓存中实际可请求的科目名称（纯本地、轻量、不联网）。

        code: 带市场后缀代码。
        statements: balance/income/cash_flow 子集；不传返回三表科目。
        仅返回该公司所有缓存报告期和历史版本中至少有一个非空金额的科目，附最早、
        最晚有效报告日。A股有可靠中文映射时只返回中文；未映射时保留原名。
        如果尚无完整缓存，提示先调用 get_financial_statements。
        """
        return _wrap(get_data_catalog_service)(
            _data_root(), code, statements=statements,
        )

    @mcp.tool()
    def get_company_profile(
        code: str,
        sections: list[str] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """获取公司信息（A股/北交所/港股；美股无结构化数据，返回提示用公告 MCP 查 SEC）。

        code: 带市场后缀代码（600519.SH / 920002.BJ / 00700.HK）。
        sections: 可选 profile/ipo/dividends/forecast/holders 子集；不传返回全部。
            profile=公司概况、ipo=IPO资料、dividends=分红历史、forecast=盈利预测、
            holders=股东（历史多期序列）。
        force_refresh: true=忽略 30 天新鲜期，强制联网刷新（默认缓存 30 天内直接返回）。

        返回 sections 字典：有数据的 section 为 {data, source, cached}；
        该市场无结构化来源的 section 为 {available: false, reason}（不是错误）。
        数据保留上游字段名原样；多源合并为主源优先、缺字段从补充源补全
        （无失败回退，主源失败即报错可重试）。
        """
        return _wrap(company_service.get_company_profile)(
            _data_root(), code, sections=sections, force_refresh=force_refresh,
        )

    return mcp


def main() -> None:
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()
