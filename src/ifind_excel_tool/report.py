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


# 科目显示别名：用户90脚本 INCOME_ITEMS 的别名，长名缩短便于打印阅读。
DISPLAY_ALIAS = {
    "归属于母公司股东的净利润": "归母净利润",
    "归属于母公司所有者的净利润": "归母净利润",
    "扣除非经常性损益后的归属母公司股东净利润": "扣非净利润",
    "归属于母公司股东的扣除非经常性损益的净利润": "扣非净利润",
    "(一) 基本每股收益(元)": "基本每股收益",
    "减：所得税费用": "所得税费用",
    "实收资本(或股本)": "实收资本",
    "归属于母公司所有者权益合计": "归母所有者权益合计",
    "支付给职工以及为职工支付的现金": "支付给职工的现金",
    "分配股利、利润或偿付利息支付的现金": "分配股利或偿付利息",
    "购建固定资产、无形资产和其他长期资产支付的现金": "购建固定资产、无形资产和其他长期资产",
    "汇率变动对现金及现金等价物的影响": "汇率变动影响",
    "经营活动产生的现金流量净额": "经营活动净现金流",
    "投资活动产生的现金流量净额": "投资活动净现金流",
    "筹资活动产生的现金流量净额": "筹资活动净现金流",
    "现金及现金等价物净增加额": "现金净增加额",
}

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


def _control_line(profile: dict, holders: list[dict]) -> str:
    """控股股东及实控人：参考件格式，名称+股比；多个用逗号分隔时逐个带股比。"""
    def pct_text(name: str, pct: Any) -> str:
        numbers = []
        for part in str(pct or "").split(","):
            n = to_number(part)
            if n is not None and n != 0:
                numbers.append(f"{n:.2f}%")
        names = [x.strip() for x in str(name or "").split(",") if x.strip()]
        if not names or names == ["0"]:
            return ""
        out = []
        for i, one in enumerate(names):
            p = numbers[i] if i < len(numbers) else (numbers[0] if len(numbers) == 1 else "")
            out.append(f"{one}" + (f"（{p}）" if p else ""))
        return "、".join(out)

    holder = pct_text(profile.get("控股股东"), profile.get("控股股东股比"))
    controller = pct_text(profile.get("实际控制人"), profile.get("实际控制人股比"))
    parts = []
    if holder:
        parts.append(f"控股股东：{holder}")
    if controller:
        parts.append(f"实际控制人：{controller}")
    return "，".join(parts) if parts else "—"


def render_basic_points(profile: dict, holders: list[dict] | None = None,
                        violations: str = "—") -> str:
    """严格按中际旭创参考件的9条要点，不增不减。"""
    holders = holders or []
    get = profile.get
    lines = [
        f"- 公司全称：{text_value(get('公司中文名称'))}（{text_value(get('成立日期'))}成立）",
        f"- 上市板块：{text_value(get('交易所中文名称') or get('上市地点'))}{text_value(get('上市板块'))}（{text_value(get('上市日期'))}上市）",
    ]
    registered = text_value(get("注册地址"))
    office = text_value(get("办公地址"))
    address = f"{office}（注册地址同办公地址）" if registered == office else f"办公地址：{office}，注册地址：{registered}"
    lines.append(f"- 地址：{address}")
    lines.append(f"- 控股股东及实控人：{_control_line(profile, holders)}")
    lines.append(f"- 公司高管：法定代表人{text_value(get('法人代表'))}、"
                 f"董事长{text_value(get('董事长'))}、总经理{text_value(get('总经理'))}")
    lines.append(f"- 所处行业：{text_value(get('所属申万行业'))}")
    lines.append(f"- 主营业务：{text_value(get('主营业务'))}")
    staff = to_number(get("员工总数"))
    lines.append(f"- 员工人数：{f'{staff:,.0f}人' if staff is not None else '—'}")
    lines.append(f"- 上市以来违规次数：{violations}")
    return "\n".join(lines)


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


def render_ipo(record: dict, data_date: str = "") -> str:
    if not record:
        return GAP
    get = record.get
    after_shares = to_number(get("发行后总股本"))
    latest_shares = to_number(get("最新总股本"))
    issue_price = to_number(get("发行价"))
    after_price = to_number(get("最新后复权收盘价"))
    latest_cap = to_number(get("最新总市值"))  # 直接公式，不用总股本×收盘价推算
    after_cap = issue_price * after_shares if issue_price and after_shares else None
    ipo_date = text_value(get("上市日期"))
    latest_title = f"最新（{data_date}）" if data_date else "最新"
    rows = [
        ["总股本（万股）", ratio(after_shares / 1e4 if after_shares else None, 0),
         ratio(latest_shares / 1e4 if latest_shares else None, 0)],
        ["股价（元）", ratio(issue_price),
         f"{ratio(after_price)}（后复权）" if after_price is not None else "—"],
        ["市值（亿元）", ratio(after_cap / 1e8 if after_cap else None),
         ratio(latest_cap / 1e8 if latest_cap else None)],
        ["市盈率（倍）", ratio(get("发行后市盈率")), ratio(get("最新市盈率TTM"))],
        ["市净率（倍）", ratio(get("发行后市净率")), ratio(get("最新市净率"))],
    ]
    body = markdown(["项目", f"发行时（{ipo_date}）", latest_title], rows)
    raised = to_number(get("募资总额"))
    net = to_number(get("募资净额"))
    fee = to_number(get("发行费用"))
    items = [
        f"- 发行数量：{ratio(to_number(get('发行数量')) / 1e4 if get('发行数量') else None, 0)}万股",
        f"- 募资总额：{ratio(raised / 1e4 if raised else None, 0)}万元",
        f"- 募资净额：{ratio(net / 1e4 if net else None, 0)}万元",
        f"- 发行费用：{ratio(fee, 0)}万元",
    ]
    return body + "\n\n" + "\n".join(items)


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
    years = sorted({str(rec.get("year") or "") for rec in records} | {p[:4] for p in annuals}, reverse=True)
    # 最新年度列按最新已披露财报季标注（如「2026三季」），避免误解为年报
    latest_label = period_label(periods[0]) if periods else ""
    headers = ["单位：万元"]
    for y in years:
        headers.append(latest_label if y == years[0] and latest_label and str(y) in latest_label
                       else f"{y}年")
    rows = [
        ["现金分红总额"],
        ["股票回购总额"],
        ["现金分红及回购"],
        ["归母净利润"],
    ]
    for year in years:
        record = dividends.get(year) or {}
        cash = to_number(record.get("现金分红总额"))
        total = to_number(record.get("现金分红及回购"))
        buyback = (total - cash) if (cash is not None and total is not None) else None
        rows[0].append(amount(cash, "万元"))
        rows[1].append(amount(buyback, "万元"))
        rows[2].append(amount(total, "万元"))
        # 归母净利润取该年度最新已披露报告期：有年报用年报，没有则用三季报/中报，不等年报。
        candidates = [p for p in income if p.startswith(str(year) + "-")]
        latest_period = max(candidates) if candidates else None
        rows[3].append(amount(value_at(income.get(latest_period), "归属于母公司所有者的净利润"), "万元"))
    note = ("最新列按截至" + (latest_label or "最新财报季") + "的现金分红方案统计，不等年报；"
            "归母净利润取该年度最新已披露报告期；历史年度为完整年度口径。")
    return markdown(headers, rows) + "\n\n" + note


SUMMARY_ROWS = [
    ("营业总收入", "利润表"),
    ("营业利润", "利润表"),
    ("扣除非经常性损益后的归属母公司股东净利润", "利润表"),
    ("经营活动产生的现金流量净额", "现金流量表"),
    ("资产总计", "资产负债表"),
    ("归属于母公司所有者权益合计", "资产负债表"),
]


def render_summary(data: dict[str, dict], periods: list[str]) -> str:
    headers = ["指标（亿元）"] + [period_label(p) for p in periods]
    rows = []
    for label, statement in SUMMARY_ROWS:
        index = data.get(statement) or {}
        values = [amount(value_at(index.get(p), label), "亿元") for p in periods]
        if all(value == "—" for value in values):
            continue
        rows.append([DISPLAY_ALIAS.get(label, label)] + values)
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
            # 收入占比、毛利率、毛利占比均用金额本地相除，和早期的Excel模板计算方法一致
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
    denominator_year = annual_year - 4  # 隐藏年份：只作末列（最早显示年）增速的分母，不显示
    display_years = list(reversed(forecast_years)) + history_years
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
    for year in history_years + [denominator_year]:
        record = income.get(f"{year}-12-31") or {}
        operating[year] = to_number(record.get("营业总收入"))
        profit[year] = to_number(record.get("归属于母公司所有者的净利润"))

    calc_years = display_years + [denominator_year]  # 多一年作分母，展示时截掉

    def order(values: dict[int, Any]) -> list[Any]:
        return [values.get(year) for year in calc_years]

    def growth(values: list[float | None]) -> list[str]:
        """参考件口径：第i列增速 = 第i列 / 第i+1列 - 1（相对更早一年）。
        列按 2028E→2027E→...→2022 排列，2028E列除以2027E也有增速；末列留「—」。"""
        out = []
        for i, current in enumerate(values):
            previous = values[i + 1] if i + 1 < len(values) else None
            # 预测无券商覆盖时上游返回0，视为无数据，不算增速（避免假的-100%）
            if previous in (None, 0) or current in (None, 0):
                out.append("—")
            else:
                out.append(f"{(current / previous - 1) * 100:.1f}%")
        return out

    n = len(display_years)
    operating_series = order(operating)
    profit_series = order(profit)
    rows = [["营业收入均值"] + [amount(v, "万元") for v in operating_series[:n]],
            ["营收增速"] + growth(operating_series)[:n],
            ["归母净利润均值"] + [amount(v, "万元") for v in profit_series[:n]],
            ["利润增速"] + growth(profit_series)[:n]]

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
    rows += [["总市值（万元）"] + caps, ["市盈率"] + pe, ["市销率"] + ps,
             ["市净率"] + pb, ["市现率"] + pcf]

    counts = []
    for year in list(reversed(forecast_years)) + history_years:
        record = forecast_index.get(str(year)) or {}
        number = to_number(record.get("预测机构数"))
        counts.append(f"{number:,.0f}" if number else "—")
    rows.append(["预测机构数"] + counts)

    table = markdown(["单位：万元"] + columns, rows)
    return (table + f"\n\n预测日期：{data_date}，最新总市值："
            f"{amount(current_cap, '万元')}万元（{amount(current_cap, '亿元')}亿元）\n"
            "市盈率、市销率的预测列用当前总市值除以预测值；历史列用年末总市值除以当年实际值；"
            "市净率、市现率取年末值。")



# 附录科目白名单：严格照兆易创新参考件，参考件没有的科目一律不进。
# 每项为 (小标题, [(展示名, 场景label或@计算标记), ...])，小标题为空表示不分组。
APPENDIX_BALANCE = [
    ("流动资产：", ["货币资金", "交易性金融资产", "应收票据及应收账款", "应收票据",
                 "应收账款", "预付款项", "其他应收款合计", "存货", "其他流动资产", "流动资产合计"]),
    ("非流动资产：", ["长期股权投资", "固定资产", "在建工程", "使用权资产", "无形资产",
                  "商誉", "递延所得税资产", "其他非流动资产", "非流动资产合计", "资产总计"]),
    ("流动负债：", ["短期借款", "应付票据及应付账款", "应付账款", "合同负债", "应付职工薪酬",
                 "应交税费", "其他应付款合计", "一年内到期的非流动负债", "其他流动负债", "流动负债合计"]),
    ("非流动负债：", ["租赁负债", "预计负债", "递延所得税负债", "递延收益-非流动负债",
                   "非流动负债合计", "负债合计"]),
    ("所有者权益：", ["实收资本(或股本)", "资本公积", "减：库存股", "其他综合收益", "盈余公积",
                   "未分配利润", "少数股东权益", "归属于母公司所有者权益合计", "所有者权益合计",
                   "负债和所有者权益总计"]),
]

APPENDIX_INCOME = [
    ("", ["营业总收入", "营业成本", "@毛利润", "@毛利率", "税金及附加", "销售费用",
          "管理费用", "研发费用", "财务费用", "投资收益", "公允价值变动收益", "资产减值损失",
          "信用减值损失", "其他收益", "营业利润", "利润总额", "减：所得税费用", "净利润",
          "归属于母公司所有者的净利润", "扣除非经常性损益后的归属母公司股东净利润",
          "(一) 基本每股收益(元)"]),
]

APPENDIX_CASHFLOW = [
    ("经营活动：", ["销售商品、提供劳务收到的现金", "收到的税费返还", "经营活动现金流入小计",
                 "购买商品、接受劳务支付的现金", "支付给职工以及为职工支付的现金", "支付的各项税费",
                 "经营活动现金流出小计", "经营活动产生的现金流量净额"]),
    ("投资活动：", ["取得投资收益收到的现金", "购建固定资产、无形资产和其他长期资产支付的现金",
                 "投资支付的现金", "投资活动产生的现金流量净额"]),
    ("筹资活动：", ["吸收投资收到的现金", "取得借款收到的现金", "偿还债务支付的现金",
                 "分配股利、利润或偿付利息支付的现金", "筹资活动产生的现金流量净额",
                 "汇率变动对现金及现金等价物的影响", "现金及现金等价物净增加额",
                 "期初现金及现金等价物余额", "期末现金及现金等价物余额"]),
]


def render_statement(records: list[dict], periods: list[str],
                     spec: list[tuple[str, list[str]]] | None = None,
                     group_map: dict[str, str] | None = None,
                     *, flat: bool = False,
                     skip_groups: tuple[str, ...] = ("间接法",)) -> str:
    """按参考件分组渲染：保留全部有数据的科目，仅剔除展示期内整行全0的科目。

    spec 为可选白名单（旧参考模式）；不传时按 records 字段顺序与 group 分组渲染，
    科目顺序由场景JSON定义（报表标准顺序），不逐家公司定制。
    """
    if not records:
        return GAP
    index = by_date(records)
    headers = ["科目"] + [period_label(p) for p in periods]
    sample = records[0]
    if spec:
        labels_by_group = [(g, labels) for g, labels in spec]
    else:
        groups: dict[str, list[str]] = {}
        for key in sample:
            if key in ("date", "code") or key.endswith("__unit"):
                continue
            group = (group_map or {}).get(key, "")
            groups.setdefault(group, []).append(key)
        labels_by_group = list(groups.items())

    def cell(label: str, period: str) -> str:
        record = index.get(period) or {}
        if label == "@毛利润":
            revenue = to_number(record.get("营业总收入"))
            cost = to_number(record.get("营业成本"))
            return amount(revenue - cost, "万元") if revenue is not None and cost is not None else "—"
        if label == "@毛利率":
            revenue = to_number(record.get("营业总收入"))
            cost = to_number(record.get("营业成本"))
            return percentage_from_fraction(
                (revenue - cost) if revenue is not None and cost is not None else None, revenue)
        raw = record.get(label)
        if "(元)" in label:
            number = to_number(raw)
            return "—" if number in (None, 0) else f"{number:.2f}"
        return amount(raw, "万元")

    blocks: list[str] = []
    if flat:
        # 用户定稿：利润表不分组，参考件是单表
        labels_by_group = [("", [x for _, g in labels_by_group for x in g])]
    for group_title, labels in labels_by_group:
        if group_title and any(k in group_title for k in skip_groups):
            continue
        rows = []
        for label in labels:
            # 利润表不显示其他综合收益相关科目（flat模式下整块略过）
            if flat and "综合收益" in label:
                continue
            # 剔全0按原始值判断：有数但换算万元后四舍五入为0的科目要保留。
            raw_values = [to_number(value_at(index.get(p), label)) for p in periods]
            if all(v in (None, 0) for v in raw_values):
                continue
            values = [cell(label, period) for period in periods]
            rows.append([DISPLAY_ALIAS.get(label, label)] + values)
        if not rows:
            continue
        table = markdown(headers, rows)
        blocks.append(group_title.rstrip("：") + "：" + "\n\n" + table if group_title else table)
    return "\n\n".join(blocks) if blocks else GAP


META_ROWS = [
    ("发布时间", "披露日期"),
    ("审计单位", "审计单位"),
    ("审计意见", "审计意见"),
]


def render_meta(meta: list[dict], periods: list[str]) -> str:
    """报表元信息：发布时间、审计单位、审计意见。三季度等无审计数据的正常留空。"""
    if not meta:
        return ""
    index = by_date(meta)
    headers = ["项目"] + [period_label(p) for p in periods]
    rows = []
    for display, key in META_ROWS:
        values = [text_value((index.get(p) or {}).get(key)) for p in periods]
        if all(v == "—" for v in values):
            continue
        rows.append([display] + values)
    return markdown(headers, rows) if rows else ""


def build_report(*, company: str, code: str, periods: list[str],
                 segment_periods: list[str] | None = None,
                 data: dict[str, list[dict]], groups: dict[str, dict] | None = None,
                 chart_file: str | None = None, data_date: str = "",
                 events_note: str = "", violations: str = "—",
                 warnings: list[str] | None = None) -> str:
    """严格照中际旭创正文 + 兆易创新附录排版；参考件没有的不进。"""
    segment_periods = segment_periods or periods
    profile = (data.get("工商信息") or [{}])[0]
    profile = {k: v for k, v in profile.items() if not k.endswith("__unit")} if profile else {}
    holders = data.get("十大股东") or []
    ipo = clean((data.get("IPO信息") or [{}])[0]) if data.get("IPO信息") else {}
    valuation = clean((data.get("估值快照") or [{}])[0]) if data.get("估值快照") else {}

    balance = by_date(data.get("资产负债表") or [])
    income = by_date(data.get("利润表") or [])
    cashflow = by_date(data.get("现金流量表") or [])

    lines = [f"# {company}（{code}）公司报告", ""]

    lines += ["## 一、公司基本信息", "",
              render_basic_points(profile, holders, violations), ""]
    lines += [f"### 十大股东（截至{periods[0]}）", "", render_holders(holders), ""]

    lines += ["## 二、资本运作", "", "### IPO信息", "", render_ipo(ipo, data_date), "",
              "### 再融资与重大投资", ""]

    lines += ["## 三、行情走势及分红", ""]
    if chart_file:
        lines += [f"![]({chart_file})", ""]
        if events_note:
            lines += [events_note, ""]
    lines += ["### 分红", "", render_dividends(data.get("分红") or [], income, periods), ""]

    lines += ["## 四、财报摘要", "", render_summary(
        {"利润表": income, "资产负债表": balance, "现金流量表": cashflow}, periods), ""]

    lines += ["## 五、公司业务", "", "### 营收结构", "",
              render_segments(data.get("分产品") or [], data.get("分地区") or [],
                              income, segment_periods), ""]
    customer_table = render_customers(data.get("客户供应商") or [], segment_periods)
    if customer_table != GAP:
        lines += ["客户供应商集中度", "", customer_table, ""]
    lines += ["### 业务概述", "", "### 主要客户", ""]

    lines += ["## 六、盈利预测与估值", "",
              render_forecast(data.get("盈利预测") or [], data.get("历史估值") or [],
                              income, periods, to_number(valuation.get("总市值")),
                              data_date or periods[0]), ""]

    lines += ["---", "", "## 附录", ""]
    meta_table = render_meta(data.get("报表元信息") or [], periods)
    if meta_table:
        lines += [meta_table, ""]
    for title, key, flat in (("A、资产负债表", "资产负债表", False),
                             ("B、利润表", "利润表", True),
                             ("C、现金流量表", "现金流量表", False)):
        lines += [f"### {title}（万元）", "",
                  render_statement(data.get(key) or [], periods,
                                   group_map=groups.get(key) or {}, flat=flat,
                                   skip_groups=("间接法", "其他综合收益")), ""]

    if warnings:
        lines += ["## 数据获取提示", "", *[f"- {w}" for w in dict.fromkeys(warnings)], ""]

    return "\n".join(lines).replace("**", "") + "\n"
