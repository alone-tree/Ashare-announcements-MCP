# -*- coding: utf-8 -*-
"""第三块 报告功能：一条命令出一份完整报告。

这份功能自己完成整条链路：按报告口径决定取哪些数据 → 调第二块取数 →
单位换算与排版交给 report.py → 绘图交给 chart.py → 落盘。
调用方只需要给股票代码和输出目录。

报告口径（取哪几期、哪些板块）属于本功能的业务规则，不是通用取数规则，
所以放在这里而不是第二块。
"""
from __future__ import annotations

from datetime import date as _date, datetime
from pathlib import Path

from ifind_excel_tool.features import chart as _chart
from ifind_excel_tool.features import report as _report
from ifind_excel_tool.indicators import definitions, fetch

REPORT_COLUMNS = 7
REPORT_BLOCKS = ("工商信息", "十大股东", "IPO信息", "历史行情", "估值快照", "分红",
                 "资产负债表", "利润表", "现金流量表", "分产品", "分地区",
                 "客户供应商", "盈利预测", "历史估值")


def report_periods(latest: str, columns: int = REPORT_COLUMNS) -> list[str]:
    """按报告口径铺报告期列。

    最新期若不是年报，第2列放去年同期（同比），其余补最近年报；最新期是年报时全部按年报铺。
    """
    year = int(latest[:4])
    periods = [latest]
    if not latest.endswith("12-31"):
        periods.append(f"{year - 1}{latest[4:]}")
    annual_start = year - 1
    for offset in range(0, columns + 2):
        if len(periods) >= columns:
            break
        periods.append(f"{annual_start - offset}-12-31")
    return periods[:columns]


def segment_periods(latest: str, columns: int = REPORT_COLUMNS) -> list[str]:
    """营收结构一类只在年报和中报披露，不能用三季报一季报。

    口径：最新中报或年报 + 去年同类 + 逐年年报，去重后共7列。
    """
    year, md = int(latest[:4]), latest[5:]
    if md == "09-30":
        first = f"{year}-06-30"
    elif md == "03-31":
        first = f"{year - 1}-12-31"
    else:
        first = latest
    fy, fmd = first[:4], first[5:]
    out = [first, f"{int(fy) - 1}-{fmd}"]
    annual_start = int(fy) if fmd == "12-31" else int(fy) - 1
    for offset in range(columns + 4):
        if len(out) >= columns:
            break
        period = f"{annual_start - offset}-12-31"
        if period not in out:
            out.append(period)
    seen, result = set(), []
    for period in out:
        if period not in seen:
            seen.add(period)
            result.append(period)
        if len(result) >= columns:
            break
    return result


def _groups(name: str) -> dict[str, str]:
    spec = definitions.load_packages()[name]
    return {f["label"]: f.get("group") or "" for f in spec.get("fields") or []}


def generate(req: dict) -> dict:
    """一条命令出完整报告：取数、换算、绘图、拼Markdown、落盘。"""
    code = (req.get("code") or "").strip()
    output = (req.get("output") or "").strip()
    if not code:
        return {"ok": False, "error": "code 必须提供"}
    if not output:
        return {"ok": False, "error": "output 必须提供（输出目录）"}
    end_date = req.get("end_date") or _date.today().isoformat()
    chart_start = req.get("chart_start") or "2016-01-01"
    warnings: list[str] = []

    latest = fetch.probe_latest_report(code)
    if not latest:
        return {"ok": False, "error": f"无法确定最新报告期（探测 {code} 失败）",
                "hint": fetch.engine.ZERO_VALUE_HINT}
    periods = report_periods(latest)
    segments = segment_periods(latest)
    annuals = [p for p in periods if p.endswith("12-31")]
    annual_year = int(annuals[0][:4]) if annuals else int(periods[0][:4]) - 1
    forecast_years = [str(annual_year + offset) for offset in (1, 2, 3)]

    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    data: dict[str, list[dict]] = {}
    csv_paths: dict[str, str] = {}

    def take(block: str, **kwargs) -> None:
        result = fetch.get_package(block, code=code, auto_export_rows=None, **kwargs)
        if not result.get("ok"):
            warnings.append(f"{block}取数失败：{result.get('error')}")
            data[block] = []
            return
        data[block] = result.get("records") or []

    basic = fetch.get_package("工商信息", code=code, auto_export_rows=None)
    if not basic.get("ok"):
        return {"ok": False, "error": f"工商信息取数失败：{basic.get('error')}"}
    data["工商信息"] = basic.get("records") or []
    profile = data["工商信息"][0] if data["工商信息"] else {}
    company = (req.get("company") or profile.get("证券简称")
               or profile.get("公司中文名称") or code).strip()

    def export(block: str) -> str:
        path = out_dir / f"{company}-{block}.csv"
        csv_paths[block] = str(path)
        return str(path)

    take("十大股东", date=latest, export_path=export("十大股东"))
    take("IPO信息", date=end_date)
    dividend_years = sorted({p[:4] for p in annuals} | {str(end_date)[:4]}, reverse=True)
    take("分红", dims={"year": dividend_years})
    take("资产负债表", report_dates=periods)
    income_periods = sorted(set(periods) | set(segments), reverse=True)
    take("利润表", report_dates=income_periods)
    take("现金流量表", report_dates=periods)
    take("分产品", report_dates=segments)
    take("分地区", report_dates=segments)
    take("客户供应商", report_dates=segments)
    take("盈利预测", date=end_date, dims={"year": forecast_years})
    take("历史估值", dims={"date": annuals})
    take("估值快照", date=end_date)

    quote_path = export("历史行情")
    quote = fetch.get_package("历史行情", code=code, start=chart_start, end=end_date,
                              export_path=quote_path, auto_export_rows=None)
    if quote.get("ok"):
        data["历史行情"] = quote.get("records") or []
    else:
        data["历史行情"] = []
        warnings.append(f"历史行情取数失败：{quote.get('error')}")

    for block in REPORT_BLOCKS:
        if block in ("历史行情",) or block not in data:
            continue
        path = out_dir / f"{company}-{block}.csv"
        csv_paths[block] = str(path)
        from ifind_excel_tool.indicators import packages
        packages.to_csv(data[block], path)

    chart_file = None
    if data.get("历史行情"):
        png = out_dir / f"{company}-行情图.png"
        drawn = _chart.draw({"template": "close_mcap_events", "data_path": quote_path,
                             "output": str(png), "events": req.get("events")})
        if drawn.get("ok"):
            chart_file = png.name
        else:
            warnings.append(f"绘图失败：{drawn.get('error')}")

    violations = _violations(code, profile, end_date)
    data["报表元信息"] = _report_meta(code, periods, warnings)

    groups = {name: _groups(name) for name in ("资产负债表", "利润表", "现金流量表")}
    markdown_text = _report.build_report(
        company=company, code=code, periods=periods, segment_periods=segments,
        data=data, groups=groups, chart_file=chart_file, data_date=end_date,
        violations=violations, warnings=warnings)
    md_path = out_dir / f"{company}-报告骨架-{stamp}.md"
    md_path.write_text(markdown_text, encoding="utf-8")

    return {"ok": True, "output": str(md_path), "company": company, "code": code,
            "latest_report": latest, "periods": periods,
            "forecast_years": forecast_years, "chart": chart_file,
            "csv": csv_paths, "warnings": warnings, "chars": len(markdown_text)}


def _violations(code: str, profile: dict, end_date: str) -> str:
    """违规次数依赖实际上市日，工商信息里没有这个动态参数，单独取一次。"""
    ipo_date = str(profile.get("上市日期") or "")
    if not ipo_date:
        return "—"
    result = fetch.engine.fetch_matrix(
        [[f'=@thsiFinD("ths_int_illegality_num_stock","{code}","{ipo_date}","{end_date}")']],
        text_ok=True)
    values = result.get("values") or []
    number = values[0][0] if values and values[0] else None
    return f"{number:,.0f}" if isinstance(number, (int, float)) else "—"


def _report_meta(code: str, periods: list[str], warnings: list[str]) -> list[dict]:
    """报表元信息：发布时间、审计单位、审计意见，一次取全部期。

    一季报三季报没有审计数据，上游返回空或0属正常，原样留空。
    """
    formulas = []
    for period in periods:
        formulas.append(f'=@thsiFinD("ths_regular_report_actual_dd_stock","{code}","{period}")')
        formulas.append(f'=@thsiFinD("ths_audit_institution_stock","{code}","{period}",100)')
        formulas.append(f'=@thsiFinD("ths_audit_opinion_type_stock","{code}","{period}",100)')
    result = fetch.engine.fetch_formulas(formulas, text_ok=True)
    errors = result.get("errors")
    if errors:
        warnings.append(f"报表元信息取数失败：{errors}")
        return []
    values = result.get("values") or []
    rows = []
    for index, period in enumerate(periods):
        chunk = values[index * 3:index * 3 + 3]
        published = chunk[0] if len(chunk) > 0 else None
        auditor = chunk[1] if len(chunk) > 1 else None
        opinion = chunk[2] if len(chunk) > 2 else None
        rows.append({"date": period,
                     "披露日期": str(published)[:10] if isinstance(published, str) else "",
                     "审计单位": auditor if isinstance(auditor, str) else "",
                     "审计意见": opinion if isinstance(opinion, str) else ""})
    return rows
