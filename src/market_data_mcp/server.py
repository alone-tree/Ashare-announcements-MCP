# -*- coding: utf-8 -*-
"""market_data MCP 服务器：三市场（A股/北交所/港股/美股）行情、基本面与行情绘图。

工具：
- get_quote: 日/周/月线行情（raw/hfq/qfq + 量额/股本/市值，超长自动导出）
- get_financial_data: 财报、营收结构及本地计算指标
- get_market_data_help: 纯本地能力及缓存帮助
- get_company_profile: 公司概况/IPO/分红/盈利预测/股东
- get_quote_chart: 行情绘图（K线/折线 PNG，事件标注/高低点；引擎 chart_service.py，
  原 market-data-chart MCP，2026-10-19 并入）

代码强制市场后缀（600519.SH / 920002.BJ / 00700.HK / AAPL.US），程序按后缀路由市场。
数据根目录：MARKET_DATA_ROOT 环境变量（默认当前目录），缓存与自动导出均在根目录下。
"""

from __future__ import annotations

import os
import sys
import json
from typing import Annotated, Any
from pydantic import Field, StrictBool, StrictInt

# 支持直接执行导出目录中的 server.py（与公告 MCP 同款；不依赖 cwd）
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

from market_data_mcp import chart_service, company_service
from market_data_mcp.financial_service import get_financial_data as get_financial_data_service
from market_data_mcp.market_help import get_market_data_help as get_market_data_help_service
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


def _render_company_markdown(result: dict) -> dict:
    """公司信息全字段成表，元信息和按类型返回的参数说明原样保留。"""
    if "data" not in result:
        return result
    data = result["data"]

    def cell(value):
        if value is None:
            return ""
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        return text.replace("&", "&amp;").replace("<", "&lt;").replace("|", "&#124;").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")

    if isinstance(data, dict):
        lines = ["| 科目 | 值 |", "|---|---|"]
        lines.extend(f"| {cell(key)} | {cell(value)} |" for key, value in data.items())
    elif isinstance(data, list) and data and all(isinstance(row, dict) for row in data):
        columns = list(dict.fromkeys(key for row in data for key in row))
        labels = {"year": "年度", "as_of_date": "预测取数基准日", "report_date": "股东名单报告截止日", "rank": "排名"}
        if result.get("information_type") == "forecast":
            labels["year"] = "预测业绩所属年度"
        elif result.get("information_type") == "dividends":
            labels["year"] = "分红统计年度"
        lines = ["| " + " | ".join(cell(labels.get(key, key)) for key in columns) + " |",
                 "|" + "|".join("---" for _ in columns) + "|"]
        lines.extend("| " + " | ".join(cell(row.get(key)) for key in columns) + " |" for row in data)
    elif data is None or data == []:
        lines = ["未接入此类数据" if result.get("available") is False else "无可用记录"]
    else:
        lines = ["| 数据 |", "|---|", f"| {cell(data)} |"]
    return {**{key: value for key, value in result.items() if key != "data"}, "markdown": "\n".join(lines)}


_FINANCIAL_TITLES = {"income": "利润表", "balance": "资产负债表", "cash_flow": "现金流量表", "meta": "报表信息"}
_FINANCIAL_META_ROWS = [
    ("公告日", "NOTICE_DATE"),
    ("东财更新日", "UPDATE_DATE"),
    ("货币", "CURRENCY"),
    ("审计意见", "OPINION_TYPE"),
    ("境外审计意见", "OSOPINION_TYPE"),
    ("内控审计意见", "INTERNAL_CONTROL_OPINION"),
    ("审计单位", "AUDITOR"),
]


def _fmt_financial_amount(value):
    """金额统一保留 2 位小数展示；空值渲染为空单元格。"""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return f"{round(value, 2):.2f}"
    return str(value)


def _fmt_financial_meta(value):
    """元信息文本展示：去除午夜时间后缀（缓存保留上游原值）。"""
    if value is None:
        return ""
    text = str(value)
    return text[:-len(" 00:00:00")] if text.endswith(" 00:00:00") else text


def _render_segments_markdown(segments: list[dict]) -> str:
    """依据docs/行为-财报工具.md §6.1，按数据形态展示实际返回列。"""
    concentration_dimensions = {"income by customer", "purchase by supplier"}
    tables = [
        ("主营构成", [row for row in segments if row.get("dimension") not in concentration_dimensions],
         [("report_date", "报告期"), ("dimension", "维度"), ("rank", "排名"), ("name", "名称"),
          ("income", "收入"), ("income_share", "营收占比"), ("gross_profit", "毛利"), ("gross_margin", "毛利率")]),
        ("客户/供应商集中度", [row for row in segments if row.get("dimension") in concentration_dimensions],
         [("report_date", "报告期"), ("dimension", "维度"), ("rank", "排名/汇总"), ("name", "名称"), ("ratio", "占比")]),
    ]
    lines = ["## 营收结构（累计口径）"]
    for title, records, fields in tables:
        if not records:
            continue
        columns = [(key, label) for key, label in fields if any(key in row for row in records)]
        lines.extend(["", f"### {title}", "", "| " + " | ".join(label for _, label in columns) + " |",
                      "|" + "|".join("---" for _ in columns) + "|"])
        for row in records:
            cells = []
            for key, _ in columns:
                value = row.get(key)
                if key == "rank" and value == "top5":
                    text = "前5大合计"
                elif key in ("income_share", "gross_margin", "ratio") and isinstance(value, (int, float)):
                    text = f"{value:.2%}"
                elif key in ("income", "gross_profit"):
                    text = _fmt_financial_amount(value)
                else:
                    text = "" if value is None else str(value)
                cells.append(text)
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _render_financial_markdown(result: dict) -> dict:
    """把财报rows渲染为「变量 × 报告期」markdown表。

    JSON 信封保留 ok/status/failed_items/notes 等元信息，数据本体进入 markdown 字段；
    rows 不再返回。include_versions=true 渲染版本审计长表。导出场景（无 rows）原样透传。
    报告期元信息独立成块；statements 含 meta 时不再重复。
    列名=上游原始报告截止日，不做任何推断（美/港股财年截止日灵活）。
    """
    rows = result.get("rows")
    if rows is None:
        return result
    include_versions = bool(result.get("include_versions"))
    blocks: list[str] = []
    for statement in result.get("statements") or []:
        srows = [row for row in rows if row.get("statement") == statement]
        if not srows:
            continue
        value_basis = "point_in_time" if statement == "balance" else "metadata" if statement == "meta" else result.get("amount_basis")
        title = _FINANCIAL_TITLES.get(statement, statement)
        if include_versions:
            md = [
                f"## {title}（value_basis={value_basis}，版本审计）",
                "",
                "| 报告期 | 科目 | 单位 | 数值 | version_id | is_latest | version_count |",
                "|---|---|---|---:|---|---|---:|",
            ]
            for row in srows:
                value = row.get("amount")
                cell = f"{value * 100:.2f}%" if row.get("unit") == "ratio" and isinstance(value, (int, float)) else _fmt_financial_amount(value)
                md.append("| {} | {} | {} | {} | {} | {} | {} |".format(
                    row.get("report_date"), row.get("item_name"), row.get("unit") or "",
                    cell,
                    row.get("version_id") or "", row.get("is_latest"), row.get("version_count"),
                ))
        else:
            dates = sorted({row["report_date"] for row in srows})
            md = [
                f"## {title}（value_basis={value_basis}）",
                "",
                "| 科目 | 单位 | " + " | ".join(dates) + " |",
                "|---|---" + "|---:" * len(dates) + "|",
            ]
            items: dict[tuple[str, str], dict[str, str]] = {}
            for row in srows:
                report_date = row["report_date"]
                value = row.get("amount")
                cell = f"{value * 100:.2f}%" if row.get("unit") == "ratio" and isinstance(value, (int, float)) else _fmt_financial_amount(value)
                items.setdefault((row.get("item_name"), row.get("unit") or ""), {})[report_date] = cell
            for (name, unit), cells in items.items():
                md.append("| {} | {} | {} |".format(name, unit, " | ".join(cells.get(d, "") for d in dates)))
        blocks.append("\n".join(md))
    segments = result.pop("segments", [])
    if segments:
        blocks.append(_render_segments_markdown(segments))
    if "meta" not in (result.get("statements") or []):
        meta_by_date: dict[str, dict] = {}
        for row in rows:
            report_date = row.get("report_date")
            if report_date and report_date not in meta_by_date:
                meta_by_date[report_date] = row.get("report_metadata") or {}
        dates = sorted(meta_by_date)
        if dates and any(meta_by_date[d].get(key) for d in dates for _, key in _FINANCIAL_META_ROWS):
            md = [
                "## 报告期元信息",
                "",
                "| 项目 | " + " | ".join(dates) + " |",
                "|---" + "|---" * len(dates) + "|",
            ]
            for label, key in _FINANCIAL_META_ROWS:
                md.append("| {} | {} |".format(
                    label,
                    " | ".join(_fmt_financial_meta(meta_by_date[d].get(key)) for d in dates),
                ))
            blocks.append("\n".join(md))
    result.pop("rows", None)
    if blocks:
        result["markdown"] = "\n\n".join(blocks)
    return result


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
        """获取日/周/月线行情（A股/北交所/港股/美股及汇率）。

        code: 股票带市场后缀（600519.SH / 920002.BJ / 00700.HK / AAPL.US）；
              汇率支持USDCNY.IN、HKDCNY.FX、USDHKD.FX。
              汇率无论传入何种vars和adjust，均仅返回close，有效adjust=raw；
              汇率同样使用字段缓存；未覆盖时，iFinD取数层从随代码CSV读取截至2026-09-30的
              历史原始数据，之后真实请求iFinD；早期空值也正常缓存，不反复补拉。
        vars: 返回字段列表（date 恒保留），可选 open/high/low/close/volume/amount/turnover/
              outstanding_share/total_shares/total_market_cap/float_market_cap；不传默认 close。
        adjust: raw=除权价、hfq=后复权、qfq=前复权（本地现算）。
        start_date/end_date: YYYY-MM-DD；空 = 最近 14 个自然日 / 当天。
            start_date 传 "all"：起点不约束——end 留空 = 返回全部数据；end 指定 = 只取 ≤end 的早期数据。
        period: daily/weekly/monthly（周/月由日线本地聚合）。
        export_path: 空 = 直接返回数据（超过 200 行自动导出到缓存目录并返回路径）；
                     指定 = 导出 CSV 并返回元信息。
        返回 rows 为数据本体；notes 说明降级/聚合/估算（A/B/北交所总市值取 iFinD 直取，
        港美股总市值与各市场流通市值为股本×收盘估算值；美股 amount 来自 iFinD；
        后复权美股为分红再投口径）。
        """
        return _wrap(get_quote_service)(
            _data_root(), code, vars=vars, adjust=adjust,
            start_date=start_date, end_date=end_date, period=period,
            export_path=export_path,
        )

    @mcp.tool()
    def get_financial_data(
        code: str,
        amount_basis: str,
        statements: list[str] | None = None,
        periods: list[str] | None = None,
        include_versions: bool = False,
        force_refresh: bool = False,
        export_path: str | None = None,
        items: list[str] | None = None,
        top_n: Annotated[StrictInt, Field(ge=1, le=99)] = 5,
    ) -> dict[str, Any]:
        """获取财报常用科目、营收结构及派生指标；详细口径查get_market_data_help。

        amount_basis必填：cumulative或single。periods省略为最近5个已披露报告期。
        statements支持balance/income/cash_flow/segments/meta。items省略返回常用清单，
        ["ALL_ITEMS"]返回全部原始科目；主营item为income by product/industry/region。
        top_n为主营排名上限，默认5，可取1—99；客户/供应商集中度仍为前五及合计。
        计算依赖自动补齐，single下营收结构仍为累计。force_refresh重查请求范围。
        export_path指定CSV；超过200行自动导出。include_versions保留已观察原始版本。
        """
        return _render_financial_markdown(_wrap(get_financial_data_service)(
            _data_root(),
            code,
            amount_basis=amount_basis,
            statements=statements,
            periods=periods,
            include_versions=include_versions,
            force_refresh=force_refresh,
            export_path=export_path,
            items=items,
            top_n=top_n,
        ))

    @mcp.tool()
    def get_market_data_help(
        tool: str | None = None,
        market: str | None = None,
        code: str | None = None,
        topic: str | None = None,
    ) -> dict[str, Any]:
        """查询工具能力、科目、口径、历史边界、刷新及导出；指定code可查本地缓存。

        tool: 需要查看说明的工具名称。
        market: 市场范围。
        code: 需要检查本地缓存的带后缀股票代码。
        topic: 帮助主题，不是行情科目或财报科目。可选tools工具说明、items科目/字段、
               ranges覆盖边界、refresh刷新规则、cache本地缓存、export导出。
        纯本地只读，不登录或联网。
        """
        return _wrap(get_market_data_help_service)(
            _data_root(), tool=tool, market=market, code=code, topic=topic,
        )

    @mcp.tool()
    def get_company_profile(
        code: str,
        information_type: company_service.InformationType,
        force_refresh: StrictBool = False,
        extra_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按类型获取完整公司信息：profile工商/概况、ipo上市发行、dividends年度分红、holders十大股东、forecast盈利预测。

        force_refresh跳过本次范围缓存；extra_parameters可省略，其可用条件和完整传法随本次结果返回。
        """
        return _render_company_markdown(_wrap(company_service.get_company_profile)(
            _data_root(), code, information_type=information_type, force_refresh=force_refresh,
            extra_parameters=extra_parameters,
        ))

    @mcp.tool()
    def get_quote_chart(
        code: str,
        adjust: str = "raw",
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "daily",
        log_scale: bool = False,
        field: str | None = None,
        events: str | list | None = None,
        keypoints: bool = False,
        drawdown_threshold: float = 0.30,
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
        events: 事件标注（K线/折线都支持）——CSV 文件路径（date,description 两列，
            兼容 events/{代码}_{简称}_事件.csv 约定）或 JSON 数组 [{date, description}]。
            图上画绿色竖线 + 顶部错开文字标签，事件日期匹配到最近一个 >= 事件日的交易日。
        keypoints: 高低点自动标注（仅折线图；K线传 true 报错）——自动提取回撤超过
            drawdown_threshold 的阶段前高（绿）/低点（红）并标注价格数字。
        drawdown_threshold: 回撤阈值（0~1，默认 0.30 = 30%），仅 keypoints=true 时生效。

        返回 {ok, path, code, chart_type, start, end, period, adjust, rows, notes}；
        path 为 PNG 文件路径，图片内容需自行读取。失败 {ok:false, error}。
        """
        return _wrap(chart_service.get_quote_chart)(
            _data_root(), code, adjust=adjust, start_date=start_date,
            end_date=end_date, period=period, log_scale=log_scale, field=field,
            events=events, keypoints=keypoints, drawdown_threshold=drawdown_threshold,
        )

    return mcp


def main() -> None:
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()
