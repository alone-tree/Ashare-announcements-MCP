"""已确认的默认输出、营收结构维度与计算指标；help及请求共用。"""
STATEMENTS = ("balance", "income", "cash_flow", "segments", "meta")
DEFAULT_ITEMS = {
    "balance": ["货币资金", "交易性金融资产", "应收票据及账款", "存货", "流动资产合计",
                "长期股权投资", "固定资产", "在建工程", "无形资产", "商誉", "非流动资产合计", "资产总计",
                "短期借款", "应付票据及账款", "合同负债", "一年内到期的非流动负债", "流动负债合计",
                "长期借款", "应付债券", "非流动负债合计", "负债合计", "所有者权益合计", "归属于母公司股东权益合计"],
    "income": ["营业总收入", "毛利率", "营业总成本", "营业成本", "营业利润", "合并净利润", "扣非净利润"],
    "cash_flow": ["经营活动现金流入", "经营活动现金流量净额", "投资活动现金流量净额",
                  "筹资活动现金流量净额", "现金及现金等价物净增加额", "期末现金及现金等价物余额"],
    "segments": ["income by product", "income by industry", "income by region",
                 "income by customer", "purchase by supplier"],
    "meta": ["报告截止日", "公告日", "币种", "审计意见", "内控审计意见", "审计单位"],
}
SEGMENTS = {"income by product": "product", "income by industry": "industry", "income by region": "district",
            "income by customer": "customer", "purchase by supplier": "supplier"}
# 港股默认清单：只列东财港股模板近5期实际有值的科目，不为对齐A股凑数。
# 注：港股利润表有原始科目“毛利”(004007999)，与大陆计算指标“毛利”同名，比率口径未定前不列入默认。
DEFAULT_ITEMS_HK = {
    "balance": ["现金及等价物", "应收帐款", "存货", "流动资产合计", "联营公司权益", "物业厂房及设备",
                "非流动资产合计", "总资产", "短期贷款", "应付帐款", "流动负债合计",
                "长期贷款", "非流动负债合计", "总负债", "少数股东权益", "净资产", "股东权益",
                "总权益及总负债"],
    "income": ["营业额", "营运收入", "销售及分销费用", "行政开支", "经营溢利", "融资成本",
               "除税前溢利", "除税后溢利", "股东应占溢利", "每股基本盈利"],
    "cash_flow": ["经营业务现金净额", "投资业务现金净额", "融资前现金净额", "融资业务现金净额",
                  "现金净额", "期初现金", "期末现金"],
    "segments": [],
    "meta": ["报告截止日", "币种"],
}


def default_items(market: str) -> dict:
    """按市场返回默认科目清单；目前只有港股与大陆分开，其他市场沿用大陆清单。"""
    return DEFAULT_ITEMS_HK if market == "HK" else DEFAULT_ITEMS


RATIOS = {
    "毛利": ("营业收入", "营业成本"),
    "毛利率": ("营业收入", "营业成本"),
    "合并净利率": ("合并净利润", "营业收入"),
    "归母净利率": ("归母净利润", "营业收入"),
    "扣非净利率": ("扣非净利润", "营业收入"),
    "资产负债率": ("负债合计", "资产总计"),
}
META_KEYS = {"报告截止日": "REPORT_DATE", "公告日": "NOTICE_DATE", "币种": "CURRENCY",
             "审计意见": "OPINION_TYPE", "内控审计意见": "INTERNAL_CONTROL_OPINION",
             "境外审计意见": "OSOPINION_TYPE", "审计单位": "AUDITOR"}
# 只补充同义名称，不跨市场映射或用相近科目替代。
ALIASES = {"合并净利润": ["净利润"], "归母净利润": ["归属于母公司股东的净利润"],
           "所有者权益合计": ["股东权益合计"], "经营活动现金流入": ["经营活动现金流入小计"],
           "应收票据及账款": ["应收票据及应收账款"], "应付票据及账款": ["应付票据及应付账款"]}


def validate_financial_request(code, amount_basis, periods, statements, items, top_n=5):
    from datetime import date
    from market_data_mcp.routing import parse_code
    mc = parse_code(code)
    if type(top_n) is not int or not 1 <= top_n <= 99:
        raise ValueError("top_n必须是1—99的整数")
    if amount_basis not in ("cumulative", "single"):
        raise ValueError("amount_basis 必须明确为 cumulative 或 single")
    if statements is not None and (not isinstance(statements, list) or not statements
                                    or any(s not in STATEMENTS for s in statements)):
        raise ValueError(f"statements 必须是 {list(STATEMENTS)} 的非空子集")
    if periods is not None:
        if not isinstance(periods, list) or not periods:
            raise ValueError("periods 必须是非空的 YYYY-MM-DD 数组")
        for period in periods:
            if not isinstance(period, str) or date.fromisoformat(period).isoformat() != period or period > date.today().isoformat():
                raise ValueError("报告期必须是有效且不晚于今天的YYYY-MM-DD")
            if mc.market in ("A", "BJ") and period[5:] not in ("03-31", "06-30", "09-30", "12-31"):
                raise ValueError("A股及北交所报告期必须是季度末")
    if items is not None and (not isinstance(items, list) or not items or any(not isinstance(i, str) or not i.strip() for i in items)):
        raise ValueError("items 必须是非空名称数组；全科目使用ALL_ITEMS")
    return mc
