# -*- coding: utf-8 -*-
"""财报科目中文展示与确定性名称匹配。

映射只收录已通过实际公司财报金额核对的 A 股东财字段；未收录字段返回原名。
港股、美股上游已提供中文名称，不经过本表。

结构：dict[code, [中文全名, *简称]]。第一项为展示与精确匹配的全名，其余是
仅用于 items 请求匹配的简称，不改变返回的 item_name。

收录标准（2026-08-28 全量核对定）：
- 金额与年报合并报表（含现金流量表补充资料）逐项核对一致才收录；行名去掉
  序号前缀（一、/减：/加：/其中：）与填列说明括注后收录核心名；
- 同一报表行的停用重复 code、恒 0 的 *_BALANCE 死字段、语义随公司漂移的
  code 不收录（保留英文原名），如 BEGIN_CCE/END_CASH、DEFER_TAX、
  FBOPERATE_NETCASH_OTHER、FINANCE_INFLOW_OTHER、
  FINANCE_OUTFLOW_OTHER、BORROW_REPO_ADD、LEND_RESALE_ADD、
  OPERATE_INFLOW_OTHER、OPERATE_OUTFLOW_OTHER、IA_LPE_AMORTIZE、
  SUBSIDIARY_ACCEPT_INVEST、OTHER、ABLE_OCI_OTHER、UNABLE_OCI_OTHER；
- 简称与全名重复的唯一例外：CASH_DEPOSIT_PBC（银行模板行名=现金及存放
  中央银行款项、金租模板行名=货币资金），收录为 [现金及存放中央银行款项,
  货币资金]，显示名取银行口径，等价关系随返回 notes 说明；
- 全名重复仅限行业/年代替代 code 对：利息收入（FE_INTEREST_INCOME 与
  INTEREST_INCOME）、信用减值损失（CREDIT_IMPAIRMENT_INCOME 与 _LOSS）、
  资产减值损失（ASSET_IMPAIRMENT_INCOME 与 _LOSS），四家样本无同公司并存。
核验样本：中际旭创 300308.SZ、交通银行 601328.SH、江苏金租 600901.SH、
中信证券 600030.SH 2025 年年度报告（合并口径）。
"""

from __future__ import annotations

A_SHARE_ITEM_NAMES: dict[str, list[str]] = {
    # ---- 利润表（工业格式 + 金融行业行）----
    "TOTAL_OPERATE_INCOME": ["营业总收入", "总收入"],
    "OPERATE_INCOME": ["营业收入", "营收"],
    "OPERATE_COST": ["营业成本"],
    "TOTAL_OPERATE_COST": ["营业总成本"],
    "OPERATE_TAX_ADD": ["税金及附加"],
    "SALE_EXPENSE": ["销售费用"],
    "MANAGE_EXPENSE": ["管理费用"],
    "RESEARCH_EXPENSE": ["研发费用"],
    "FINANCE_EXPENSE": ["财务费用"],
    "FE_INTEREST_EXPENSE": ["利息费用"],
    "FE_INTEREST_INCOME": ["利息收入"],
    "INTEREST_INCOME": ["利息收入"],
    "INTEREST_EXPENSE": ["利息支出"],
    "INTEREST_NI": ["利息净收入"],
    "FEE_COMMISSION_INCOME": ["手续费及佣金收入"],
    "FEE_COMMISSION_EXPENSE": ["手续费及佣金支出"],
    "FEE_COMMISSION_NI": ["手续费及佣金净收入"],
    "AGENT_SECURITY_NI": ["经纪业务手续费净收入"],
    "ASSET_MANAGE_NI": ["资产管理业务手续费净收入"],
    "SECURITY_UNDERWRITE_NI": ["投资银行业务手续费净收入"],
    "BUSINESS_MANAGE_EXPENSE": ["业务及管理费"],
    "OPERATE_EXPENSE": ["营业支出"],
    "OPERATE_EXPENSE_OTHER": ["经营租赁成本"],
    "OPERATE_INCOME_OTHER": ["经营租赁收入"],
    "OTHER_BUSINESS_INCOME": ["其他业务收入"],
    "OTHER_BUSINESS_COST": ["其他业务成本"],
    "INVEST_INCOME": ["投资收益"],
    "INVEST_JOINT_INCOME": ["对联营企业和合营企业的投资收益"],
    "ASSET_DISPOSAL_INCOME": ["资产处置收益"],
    "OTHER_INCOME": ["其他收益"],
    "NONBUSINESS_INCOME": ["营业外收入"],
    "NONBUSINESS_EXPENSE": ["营业外支出"],
    "FAIRVALUE_CHANGE_INCOME": ["公允价值变动收益"],
    "CREDIT_IMPAIRMENT_INCOME": ["信用减值损失"],
    "CREDIT_IMPAIRMENT_LOSS": ["信用减值损失"],
    "ASSET_IMPAIRMENT_INCOME": ["资产减值损失"],
    "ASSET_IMPAIRMENT_LOSS": ["资产减值损失"],
    "OTHER_COMPRE_INCOME": ["其他综合收益的税后净额", "其他综合收益"],
    "ABLE_OCI": ["将重分类进损益的其他综合收益"],
    "UNABLE_OCI": ["不能重分类进损益的其他综合收益"],
    "RIGHTLAW_ABLE_OCI": ["权益法下可转损益的其他综合收益"],
    "RIGHTLAW_UNABLE_OCI": ["权益法下不能转损益的其他综合收益"],
    "CREDITOR_FAIRVALUE_CHANGE": ["其他债权投资公允价值变动"],
    "CREDITOR_IMPAIRMENT_RESERVE": ["其他债权投资信用损失准备"],
    "CREDITRISK_FAIRVALUE_CHANGE": ["企业自身信用风险公允价值变动"],
    "OTHERRIGHT_FAIRVALUE_CHANGE": ["其他权益工具投资公允价值变动"],
    "CASHFLOW_HEDGE_VALID": ["现金流量套期储备"],
    "SETUP_PROFIT_CHANGE": ["重新计量设定受益计划变动额"],
    "CONVERT_DIFF": ["外币财务报表折算差额"],
    "ACF_END_INCOME": ["以摊余成本计量的金融资产终止确认产生的收益"],
    "MINORITY_INTEREST": ["少数股东损益"],
    "PARENT_NETPROFIT": ["归属于母公司股东的净利润", "归母净利润", "归属母公司的净利润"],
    "DEDUCT_PARENT_NETPROFIT": [
        "归属于母公司股东的扣除非经常性损益的净利润",
        "扣非净利润",
        "扣非归母净利润",
    ],
    "NETPROFIT": ["净利润"],
    "CONTINUED_NETPROFIT": ["持续经营净利润"],
    "MINORITY_OCI": ["归属于少数股东的其他综合收益的税后净额"],
    "MINORITY_TCI": ["归属于少数股东的综合收益总额"],
    "PARENT_OCI": ["归属于母公司股东的其他综合收益的税后净额"],
    "PARENT_TCI": ["归属于母公司股东的综合收益总额"],
    "TOTAL_COMPRE_INCOME": ["综合收益总额"],
    "BASIC_EPS": ["基本每股收益", "基本EPS"],
    "DILUTED_EPS": ["稀释每股收益", "稀释EPS"],
    "EXCHANGE_INCOME": ["汇兑收益"],
    "OPERATE_PROFIT": ["营业利润"],
    "TOTAL_PROFIT": ["利润总额"],
    "INCOME_TAX": ["所得税费用"],
    # ---- 资产负债表 ----
    "MONETARYFUNDS": ["货币资金"],
    "TRADE_FINASSET_NOTFVTPL": ["交易性金融资产"],
    "NOTE_RECE": ["应收票据"],
    "ACCOUNTS_RECE": ["应收账款"],
    "FINANCE_RECE": ["应收款项融资"],
    "PREPAYMENT": ["预付款项"],
    "TOTAL_OTHER_RECE": ["其他应收款"],
    "INVENTORY": ["存货"],
    "FIXED_ASSET": ["固定资产"],
    "CIP": ["在建工程"],
    "INTANGIBLE_ASSET": ["无形资产"],
    "DEVELOP_EXPENSE": ["开发支出"],
    "GOODWILL": ["商誉"],
    "SHORT_LOAN": ["短期借款"],
    "NOTE_PAYABLE": ["应付票据"],
    "ACCOUNTS_PAYABLE": ["应付账款"],
    "CONTRACT_LIAB": ["合同负债"],
    "CAPITAL_RESERVE": ["资本公积"],
    "TREASURY_SHARES": ["库存股"],
    "DEFER_INCOME": ["递延收益"],
    "DEFER_TAX_ASSET": ["递延所得税资产"],
    "DEFER_TAX_LIAB": ["递延所得税负债"],
    "LEASE_LIAB": ["租赁负债"],
    "USERIGHT_ASSET": ["使用权资产"],
    "LONG_EQUITY_INVEST": ["长期股权投资"],
    "LONG_LOAN": ["长期借款"],
    "LONG_PAYABLE": ["长期应付款"],
    "LONG_PREPAID_EXPENSE": ["长期待摊费用"],
    "NONCURRENT_LIAB_1YEAR": ["一年内到期的非流动负债"],
    "OTHER_CURRENT_ASSET": ["其他流动资产"],
    "OTHER_CURRENT_LIAB": ["其他流动负债"],
    "OTHER_NONCURRENT_ASSET": ["其他非流动资产"],
    "OTHER_NONCURRENT_FINASSET": ["其他非流动金融资产"],
    "OTHER_NONCURRENT_LIAB": ["其他非流动负债"],
    "SPECIAL_RESERVE": ["专项储备"],
    "SURPLUS_RESERVE": ["盈余公积"],
    "STAFF_SALARY_PAYABLE": ["应付职工薪酬"],
    "TAX_PAYABLE": ["应交税费"],
    "SHARE_CAPITAL": ["股本"],
    "UNASSIGN_RPOFIT": ["未分配利润"],
    "GENERAL_RISK_RESERVE": ["一般风险准备"],
    "MINORITY_EQUITY": ["少数股东权益"],
    "TOTAL_PARENT_EQUITY": ["归属于母公司股东权益合计"],
    "TOTAL_EQUITY": ["股东权益合计"],
    "TOTAL_LIABILITIES": ["负债合计"],
    "TOTAL_LIAB_EQUITY": ["负债和股东权益总计"],
    "TOTAL_ASSETS": ["资产总计"],
    "TOTAL_CURRENT_ASSETS": ["流动资产合计"],
    "TOTAL_NONCURRENT_ASSETS": ["非流动资产合计"],
    "TOTAL_CURRENT_LIAB": ["流动负债合计"],
    "TOTAL_NONCURRENT_LIAB": ["非流动负债合计"],
    "INTEREST_PAYABLE": ["应付利息"],
    "PREDICT_LIAB": ["预计负债"],
    "INVEST_REALESTATE": ["投资性房地产"],
    "OTHER_ASSET": ["其他资产"],
    "OTHER_LIAB": ["其他负债"],
    "DERIVE_FINASSET": ["衍生金融资产"],
    "DERIVE_FINLIAB": ["衍生金融负债"],
    "BOND_PAYABLE": ["应付债券"],
    "BORROW_FUND": ["拆入资金"],
    "LEND_FUND": ["拆出资金"],
    "BUY_RESALE_FINASSET": ["买入返售金融资产"],
    "SELL_REPO_FINASSET": ["卖出回购金融资产款"],
    "DEPOSIT_INTERBANK": ["存放同业款项"],
    "IOFI_DEPOSIT": ["同业及其他金融机构存放款项"],
    "LOAN_ADVANCE": ["发放贷款和垫款"],
    "LOAN_PBC": ["向中央银行借款"],
    "ACCEPT_DEPOSIT": ["客户存款"],
    "DEPOSIT_CERTIFICATE": ["已发行存款证"],
    "AMORTIZE_COST_FINASSET": ["以摊余成本计量的金融投资"],
    "FVTOCI_FINASSET": ["以公允价值计量且其变动计入其他综合收益的金融投资"],
    "FVTPL_FINASSET": ["以公允价值计量且其变动计入当期损益的金融投资"],
    "FVTPL_FINLIAB": ["以公允价值计量且其变动计入当期损益的金融负债"],
    "OTHER_CREDITOR_INVEST": ["其他债权投资"],
    "OTHER_EQUITY_INVEST": ["其他权益工具投资"],
    "SETTLE_EXCESS_RESERVE": ["结算备付金"],
    "AGENT_TRADE_SECURITY": ["代理买卖证券款"],
    "FIN_FUND": ["融出资金"],
    "REFUND_DEPOSIT_PAY": ["存出保证金"],
    "CUSTOMER_DEPOSIT": ["客户资金存款"],
    "CUSTOMER_EXCESS_RESERVE": ["客户备付金"],
    "SHORT_FIN_PAYABLE": ["应付短期融资款"],
    "RECEIVABLES": ["应收款项"],
    "TRADE_FINLIAB_NOTFVTPL": ["交易性金融负债"],
    "OTHER_EQUITY_TOOL": ["其他权益工具"],
    "PERPETUAL_BOND": ["永续债"],
    "PREFERRED_SHARES": ["优先股"],
    "CASH_DEPOSIT_PBC": ["现金及存放中央银行款项", "货币资金"],
    # ---- 现金流量表（主表 + 补充资料）----
    "NETCASH_OPERATE": ["经营活动产生的现金流量净额", "经营现金流净额"],
    "NETCASH_INVEST": ["投资活动产生的现金流量净额", "投资现金流净额"],
    "NETCASH_FINANCE": ["筹资活动产生的现金流量净额", "筹资现金流净额"],
    "SALES_SERVICES": ["销售商品、提供劳务收到的现金"],
    "RECEIVE_TAX_REFUND": ["收到的税费返还"],
    "RECEIVE_OTHER_OPERATE": ["收到其他与经营活动有关的现金"],
    "BUY_SERVICES": ["购买商品、接受劳务支付的现金"],
    "PAY_STAFF_CASH": ["支付给职工以及为职工支付的现金"],
    "PAY_ALL_TAX": ["支付的各项税费"],
    "PAY_OTHER_OPERATE": ["支付其他与经营活动有关的现金"],
    "CONSTRUCT_LONG_ASSET": ["购建固定资产、无形资产和其他长期资产支付的现金"],
    "DISPOSAL_LONG_ASSET": ["处置固定资产、无形资产和其他长期资产收回的现金净额"],
    "DISPOSAL_SUBSIDIARY_OTHER": ["处置子公司及其他营业单位收到的现金净额"],
    "OBTAIN_SUBSIDIARY_OTHER": ["取得子公司及其他营业单位支付的现金净额"],
    "RECEIVE_INVEST_INCOME": ["取得投资收益收到的现金"],
    "WITHDRAW_INVEST": ["收回投资收到的现金"],
    "INVEST_PAY_CASH": ["投资支付的现金"],
    "RECEIVE_OTHER_INVEST": ["收到其他与投资活动有关的现金"],
    "PAY_OTHER_INVEST": ["支付其他与投资活动有关的现金"],
    "RECEIVE_LOAN_CASH": ["取得借款收到的现金"],
    "ISSUE_BOND": ["发行债券收到的现金"],
    "PAY_DEBT_CASH": ["偿还债务支付的现金"],
    "PAY_OTHER_FINANCE": ["支付其他与筹资活动有关的现金"],
    "ACCEPT_INVEST_CASH": ["吸收投资收到的现金"],
    "ASSIGN_DIVIDEND_PORFIT": ["分配股利、利润或偿付利息支付的现金"],
    "SUBSIDIARY_PAY_DIVIDEND": ["子公司支付给少数股东的股利、利润"],
    "RECEIVE_INTEREST_COMMISSION": ["收取利息、手续费及佣金的现金"],
    "PAY_INTEREST_COMMISSION": ["支付利息、手续费及佣金的现金"],
    "RECEIVE_AGENT_TRADE": ["代理买卖证券收到的现金净额"],
    "REPO_BUSINESS_ADD": ["回购业务资金净增加额"],
    "BORROW_FUND_ADD": ["拆入资金净增加额"],
    "BORROW_FUND_REDUCE": ["拆入资金净减少额"],
    "LEND_FUND_ADD": ["拆出资金净增加额"],
    "BUY_RESALE_REDUCE": ["买入返售金融资产净减少额"],
    "SELL_REPO_REDUCE": ["卖出回购金融资产款净减少额"],
    "LOAN_ADVANCE_ADD": ["客户贷款及垫款净增加额"],
    "LOAN_PBC_ADD": ["向中央银行借款净增加额"],
    "PBC_IOFI_REDUCE": ["存放中央银行款项净减少额"],
    "DEPOSIT_IOFI_ADD": ["存放同业款项净增加额"],
    "DEPOSIT_IOFI_OTHER": ["客户存款和同业及其他金融机构存放款项净增加额"],
    "RATE_CHANGE_EFFECT": ["汇率变动对现金及现金等价物的影响"],
    "CCE_ADD": ["现金及现金等价物净增加额"],
    "BEGIN_CASH": ["年初现金及现金等价物余额"],
    "END_CCE": ["期末现金及现金等价物余额"],
    "ASSET_IMPAIRMENT": ["资产减值准备"],
    "FA_IR_DEPR": ["固定资产折旧、油气资产折耗、生产性生物资产折旧"],
    "USERIGHT_ASSET_AMORTIZE": ["使用权资产折旧"],
    "IA_AMORTIZE": ["无形资产摊销"],
    "LPE_AMORTIZE": ["长期待摊费用摊销"],
    "DISPOSAL_LONGASSET_LOSS": ["处置固定资产、无形资产和其他长期资产的损失"],
    "FA_SCRAP_LOSS": ["固定资产报废损失"],
    "FAIRVALUE_CHANGE_LOSS": ["公允价值变动损失"],
    "EXCHANGE_LOSS": ["汇兑损失"],
    "INVEST_LOSS": ["投资损失"],
    "DT_ASSET_REDUCE": ["递延所得税资产减少"],
    "DT_LIAB_ADD": ["递延所得税负债增加"],
    "INVENTORY_REDUCE": ["存货的减少"],
    "OPERATE_RECE_REDUCE": ["经营性应收项目的减少"],
    "OPERATE_PAYABLE_ADD": ["经营性应付项目的增加"],
    "BOND_INTEREST_EXPENSE": ["债券利息支出"],
}


def display_name(market: str, item_code: object, source_name: object) -> str:
    """有可靠中文名则只返回中文全名；无映射时保留上游原名。"""
    code = str(item_code or "")
    name = str(source_name or code)
    if market in ("A", "BJ"):
        names = A_SHARE_ITEM_NAMES.get(code)
        return names[0] if names else name
    return name


def match_names(market: str, item_code: object, source_name: object) -> list[str]:
    """items 请求可匹配的全部名称：[中文全名, *简称]；未映射时为 [原名]。"""
    code = str(item_code or "")
    name = str(source_name or code)
    if market in ("A", "BJ"):
        names = A_SHARE_ITEM_NAMES.get(code)
        return list(names) if names else [name]
    return [name]
