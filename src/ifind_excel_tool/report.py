# -*- coding: utf-8 -*-
"""固定报告排版：把各板块取到的记录拼成完整 Markdown 报告。

依据 docs/iFinD-CLI全量报告命令方案-2026-11-25.md。
本模块只做排版与单位换算，不取数、不绘图、不做公司级适配。
章节顺序与表格形式对齐旧脚本导出件（中际旭创300308.SZ）与兆易创新附录。
"""
from __future__ import annotations

from typing import Any

GAP = "（本板块未取到数据，待补）"

QUARTER_NAMES = {"03-31": "一季", "06-30": "中报", "09-30": "三季", "12-31": "年"}


# ---------------- 基础格式化 ----------------

def to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in ("-", "—", "None"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def amount(value: Any, unit: str) -> str:
    """按目标单位换算：亿元保留2位小数，万元取整。"""
    number = to_number(value)
    if number is None:
        return "—"
    scale = 1e8 if unit == "亿元" else 1e4
    scaled = number / scale
    if unit == "亿元":
        return f"{scaled:,.2f}"
    return f"{scaled:,.0f}"


def ratio(value: Any, digits: int = 2) -> str:
    number = to_number(value)
    if number is None:
        return "—"
    return f"{number:,.{digits}f}"


def percent(value: Any, digits: int = 1) -> str:
    """值本身已是百分数（如 75.98 表示 75.98%）。"""
    number = to_number(value)
    if number is None:
        return "—"
    return f"{number:.{digits}f}%"


def percentage_from_fraction(numerator: Any, denominator: Any, digits: int = 1) -> str:
    up, down = to_number(numerator), to_number(denominator)
    if up is None or down in (None, 0):
        return "—"
    return f"{up / down * 100:.{digits}f}%"


def text_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value == 0:
        return "—"
    if isinstance(value, (int, float)):
        number = float(value)
        return f"{number:,.0f}" if number == int(number) else f"{number}"
    text = str(value).strip()
    return "—" if text in ("", "0", "0.0") else text


def clean(record: dict) -> dict:
    """去掉取数痕迹与单位字段，只留业务列。"""
    return {k: v for k, v in record.items()
            if k != "code" and not k.endswith("__unit")}


def markdown(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ---------------- 报告期 ----------------

def period_label(report_date: str) -> str:
    year, month_day = report_date[:4], report_date[5:10]
    return f"{year}{QUARTER_NAMES.get(month_day, month_day)}"


def annual_periods(periods: list[str]) -> list[str]:
    return [p for p in periods if p.endswith("12-31")]


def latest_annual_year(periods: list[str]) -> int:
    annuals = annual_periods(periods)
    if annuals:
        return int(annuals[0][:4])
    # 只有中报或三季报时，最近一个完整年报是上一年的
    return int(periods[0][:4]) - 1


def by_date(records: list[dict]) -> dict[str, dict]:
    return {str(rec.get("date") or "")[:10]: rec for rec in records}


def value_at(record: dict | None, label: str) -> Any:
    return None if not record else record.get(label)


# ---------------- 各板块 ----------------

BASIC_POINTS = [
    ("公司全称", "公司中文名称"),
    ("上市板块", None),
    ("地址", None),
    ("实际控制人", "实际控制人"),
    ("公司高管", None),
    ("所处行业", "所属申万行业"),
    ("主营业务", "主营业务"),
    ("员工人数", "员工总数"),
    ("注册资本", "注册资本"),
    ("公司网站", "公司网站"),
]


def render_basic_points(profile: dict) -> str:
    if not profile:
        return GAP
    get = profile.get
    lines = [
        f"- 公司全称：{text_value(get('公司中文名称'))}（{text_value(get('成立日期'))}成立）",
        f"- 上市板块：{text_value(get('交易所中文名称'))}{text_value(get('上市板块'))}"
        f"（{text_value(get('上市日期'))}上市）",
    ]
    registered = text_value(get("注册地址"))
    office = text_value(get("办公地址"))
    address = f"注册地址：{registered}；办公地址：{office}" if registered != office else f"{office}（注册地址同办公地址）"
    lines.append(f"- 地址：{address}")
    lines.append(f"- 实际控制人：{text_value(get('实际控制人'))}"
                 f"（{text_value(get('实际控制人类型'))}）")
    lines.append(f"- 公司高管：法定代表人{text_value(get('法人代表'))}、"
                 f"董事长{text_value(get('董事长'))}、总经理{text_value(get('总经理'))}")
    lines.append(f"- 所处行业：{text_value(get('所属申万行业'))}")
    lines.append(f"- 主营业务：{text_value(get('主营业务'))}")
    staff = to_number(get("员工总数"))
    lines.append(f"- 员工人数：{f'{staff:,.0f}人' if staff is not None else '—'}")
    capital = to_number(get("注册资本"))
    lines.append(f"- 注册资本：{f'{capital:,.0f}元' if capital is not None else '—'}")
    lines.append(f"- 公司网站：{text_value(get('公司网站'))}")
    return "\n".join(lines)


def render_profile_table(profile: dict) -> str:
    if not profile:
        return GAP
    rows = [[key, text_value(value)] for key, value in clean(profile).items()]
    if not rows:
        return GAP
    return markdown(["字段", "值"], rows)


def render_holders(records: list[dict]) -> str:
    if not records:
        return GAP
    order = ["rank", "股东名称", "股东性质", "股份性质", "持股数量", "持股比例", "限售股数"]
    available = [key for key in order if key in records[0]]
    if not available:
        return GAP
    headers = ["排名" if key == "rank" else key for key in available]
    rows = []
    for record in records:
        row = []
        for key in available:
            value = record.get(key)
            if key == "持股比例":
                row.append(percent(value, 2))
            elif key in ("持股数量", "限售股数"):
                number = to_number(value)
                row.append(f"{number:,.0f}" if number is not None else "—")
            elif key == "rank":
                number = to_number(value)
                row.append(f"{number:,.0f}" if number is not None else "—")
            else:
                row.append(text_value(value))
        rows.append(row)
    return markdown(headers, rows)


def render_ipo(record: dict) -> str:
    if not record:
        return GAP
    get = record.get
    after_shares = to_number(get("发行后总股本"))
    latest_shares = to_number(get("最新总股本"))
    issue_price = to_number(get("发行价"))
    after_price = to_number(get("最新后复权收盘价"))
    raw_close = to_number(get("最新除权收盘价"))
    after_cap = issue_price * after_shares if issue_price and after_shares else None
    latest_cap = raw_close * latest_shares if raw_close and latest_shares else None
    rows = [
        ["总股本（万股）",
         ratio(after_shares / 1e4 if after_shares else None, 0),
         ratio(latest_shares / 1e4 if latest_shares else None, 0)],
        ["股价（元）",
         ratio(issue_price),
         f"{ratio(after_price)}（后复权）" if after_price is not None else "—"],
        ["市值（亿元）",
         ratio(after_cap / 1e8 if after_cap else None),
         ratio(latest_cap / 1e8 if latest_cap else None)],
        ["市盈率（倍）", ratio(get("发行后市盈率")), ratio(get("最新市盈率TTM"))],
        ["市净率（倍）", ratio(get("发行后市净率")), ratio(get("最新市净率"))],
    ]
    body = markdown(["项目", "发行时", "最新"], rows)
    raised = to_number(get("募资总额"))
    net = to_number(get("募资净额"))
    fee = to_number(get("发行费用"))
    extra = ["", f"上市日期：{text_value(get('上市日期'))}　　发行数量："
                 f"{ratio(to_number(get('发行数量')) / 1e4 if get('发行数量') else None, 0)}万股",
             f"募资总额：{ratio(raised / 1e4 if raised else None, 0)}万元　　"
             f"募资净额：{ratio(net / 1e4 if net else None, 0)}万元　　"
             f"发行费用：{ratio(fee, 0)}万元"]
    return body + "\n" + "\n".join(extra)


def render_valuation(record: dict) -> str:
    if not record:
        return GAP
    get = record.get
    rows = [[
        amount(get("总市值"), "亿元"),
        amount(get("流通市值"), "亿元"),
        ratio(get("市盈率PE(TTM)")),
        ratio(get("市净率PB(MRQ)")),
        ratio(get("市销率PS(TTM)") if get("市销率PS(TTM)") is not None else get("市销率TTM")),
        percent(to_number(get("股息率近12个月")) * 100 if to_number(get("股息率近12个月")) is not None else None),
    ]]
    return markdown(["总市值（亿元）", "流通市值（亿元）", "市盈率PE(TTM)", "市净率PB(MRQ)",
                     "市销率PS(TTM)", "股息率近12个月"], rows)


def render_dividends(records: list[dict], income: dict[str, dict], periods: list[str]) -> str:
    annuals = annual_periods(periods)
    if not records or not annuals:
        return GAP
    dividends = {str(rec.get("year") or ""): rec for rec in records}
    headers = ["单位：万元"] + [f"{period[:4]}年" for period in annuals]
    rows = [
        ["现金分红总额"],
        ["股票回购总额"],
        ["现金分红及回购"],
        ["归母净利润"],
    ]
    for period in annuals:
        year = period[:4]
        record = dividends.get(year) or {}
        cash = to_number(record.get("现金分红总额"))
        total = to_number(record.get("现金分红及回购"))
        buyback = (total - cash) if (cash is not None and total is not None) else None
        rows[0].append(amount(cash, "万元"))
        rows[1].append(amount(buyback, "万元"))
        rows[2].append(amount(total, "万元"))
        rows[3].append(amount(value_at(income.get(period), "归属于母公司所有者的净利润"), "万元"))
    return markdown(headers, rows)


SUMMARY_ROWS = [
    ("营业总收入", "利润表"),
    ("营业成本", "利润表"),
    ("营业利润", "利润表"),
    ("利润总额", "利润表"),
    ("净利润", "利润表"),
    ("归属于母公司所有者的净利润", "利润表"),
    ("扣除非经常性损益后的归属母公司股东净利润", "利润表"),
    ("归属于母公司所有者权益合计", "资产负债表"),
    ("资产总计", "资产负债表"),
    ("负债合计", "资产负债表"),
    ("经营活动产生的现金流量净额", "现金流量表"),
]


def render_summary(data: dict[str, dict], periods: list[str]) -> str:
    headers = ["指标（亿元）"] + [period_label(p) for p in periods]
    rows = []
    for label, statement in SUMMARY_ROWS:
        index = data.get(statement) or {}
        values = [amount(value_at(index.get(p), label), "亿元") for p in periods]
        if all(value == "—" for value in values):
            continue
        rows.append([label] + values)
    if not rows:
        return GAP
    return markdown(headers, rows)


def _segment_block(items: list[dict], periods: list[str],
                   income: dict[str, dict]) -> list[list[str]]:
    """分产品/分地区：每个项目先一行名称，再四行明细。"""
    rows: list[list[str]] = []
    names = {}
    for record in items:
        index = record.get("index")
        name = record.get("项目名称")
        name = "" if isinstance(name, float) else str(name or "").strip()
        if not name or name in ("0", "0.0"):
            continue
        names.setdefault(index, name)
    for index in sorted(names):
        rows.append([names[index]] + [""] * len(periods))
        detail = {label: [] for label in ("收入", "收入占比", "毛利率", "毛利占比")}
        for period in periods:
            record = next((r for r in items
                           if r.get("index") == index and str(r.get("date"))[:10] == period), {})
            revenue = to_number(record.get("项目收入"))
            profit = to_number(record.get("项目毛利"))
            total_revenue = to_number(value_at(income.get(period), "营业总收入"))
            total_cost = to_number(value_at(income.get(period), "营业成本"))
            total_profit = (total_revenue - total_cost
                            if total_revenue is not None and total_cost is not None else None)
            detail["收入"].append(amount(revenue, "万元"))
            detail["收入占比"].append(percentage_from_fraction(revenue, total_revenue))
            detail["毛利率"].append(percentage_from_fraction(profit, revenue))
            detail["毛利占比"].append(percentage_from_fraction(profit, total_profit))
        for label in ("收入", "收入占比", "毛利率", "毛利占比"):
            rows.append([f"&emsp;{label}"] + detail[label])
    return rows


def render_segments(products: list[dict], districts: list[dict],
                    income: dict[str, dict], periods: list[str]) -> str:
    headers = ["项目（万元）"] + [period_label(p) for p in periods]
    blocks = []
    product_rows = _segment_block(products, periods, income)
    if product_rows:
        blocks.append("分产品收入（万元）\n\n" + markdown(headers, product_rows))
    district_rows = _segment_block(districts, periods, income)
    if district_rows:
        blocks.append("分地区收入（万元）\n\n" + markdown(headers, district_rows))
    return "\n\n".join(blocks) if blocks else GAP


def render_customers(records: list[dict], periods: list[str]) -> str:
    if not records:
        return GAP
    index = by_date(records)
    labels = [
        ("前5大客户收入占比", "percent"),
        ("第1大客户收入占比", "percent"),
        ("第1大客户名称", "text"),
        ("前5大供应商采购占比", "percent"),
        ("第1大供应商采购占比", "percent"),
        ("第1大供应商名称", "text"),
    ]
    headers = ["指标"] + [period_label(p) for p in periods]
    rows = []
    for label, kind in labels:
        values = []
        for period in periods:
            record = index.get(period) or {}
            raw = record.get(label)
            values.append(text_value(raw) if kind == "text" else percent(raw, 2))
        if all(value == "—" for value in values):
            continue
        rows.append([label] + values)
    if not rows:
        return GAP
    return markdown(headers, rows)


FORECAST_ROWS = ["营业收入均值", "营收增速", "归母净利润均值", "利润增速",
                 "总市值", "市盈率", "市销率", "市净率", "市现率", "预测机构数"]


def render_forecast(forecast: list[dict], valuation: list[dict],
                    income: dict[str, dict], periods: list[str],
                    current_cap: float | None, data_date: str) -> str:
    annual_year = latest_annual_year(periods)
    forecast_years = [annual_year + 1, annual_year + 2, annual_year + 3]
    history_years = [annual_year, annual_year - 1, annual_year - 2, annual_year - 3]
    columns = [f"{year}年E" for year in reversed(forecast_years)] + \
              [f"{year}年" for year in history_years]
    forecast_index = {str(rec.get("year") or ""): rec for rec in forecast}
    valuation_index = {str(rec.get("date") or "")[:4]: rec for rec in valuation}

    def cap_of(year: int) -> float | None:
        record = valuation_index.get(str(year)) or {}
        return to_number(record.get("总市值"))

    operating = {}
    profit = {}
    for year in forecast_years:
        record = forecast_index.get(str(year)) or {}
        operating[year] = to_number(record.get("营业收入均值"))
        profit[year] = to_number(record.get("归母净利润均值"))
    for year in history_years:
        record = income.get(f"{year}-12-31") or {}
        operating[year] = to_number(record.get("营业总收入"))
        profit[year] = to_number(record.get("归属于母公司所有者的净利润"))

    def order(values: dict[int, Any]) -> list[Any]:
        return [values.get(year) for year in list(reversed(forecast_years)) + history_years]

    def growth(values: list[float | None]) -> list[str]:
        out = ["—"]
        for previous, current in zip(values, values[1:]):
            if previous in (None, 0) or current is None:
                out.append("—")
            else:
                out.append(f"{(current / previous - 1) * 100:.1f}%")
        return out

    operating_series = order(operating)
    profit_series = order(profit)
    rows = [["营业收入均值"] + [amount(v, "万元") for v in operating_series],
            ["营收增速"] + growth(operating_series),
            ["归母净利润均值"] + [amount(v, "万元") for v in profit_series],
            ["利润增速"] + growth(profit_series)]

    caps, pe, ps, pb, pcf = [], [], [], [], []
    for year in list(reversed(forecast_years)) + history_years:
        if year in forecast_years:
            cap = current_cap
            caps.append(amount(cap, "万元"))
            pe.append(ratio(cap / profit[year] if cap and profit[year] else None))
            ps.append(ratio(cap / operating[year] if cap and operating[year] else None))
            pb.append("—")
            pcf.append("—")
        else:
            record = valuation_index.get(str(year)) or {}
            cap = to_number(record.get("总市值"))
            caps.append(amount(cap, "万元"))
            pe.append(ratio(cap / profit[year] if cap and profit[year] else None))
            ps.append(ratio(cap / operating[year] if cap and operating[year] else None))
            pb.append(ratio(record.get("市净率")))
            pcf.append(ratio(record.get("市现率")))
    rows += [["总市值"] + caps, ["市盈率"] + pe, ["市销率"] + ps,
             ["市净率"] + pb, ["市现率"] + pcf]

    counts = []
    for year in list(reversed(forecast_years)) + history_years:
        record = forecast_index.get(str(year)) or {}
        number = to_number(record.get("预测机构数"))
        counts.append(f"{number:,.0f}" if number else "—")
    rows.append(["预测机构数"] + counts)

    table = markdown(["单位：万元"] + columns, rows)
    return (table + f"\n\n预测日期：{data_date}，最新总市值："
            f"{amount(current_cap, '亿元')}亿元\n"
            "市盈率、市销率的预测列用当前总市值除以预测值；历史列用年末总市值除以当年实际值；"
            "市净率、市现率取年末值。")


def render_statement(records: list[dict], periods: list[str],
                     groups: dict[str, str], unit: str = "万元") -> str:
    if not records:
        return GAP
    index = by_date(records)
    sample = records[0]
    labels = [key for key in sample if key not in ("date", "code") and not key.endswith("__unit")]
    blocks: list[str] = []
    current_group = None
    current_rows: list[list[str]] = []
    headers = ["科目（万元）"] + [period_label(p) for p in periods]

    def flush():
        nonlocal current_rows
        if current_rows:
            if current_group:
                blocks.append(f"**{current_group}**\n\n" + markdown(headers, current_rows))
            else:
                blocks.append(markdown(headers, current_rows))
            current_rows = []

    for label in labels:
        values = [value_at(index.get(p), label) for p in periods]
        numbers = [to_number(v) for v in values]
        if all(n in (None, 0) for n in numbers):
            continue
        group = groups.get(label)
        if group != current_group:
            flush()
            current_group = group
        current_rows.append([label] + [amount(v, unit) for v in values])
    flush()
    result = "\n\n".join(blocks)
    # 报告不使用加粗，分组标题改用小标题行
    return result.replace("**", "")


# ---------------- 拼装 ----------------

def build_report(*, company: str, code: str, periods: list[str],
                 data: dict[str, list[dict]], groups: dict[str, dict] | None = None,
                 chart_file: str | None = None, data_date: str = "",
                 events_note: str = "", warnings: list[str] | None = None) -> str:
    groups = groups or {}
    profile = (data.get("工商信息") or [{}])[0]
    profile = clean(profile) if profile else {}
    holders = data.get("十大股东") or []
    ipo = clean((data.get("IPO信息") or [{}])[0]) if data.get("IPO信息") else {}
    valuation = clean((data.get("估值快照") or [{}])[0]) if data.get("估值快照") else {}

    balance = by_date(data.get("资产负债表") or [])
    income = by_date(data.get("利润表") or [])
    cashflow = by_date(data.get("现金流量表") or [])

    lines = [f"# {company}（{code}）公司报告", ""]

    lines += ["## 一、公司基本信息", "", render_basic_points(profile), ""]
    lines += ["### 十大股东", "", render_holders(holders), ""]
    lines += ["### 工商信息全字段", "", render_profile_table(profile), ""]

    lines += ["## 二、资本运作", "", "### IPO信息", "", render_ipo(ipo), ""]

    lines += ["## 三、行情走势及分红", ""]
    if chart_file:
        lines += [f"![]({chart_file})", ""]
        if events_note:
            lines += [events_note, ""]
    lines += ["### 估值快照", "", render_valuation(valuation), ""]
    lines += ["### 分红", "", render_dividends(data.get("分红") or [], income, periods), ""]

    lines += ["## 四、财报摘要", "", render_summary(
        {"利润表": income, "资产负债表": balance, "现金流量表": cashflow}, periods), "",
        "完整三表见附录，单位万元。", ""]

    lines += ["## 五、公司业务", "", "### 营收结构", "",
              render_segments(data.get("分产品") or [], data.get("分地区") or [],
                              income, periods), ""]
    customer_table = render_customers(data.get("客户供应商") or [], periods)
    if customer_table != GAP:
        lines += ["客户供应商集中度", "", customer_table, ""]

    lines += ["## 六、盈利预测与估值", "",
              render_forecast(data.get("盈利预测") or [], data.get("历史估值") or [],
                              income, periods, to_number(valuation.get("总市值")),
                              data_date or periods[0]), ""]

    lines += ["---", "", "## 附录", "",
              "附录金额统一换算为万元，四舍五入取整。", ""]
    for title, key, statement in (("A、资产负债表", "资产负债表", "资产负债表"),
                                  ("B、利润表", "利润表", "利润表"),
                                  ("C、现金流量表", "现金流量表", "现金流量表")):
        records = data.get(key) or []
        lines += [f"### {title}", "", render_statement(records, periods,
                                                       groups.get(statement) or {}), ""]

    if warnings:
        lines += ["## 数据获取提示", "", *[f"- {w}" for w in dict.fromkeys(warnings)], ""]

    return "\n".join(lines).replace("**", "") + "\n"
