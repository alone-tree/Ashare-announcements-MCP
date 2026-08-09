# -*- coding: utf-8 -*-
"""财报科目中文展示与确定性名称匹配。

映射只收录已通过实际公司财报金额核对的 A 股东财字段；未收录字段返回原名。
港股、美股上游已提供中文名称，不经过本表。
"""

from __future__ import annotations

# 核验样本：中际旭创（300308.SZ）2024 年财务决算报告/年度报告与东财利润表。
# 2024-12-31 金额逐项一致：营业（总）收入、营业利润、利润总额、净利润、
# 归母净利润、扣非归母净利润、基本每股收益。
A_SHARE_ITEM_NAMES: dict[str, str] = {
    # 利润表：中际旭创 2024 年财务决算报告/年度报告逐项核对。
    "TOTAL_OPERATE_INCOME": "营业总收入",
    "OPERATE_INCOME": "营业收入",
    "OPERATE_PROFIT": "营业利润",
    "TOTAL_PROFIT": "利润总额",
    "NETPROFIT": "净利润",
    "PARENT_NETPROFIT": "归属于母公司股东的净利润",
    "DEDUCT_PARENT_NETPROFIT": "归属于母公司股东的扣除非经常性损益的净利润",
    "BASIC_EPS": "基本每股收益",
    # 资产负债表：同一报告 2024-12-31 金额反查东财列，以下均为唯一数值匹配。
    "MONETARYFUNDS": "货币资金",
    "TRADE_FINASSET_NOTFVTPL": "交易性金融资产",
    "NOTE_RECE": "应收票据",
    "ACCOUNTS_RECE": "应收账款",
    "FINANCE_RECE": "应收款项融资",
    "PREPAYMENT": "预付款项",
    "TOTAL_OTHER_RECE": "其他应收款",
    "INVENTORY": "存货",
    "FIXED_ASSET": "固定资产",
    "CIP": "在建工程",
    "INTANGIBLE_ASSET": "无形资产",
    "DEVELOP_EXPENSE": "开发支出",
    "GOODWILL": "商誉",
    "SHORT_LOAN": "短期借款",
    "NOTE_PAYABLE": "应付票据",
    "ACCOUNTS_PAYABLE": "应付账款",
    "CONTRACT_LIAB": "合同负债",
    "CAPITAL_RESERVE": "资本公积",
    "TREASURY_SHARES": "库存股",
}


def display_name(market: str, item_code: object, source_name: object) -> str:
    """有可靠中文名则只返回中文；无映射时保留上游原名。"""
    code = str(item_code or "")
    name = str(source_name or code)
    if market in ("A", "BJ"):
        return A_SHARE_ITEM_NAMES.get(code, name)
    return name
