# iFinD 财务报表科目对照清单

> **用途**：iFinD 三表科目中文名与变量名的对照工作表（2026-10-19 财报科目扩全）。已按编辑器清单定稿（资产负债表 133/利润表 83/现金流量表 110 + 报表信息 meta 4），注册表（`src/market_data_mcp/financial_subjects.py`）已重建为 **330 科目**（2026-10-19，§6 拍板全闭环+报表信息独立成表）。
> **公式存档**：资产负债表原始 THS_BD 公式（逐字符校验）在《字段与数据源支持情况.md》§7；本文只维护对照表，公式以彼处为准，不重复存档。
> **列说明**：科目列=注册表现有名（Excel 模板行名，序号前缀已剥、个别带「其中：」「减：」前缀）；三表均为接口编辑器清单口径（2026-10-19 定稿），利润表不含报表信息行（3 条信息行归 §3.1 的 meta）。

## 1. 一般企业资产负债表（133 项，接口编辑器 2026-10-19，定稿）

| 报表 | 科目 | ifind变量名 | 备注 |
|---|---|---|---|
| 资产负债表-流动资产 | 货币资金 | ths_currency_fund_stock |  |
| 资产负债表-流动资产 | 结算备付金 | ths_settle_reserves_stock |  |
| 资产负债表-流动资产 | 拆出资金 | ths_lending_fund_stock |  |
| 资产负债表-流动资产 | 交易性金融资产 | ths_tradable_fnncl_assets_stock |  |
| 资产负债表-流动资产 | 衍生金融资产 | ths_derivative_fnncl_assets_stock |  |
| 资产负债表-流动资产 | 其中：应收票据 | ths_bill_receivable_stock |  |
| 资产负债表-流动资产 | 应收账款 | ths_account_receivable_stock |  |
| 资产负债表-流动资产 | 应收票据及应收账款 | ths_bill_and_account_receivable_stock |  |
| 资产负债表-流动资产 | 应收款项融资 | ths_receivable_financing_stock |  |
| 资产负债表-流动资产 | 预付款项 | ths_prepays_stock |  |
| 资产负债表-流动资产 | 应收保费 | ths_premium_receivable_stock |  |
| 资产负债表-流动资产 | 应收分保账款 | ths_rein_account_receivable_stock |  |
| 资产负债表-流动资产 | 应收分保合同准备金 | ths_rein_contract_reserve_stock |  |
| 资产负债表-流动资产 | 其中：应收利息 | ths_interest_receivable_stock |  |
| 资产负债表-流动资产 | 应收股利 | ths_dividend_receivable_stock |  |
| 资产负债表-流动资产 | 其他应收款 | ths_other_receivables_stock |  |
| 资产负债表-流动资产 | 其他应收款合计 | ths_other_receivables_sum_stock |  |
| 资产负债表-流动资产 | 买入返售金融资产 | ths_buy_resale_fnncl_assets_stock |  |
| 资产负债表-流动资产 | 存货 | ths_inventory_stock |  |
| 资产负债表-流动资产 | 存货：数据资源 | ths_inventory_data_assets_stock | 2026-10-19 编辑器确认 |
| 资产负债表-流动资产 | 合同资产 | ths_contract_asset_stock |  |
| 资产负债表-流动资产 | 持有待售资产 | ths_divided_into_asset_for_sale_stock |  |
| 资产负债表-流动资产 | 一年内到期的非流动资产 | ths_noncurrent_asset_due_within1y_stock |  |
| 资产负债表-流动资产 | 其他流动资产 | ths_other_cunrren_assets_stock |  |
| 资产负债表-流动资产 | 流动资产差额(特殊报表科目) | ths_flow_assets_diff_sri_stock |  |
| 资产负债表-流动资产 | 流动资产差额(合计平衡科目) | ths_flow_assets_diff_tbi_stock |  |
| 资产负债表-流动资产 | 流动资产合计 | ths_total_current_assets_stock |  |
| 资产负债表-非流动资产 | 发放贷款及垫款 | ths_loans_and_payments_stock |  |
| 资产负债表-非流动资产 | 可供出售金融资产 | ths_saleable_finacial_assets_stock |  |
| 资产负债表-非流动资产 | 持有至到期投资 | ths_held_to_maturity_invest_stock |  |
| 资产负债表-非流动资产 | 债权投资 | ths_debt_right_invest_stock |  |
| 资产负债表-非流动资产 | 其他债权投资 | ths_other_debt_right_invest_stock |  |
| 资产负债表-非流动资产 | 长期应收款 | ths_lt_receivable_stock |  |
| 资产负债表-非流动资产 | 长期股权投资 | ths_lt_equity_invest_stock |  |
| 资产负债表-非流动资产 | 其他权益工具投资 | ths_other_ei_invest_stock |  |
| 资产负债表-非流动资产 | 其他非流动金融资产 | ths_other_uncurrent_fa_stock |  |
| 资产负债表-非流动资产 | 投资性房地产 | ths_invest_property_stock |  |
| 资产负债表-非流动资产 | 其中：固定资产 | ths_fixed_asset_stock |  |
| 资产负债表-非流动资产 | 固定资产清理 | ths_fixed_assets_disposal_stock |  |
| 资产负债表-非流动资产 | 固定资产合计 | ths_fixed_asset_sum_stock |  |
| 资产负债表-非流动资产 | 其中：在建工程 | ths_construction_in_process_stock |  |
| 资产负债表-非流动资产 | 工程物资 | ths_project_goods_and_material_stock |  |
| 资产负债表-非流动资产 | 在建工程合计 | ths_construction_in_process_sum_stock |  |
| 资产负债表-非流动资产 | 生产性生物资产 | ths_productive_biological_assets_stock |  |
| 资产负债表-非流动资产 | 油气资产 | ths_oil_and_gas_asset_stock |  |
| 资产负债表-非流动资产 | 使用权资产 | ths_right_of_use_assets_stock |  |
| 资产负债表-非流动资产 | 无形资产 | ths_intangible_assets_stock |  |
| 资产负债表-非流动资产 | 无形资产：数据资源 | ths_intangible_asset_data_assets_stock | 2026-10-19 编辑器确认 |
| 资产负债表-非流动资产 | 开发支出 | ths_dev_expenditure_stock |  |
| 资产负债表-非流动资产 | 开发支出：数据资源 | ths_dev_expenditure_data_assets_stock | 2026-10-19 编辑器确认 |
| 资产负债表-非流动资产 | 商誉 | ths_goodwill_stock |  |
| 资产负债表-非流动资产 | 长期待摊费用 | ths_lt_deferred_expense_stock |  |
| 资产负债表-非流动资产 | 递延所得税资产 | ths_dt_assets_stock |  |
| 资产负债表-非流动资产 | 其他非流动资产 | ths_othr_noncurrent_assets_stock |  |
| 资产负债表-非流动资产 | 非流动资产差额(特殊报表科目) | ths_noncurrent_assets_diff_sri_stock |  |
| 资产负债表-非流动资产 | 非流动资产差额(合计平衡科目) | ths_noncurrent_assets_diff_tbi_stock |  |
| 资产负债表-非流动资产 | 非流动资产合计 | ths_total_noncurrent_assets_stock |  |
| 资产负债表-非流动资产 | 资产差额(特殊报表科目) | ths_asset_diff_sri_stock |  |
| 资产负债表-非流动资产 | 资产差额(合计平衡科目) | ths_asset_diff_tbi_stock |  |
| 资产负债表-非流动资产 | 资产总计 | ths_total_assets_stock |  |
| 资产负债表-流动负债 | 短期借款 | ths_st_borrow_stock |  |
| 资产负债表-流动负债 | 向中央银行借款 | ths_loan_from_central_bank_stock |  |
| 资产负债表-流动负债 | 吸收存款及同业存放 | ths_saving_and_interbank_deposit_stock |  |
| 资产负债表-流动负债 | 拆入资金 | ths_borrowing_funds_stock |  |
| 资产负债表-流动负债 | 交易性金融负债 | ths_tradable_fnncl_liab_stock |  |
| 资产负债表-流动负债 | 衍生金融负债 | ths_derivative_fnncl_liab_stock |  |
| 资产负债表-流动负债 | 其中：应付票据 | ths_bill_payable_stock |  |
| 资产负债表-流动负债 | 应付账款 | ths_accounts_payable_stock |  |
| 资产负债表-流动负债 | 应付票据及应付账款 | ths_bill_and_account_payable_stock |  |
| 资产负债表-流动负债 | 预收款项 | ths_advance_payment_stock |  |
| 资产负债表-流动负债 | 合同负债 | ths_contract_liab_stock |  |
| 资产负债表-流动负债 | 卖出回购金融资产款 | ths_fnncl_assets_sold_for_repur_stock |  |
| 资产负债表-流动负债 | 应付手续费及佣金 | ths_charge_and_commi_payable_stock |  |
| 资产负债表-流动负债 | 应付职工薪酬 | ths_payroll_payable_stock |  |
| 资产负债表-流动负债 | 应交税费 | ths_tax_payable_stock |  |
| 资产负债表-流动负债 | 其中：应付利息 | ths_interest_payable_stock |  |
| 资产负债表-流动负债 | 应付股利 | ths_dividend_payable_stock |  |
| 资产负债表-流动负债 | 其他应付款 | ths_other_payables_stock |  |
| 资产负债表-流动负债 | 其他应付款合计 | ths_other_payables_sum_stock |  |
| 资产负债表-流动负债 | 应付分保账款 | ths_rein_payable_stock |  |
| 资产负债表-流动负债 | 保险合同准备金 | ths_insurance_contract_reserve_stock |  |
| 资产负债表-流动负债 | 代理买卖证券款 | ths_acting_td_sec_stock |  |
| 资产负债表-流动负债 | 代理承销证券款 | ths_act_underwriting_sec_stock |  |
| 资产负债表-流动负债 | 持有待售负债 | ths_divided_into_liab_for_sale_stock |  |
| 资产负债表-流动负债 | 一年内到期的非流动负债 | ths_noncurrent_liab_due_in1y_stock |  |
| 资产负债表-流动负债 | 递延收益-流动负债 | ths_differed_income_current_liab_stock |  |
| 资产负债表-流动负债 | 应付短期债券 | ths_st_bond_payable_new_stock | 2026-10-19 编辑器确认；替代旧码 ths_st_bond_payable_stock（已拍板不保留） |
| 资产负债表-流动负债 | 其他流动负债 | ths_other_current_liab_stock |  |
| 资产负债表-流动负债 | 流动负债差额(特殊报表科目) | ths_flow_debt_diff_sri_stock |  |
| 资产负债表-流动负债 | 流动负债差额(合计平衡科目) | ths_flow_debt_diff_tbi_stock |  |
| 资产负债表-流动负债 | 流动负债合计 | ths_total_current_liab_stock |  |
| 资产负债表-非流动负债 | 长期借款 | ths_lt_loan_stock |  |
| 资产负债表-非流动负债 | 应付债券 | ths_bond_payable_stock |  |
| 资产负债表-非流动负债 | 永续债 | ths_perpetual_capital_sec_stock |  |
| 资产负债表-非流动负债 | 其中:优先股 | ths_preferred_stock |  |
| 资产负债表-非流动负债 | 租赁负债 | ths_lease_libilities_stock |  |
| 资产负债表-非流动负债 | 其中：长期应付款 | ths_lt_payable_stock |  |
| 资产负债表-非流动负债 | 专项应付款 | ths_special_payable_stock |  |
| 资产负债表-非流动负债 | 长期应付款合计 | ths_lt_payable_sum_stock |  |
| 资产负债表-非流动负债 | 长期应付职工薪酬 | ths_lt_staff_salary_payable_stock |  |
| 资产负债表-非流动负债 | 预计负债 | ths_estimated_liab_stock |  |
| 资产负债表-非流动负债 | 递延所得税负债 | ths_dt_liab_stock |  |
| 资产负债表-非流动负债 | 递延收益-非流动负债 | ths_differed_incomencl_stock |  |
| 资产负债表-非流动负债 | 其他非流动负债 | ths_othr_noncurrent_liab_stock |  |
| 资产负债表-非流动负债 | 非流动负债差额(特殊报表科目) | ths_noncurrent_liab_diff_sri_stock |  |
| 资产负债表-非流动负债 | 非流动负债差额(合计平衡科目) | ths_noncurrent_liab_diff_sbi_stock |  |
| 资产负债表-非流动负债 | 非流动负债合计 | ths_total_noncurrent_liab_stock |  |
| 资产负债表-非流动负债 | 负债差额(特殊报表科目) | ths_liab_diff_sri_stock |  |
| 资产负债表-非流动负债 | 负债差额(合计平衡科目) | ths_liab_diff_tbi_stock |  |
| 资产负债表-非流动负债 | 负债合计 | ths_total_liab_stock |  |
| 资产负债表-所有者权益 | 实收资本 | ths_actual_received_capital_stock |  |
| 资产负债表-所有者权益 | 资本公积 | ths_capital_reserve_stock |  |
| 资产负债表-所有者权益 | 减：库存股 | ths_treasury_stock_stock |  |
| 资产负债表-所有者权益 | 其他综合收益 | ths_bs_other_compre_income_stock |  |
| 资产负债表-所有者权益 | 其他权益工具 | ths_other_equity_instruments_stock |  |
| 资产负债表-所有者权益 | 其中:优先股 | ths_preferred_shares_stock |  |
| 资产负债表-所有者权益 | 永续债 | ths_perpetual_capital_sec_shares_stock |  |
| 资产负债表-所有者权益 | 专项储备 | ths_appropriative_reserve_stock |  |
| 资产负债表-所有者权益 | 盈余公积 | ths_earned_surplus_stock |  |
| 资产负债表-所有者权益 | 一般风险准备 | ths_general_risk_provision_stock |  |
| 资产负债表-所有者权益 | 未分配利润 | ths_undstrbtd_profit_stock |  |
| 资产负债表-所有者权益 | 外币报表折算差额 | ths_frgn_currency_convert_diff_stock |  |
| 资产负债表-所有者权益 | 未确认的投资损失 | unconfirmed_invest_loss_bs | 2026-10-19 编辑器确认 |
| 资产负债表-所有者权益 | 归属于母公司股东权益差额(特殊报表科目) | ths_total_equity_atoopc_diff_spe_stock |  |
| 资产负债表-所有者权益 | 归属于母公司股东权益差额(合计平衡科目) | ths_total_equity_atoopc_diff_sri_stock |  |
| 资产负债表-所有者权益 | 归母所有者权益合计 | ths_total_equity_atoopc_stock |  |
| 资产负债表-所有者权益 | 少数股东权益 | ths_minority_equity_stock |  |
| 资产负债表-所有者权益 | 股东权益差额(特殊报表科目) | ths_holder_equity_diff_sri_stock |  |
| 资产负债表-所有者权益 | 股东权益差额(合计平衡科目) | ths_equity_right_diff_tbi_stock |  |
| 资产负债表-所有者权益 | 所有者权益合计 | ths_total_owner_equity_stock |  |
| 资产负债表-所有者权益 | 负债及股东权益差额(特殊报表科目) | ths_liab_and_equity_diff_sri_stock |  |
| 资产负债表-所有者权益 | 负债及股东权益差额(合计平衡科目) | ths_liab_and_equity_diff_tbi_stock |  |
| 资产负债表-所有者权益 | 负债和所有者权益总计 | ths_total_liab_and_owner_equity_stock |  |

## 2. 利润表（83 项，编辑器清单 2026-10-19 定稿）

> 来源：`0-IPO信息+财报数据 ifind.xlsx` 模板（2026-10-14 提取为 `.codex-temp/statements_subjects_from_template.csv`）。**2026-10-19 接口编辑器利润表清单已到手（82 项，其中序位 1 在建工程合计经确认为误选、忽略，有效 81 项；参数全 `'20250930,100'`，公式存档于字段与数据源支持情况.md §7）**：赔付支出、提取保险合同准备金（非净额）树内存在、全量清单漏勾，均补入；扣非用新分析码 `ths_new_analyse_np_dnrgal_stock`（旧码不保留）；10,现金流量套期储备树内没有、不保留；3 信息行未勾选属预期（维持）。新码中文名全部确认（见下方附表）。**利润表定稿：83 项**（不含 3 条报表信息行，它们归 §3.1 的 meta；含 2 EPS 非加总行；不保留 4 项：在建工程合计误选、营业总成本2、扣非旧码、10,现金流量套期储备）。

| 报表 | 科目 | ifind变量名 | 备注 |
|---|---|---|---|
| 利润表 | 营业总收入 | ths_operating_total_revenue_stock |  |
| 利润表 | 营业收入 | ths_revenue_stock |  |
| 利润表 | 利息收入 | ths_interest_income_stock |  |
| 利润表 | 已赚保费 | ths_earned_premium_stock |  |
| 利润表 | 手续费及佣金收入 | ths_fee_and_commi_income_stock |  |
| 利润表 | 营业总收入差额(特殊报表科目) | ths_operating_revenuediff_sri_stock |  |
| 利润表 | 营业总收入差额(合计平衡科目) | ths_operating_revenuediff_tbi_stock |  |
| 利润表 | 营业总成本 | ths_operating_total_cost_stock | 编辑器清单新码（序位 9），2026-10-19 编辑器确认 |
| 利润表 | 营业总成本2 | ths_operating_cost_2_stock | 模板/注册表旧「营业总成本」码；2026-10-19 拍板忽略不保留 |
| 利润表 | 营业成本 | ths_operating_cost_stock |  |
| 利润表 | 利息支出 | ths_interest_payout_stock |  |
| 利润表 | 手续费及佣金支出 | ths_charge_and_commi_expenses_stock |  |
| 利润表 | 退保金 | ths_refunded_premium_stock |  |
| 利润表 | 赔付支出 | ths_compen_payout_stock | 全量清单漏勾，树内已确认存在（2026-10-19），补入清单 |
| 利润表 | 提取保险合同准备金 | ths_extract_ic_reserve_stock | 树内存在（2026-10-19 公式验证），全量清单漏勾，补入清单 |
| 利润表 | 保单红利支出 | ths_commi_on_insurance_policy_stock |  |
| 利润表 | 分保费用 | ths_rein_expenditure_stock |  |
| 利润表 | 税金及附加 | ths_operating_taxes_and_surcharge_stock |  |
| 利润表 | 销售费用 | ths_sales_fee_stock |  |
| 利润表 | 管理费用 | ths_manage_fee_stock |  |
| 利润表 | 研发费用 | ths_rad_cost_sum_stock |  |
| 利润表 | 财务费用 | ths_financing_expenses_stock |  |
| 利润表 | 其中：利息费用 | ths_finance_cost_interest_fee_stock |  |
| 利润表 | 利息收入 | ths_fc_interest_income_stock |  |
| 利润表 | 营业总成本差额(特殊报表科目) | ths_operating_cost_diff_sri_stock |  |
| 利润表 | 营业总成本差额(合计平衡科目) | ths_operating_cost_diff_tbi_stock |  |
| 利润表 | 公允价值变动收益 | ths_fv_chg_income_stock |  |
| 利润表 | 投资收益 | ths_invest_income_stock |  |
| 利润表 | 其中：对联营企业和合营企业的投资收益 | ths_ii_from_jc_etc_stock |  |
| 利润表 | 以摊余成本计量的金融资产终止确认收益 | ths_amortized_cost_fnncl_ass_cfrm_stock |  |
| 利润表 | 净敞口套期收益 | ths_net_open_hedge_income_stock |  |
| 利润表 | 汇兑收益 | ths_exchange_gain_stock |  |
| 利润表 | 资产处置收益 | ths_asset_disposal_gain_stock |  |
| 利润表 | 资产减值损失(正数为损失) | ths_asset_impairment_loss_stock |  |
| 利润表 | 信用减值损失(正数为损失) | ths_credit_impairment_loss_stock |  |
| 利润表 | 其他收益 | ths_other_income_stock |  |
| 利润表 | 营业利润差额(特殊报表科目) | ths_op_diff_sri_stock |  |
| 利润表 | 营业利润差额(合计平衡科目) | ths_op_diff_tbi_stock |  |
| 利润表 | 营业利润 | ths_op_stock |  |
| 利润表 | 加：营业外收入 | ths_non_operating_income_stock |  |
| 利润表 | 其中：非流动资产处置利得 | ths_noncurrent_asset_dispose_gain_stock |  |
| 利润表 | 减：营业外支出 | ths_nonoperating_cost_stock |  |
| 利润表 | 其中：非流动资产处置损失 | ths_noncurrent_asset_dispose_loss_stock |  |
| 利润表 | 利润总额差额(特殊报表科目) | ths_total_profit_diff_sri_stock |  |
| 利润表 | 利润总额差额(合计平衡科目) | ths_total_profit_diff_tbi_stock |  |
| 利润表 | 利润总额 | ths_total_profit_stock |  |
| 利润表 | 减：所得税费用 | ths_income_tax_cost_stock |  |
| 利润表 | 净利润差额(特殊报表科目) | ths_np_diff_sri_stock |  |
| 利润表 | 净利润差额(合计平衡科目) | ths_np_diff_tbi_stock |  |
| 利润表 | 净利润 | ths_np_stock |  |
| 利润表 | (一)持续经营净利润 | ths_continued_operating_np_stock |  |
| 利润表 | (二)终止经营净利润 | ths_stop_operating_np_stock |  |
| 利润表 | 减：少数股东损益 | ths_minority_gal_stock |  |
| 利润表 | 归母净利润 | ths_np_atoopc_stock |  |
| 利润表 | 扣非净利润 | ths_np_dnrgal_stock | 旧码不保留（2026-10-19 拍板），由下行新分析码替代 |
| 利润表 | 扣除非经常性损益后的归属母公司股东净利润 | ths_new_analyse_np_dnrgal_stock | 编辑器现行码（2026-10-19 用户补生成确认），拟替代旧码 |
| 利润表 | (一) 基本每股收益(元) | ths_basic_eps_stock | 非加总科目（single 差分排除） |
| 利润表 | (二) 稀释每股收益(元) | ths_dlt_earnings_per_share_stock | 非加总科目（single 差分排除） |
| 利润表 | 其他综合收益 | ths_other_compre_income_stock |  |
| 利润表 | 归属母公司所有者的其他综合收益 | ths_othrcompre_income_atoopc_stock |  |
| 利润表 | 以后不能重分类进损益的其他综合收益 | ths_cannt_reclass_to_gal_stock |  |
| 利润表 | 重新计量设定受益计划净负债或净资产的变动 | ths_asset_change_due_to_remeasure_stock |  |
| 利润表 | 权益法下在被投资单位不能重分类进损益的其他综合收益中享有的份额 | ths_cannt_reclass_gal_equity_law_stock |  |
| 利润表 | 其他以后不能重分类进损益 | ths_other_not_reclass_to_gal_stock |  |
| 利润表 | 其他权益工具投资公允价值变动 | ths_other_equity_invest_fvc_stock |  |
| 利润表 | 企业自身信用风险公允价值变动 | ths_corp_credit_risk_fvc_stock |  |
| 利润表 | 以后将重分类进损益的其他综合收益 | ths_reclass_to_gal_stock |  |
| 利润表 | 权益法下在被投资单位以后将重分类进损益的其他综合收益中享有的份额 | ths_reclass_togal_in_equity_law_stock |  |
| 利润表 | 可供出售金融资产公允价值变动损益 | ths_saleable_fv_chg_gal_stock |  |
| 利润表 | 持有至到期投资重分类为可供出售金融资产损益 | ths_reclass_and_salable_gal_stock |  |
| 利润表 | 现金流量套期损益的有效部分 | ths_cf_hedging_gal_valid_part_stock |  |
| 利润表 | 外币财务报表折算差额 | ths_fc_convert_diff_stock |  |
| 利润表 | 其他以后将重分类进损益 | ths_other_reclass_to_gal_stock |  |
| 利润表 | 其他债权投资公允价值变动 | ths_other_debt_right_invest_fvc_stock |  |
| 利润表 | 金融资产重分类计入其他综合收益的金额 | ths_fa_reclassi_amt_stock |  |
| 利润表 | 其他债权投资信用减值准备 | ths_other_debt_right_invest_ir_stock |  |
| 利润表 | 现金流量套期储备 | ths_cash_flow_hedge_reserve_stock | 编辑器树内没有（2026-10-19 确认），不保留 |
| 利润表 | 归属于少数股东的其他综合收益 | ths_othrcompre_income_atms_stock |  |
| 利润表 | 综合收益总额 | ths_total_compre_income_stock |  |
| 利润表 | 归属于母公司股东的综合收益总额 | ths_total_compre_income_atsopc_stock |  |
| 利润表 | 归属于少数股东的综合收益总额 | ths_total_compre_income_atms_stock |  |

**主表未按分组收录的 5 个新码（编辑器序位备查，均属利润表；中文名 2026-10-19 编辑器确认，序位 1 在建工程合计误选已忽略）**：

| 编辑器序位 | ifind变量名 | 中文名 |
|---|---|---|
| 9 | ths_operating_total_cost_stock | 营业总成本 |
| 15 | ths_compensate_net_pay_stock | 赔付支出净额 |
| 16 | ths_extract_ic_reserve_net_amt_stock | 提取保险合同准备金净额 |
| 27 | ths_asset_impairment_loss_publish_stock | 资产减值损失(公布值) |
| 29 | ths_credit_impairment_loss_publish_stock | 信用减值损失(公布值) |
| 50 | unconfirmed_invest_loss_is | 未确认投资损失 |

> 名称注：2026-10-19 拍板 `ths_operating_cost_2_stock`（营业总成本2）不保留，营业总成本以新码 `ths_operating_total_cost_stock` 为准。

## 3. 现金流量表（编辑器清单 110 项 = 模板 105 全含 + 5 新码，2026-10-19；报表列按模板分组）

> 来源同上。**2026-10-19 接口编辑器现金流量表清单已到手（110 项，参数全 `'20250930,100'`，公式存档于字段与数据源支持情况.md §7）**：模板 105 码全部在清单内（无缺失），5 个新码已按编辑器位置插入下表，中文名 2026-10-19 全部确认。
> 分组（编辑器 110 项口径）：经营现金流 33 / 投资现金流 19 / 筹资现金流 18 / 汇率变动与净增加额 6（含期初、期末余额）/ 间接法 34。

| 报表 | 科目 | ifind变量名 | 备注 |
|---|---|---|---|
| 现金流量表-经营现金流 | 销售商品收到现金 | ths_cash_received_of_sales_service_stock |  |
| 现金流量表-经营现金流 | 客户存款和同业存放款项净增加额 | ths_deposit_and_interbank_net_add_stock |  |
| 现金流量表-经营现金流 | 向中央银行借款净增加额 | ths_borrowing_net_add_central_bank_stock |  |
| 现金流量表-经营现金流 | 向其他金融机构拆入资金净增加额 | ths_lending_net_add_other_org_stock |  |
| 现金流量表-经营现金流 | 收到原保险合同保费取得的现金 | ths_cash_received_from_orig_ic_stock |  |
| 现金流量表-经营现金流 | 收到再保业务现金净额 | ths_net_cash_received_from_rein_stock |  |
| 现金流量表-经营现金流 | 保户储金及投资款净增加额 | ths_naaassured_saving_and_invest_stock |  |
| 现金流量表-经营现金流 | 处置以公允价值计量且其变动计入当期损益的金融资产净增加额 | ths_naa_of_disposal_fnncl_assets_stock |  |
| 现金流量表-经营现金流 | 收取利息、手续费及佣金的现金 | ths_cash_received_of_interest_etc_stock |  |
| 现金流量表-经营现金流 | 拆入资金净增加额 | ths_borrowing_net_increase_amt_stock |  |
| 现金流量表-经营现金流 | 回购业务资金净增加额 | ths_net_add_in_repur_capital_stock |  |
| 现金流量表-经营现金流 | 收到的税费返还 | ths_refund_of_tax_and_levies_stock |  |
| 现金流量表-经营现金流 | 收到其他经营活动现金 | ths_cash_received_of_other_oa_stock |  |
| 现金流量表-经营现金流 | 经营活动现金流入差额(特殊报表科目) | ths_oa_cash_inflow_diff_sri_stock |  |
| 现金流量表-经营现金流 | 经营活动现金流入差额(合计平衡科目) | ths_oa_cash_inflow_diff_tbi_stock |  |
| 现金流量表-经营现金流 | 经营活动现金流入 | ths_sub_total_of_ci_from_oa_stock |  |
| 现金流量表-经营现金流 | 购买商品支付现金 | ths_goods_buy_and_service_cash_pay_stock |  |
| 现金流量表-经营现金流 | 客户贷款及垫款净增加额 | ths_loan_and_advancenet_add_stock |  |
| 现金流量表-经营现金流 | 存放中央银行和同业款项净增加额 | ths_naa_of_cb_and_interbank_stock |  |
| 现金流量表-经营现金流 | 支付原保险合同赔付款项的现金 | ths_cash_of_orig_ic_indemnity_stock |  |
| 现金流量表-经营现金流 | 支付利息、手续费及佣金的现金 | ths_cash_paid_for_interests_etc_stock |  |
| 现金流量表-经营现金流 | 支付保单红利的现金 | ths_cash_paid_for_pd_stock |  |
| 现金流量表-经营现金流 | 拆出资金净增加额 | ths_lending_funds_net_increase_stock | 编辑器清单新增（序位 23），2026-10-19 编辑器确认 |
| 现金流量表-经营现金流 | 向其他金融机构拆出资金净增加额 | ths_lend_to_other_finins_net_incre_stock | 编辑器清单新增（序位 24），2026-10-19 编辑器确认 |
| 现金流量表-经营现金流 | 支付给职工的现金 | ths_cash_paid_to_staff_etc_stock |  |
| 现金流量表-经营现金流 | 支付的各项税费 | ths_payments_of_all_taxes_stock |  |
| 现金流量表-经营现金流 | 支付其他经营活动现金 | ths_other_cash_paid_related_to_oa_stock |  |
| 现金流量表-经营现金流 | 经营活动现金流出差额(特殊报表科目) | ths_oa_cash_outflow_diff_sri_stock |  |
| 现金流量表-经营现金流 | 经营活动现金流出差额(合计平衡科目) | ths_oa_cash_outflow_diff_tbi_stock |  |
| 现金流量表-经营现金流 | 经营活动现金流出 | ths_sub_total_of_cos_from_oa_stock |  |
| 现金流量表-经营现金流 | 经营活动产生的现金流量净额差额(特殊报表科目) | ths_ncf_diff_of_oa_sri_stock |  |
| 现金流量表-经营现金流 | 经营活动产生的现金流量净额差额(合计平衡科目) | ths_ncf_diff_of_oa_tbi_stock |  |
| 现金流量表-经营现金流 | 经营活动净现金流 | ths_ncf_from_oa_stock |  |
| 现金流量表-投资现金流 | 收回投资收到现金 | ths_cash_received_of_dspsl_invest_stock |  |
| 现金流量表-投资现金流 | 取得投资收益收到的现金 | ths_invest_income_cash_received_stock |  |
| 现金流量表-投资现金流 | 处置固定资产、无形资产和其他长期资产收回现金 | ths_net_cash_of_disposal_assets_stock |  |
| 现金流量表-投资现金流 | 处置子公司收到现金 | ths_net_cash_of_disposal_branch_stock |  |
| 现金流量表-投资现金流 | 收到其他投资活动现金 | ths_cash_received_of_other_fa_stock |  |
| 现金流量表-投资现金流 | 投资活动现金流入差额(特殊报表科目) | ths_ia_cash_inflow_diff_sri_stock |  |
| 现金流量表-投资现金流 | 投资活动现金流入差额(合计平衡科目) | ths_ia_cash_inflow_diff_tbi_stock |  |
| 现金流量表-投资现金流 | 投资活动现金流入 | ths_sub_total_of_ci_from_ia_stock |  |
| 现金流量表-投资现金流 | 购建固定资产、无形资产和其他长期资产 | ths_cash_paid_for_assets_stock |  |
| 现金流量表-投资现金流 | 投资支付的现金 | ths_invest_paid_cash_stock |  |
| 现金流量表-投资现金流 | 质押贷款净增加额 | ths_net_add_in_pledge_loans_stock |  |
| 现金流量表-投资现金流 | 取得子公司支付现金 | ths_net_cash_amt_from_branch_stock |  |
| 现金流量表-投资现金流 | 支付其他投资活动现金 | ths_other_cash_paid_related_to_ia_stock |  |
| 现金流量表-投资现金流 | 投资活动现金流出差额(特殊报表科目) | ths_ia_cash_outflow_diff_sri_stock |  |
| 现金流量表-投资现金流 | 投资活动现金流出差额(合计平衡科目) | ths_ia_cash_outflow_diff_tbi_stock |  |
| 现金流量表-投资现金流 | 投资活动现金流出 | ths_sub_total_of_cos_from_ia_stock |  |
| 现金流量表-投资现金流 | 投资活动产生的现金流量净额差额(特殊报表科目) | ths_ncf_diff_from_ia_sri_stock |  |
| 现金流量表-投资现金流 | 投资活动产生的现金流量净额差额(合计平衡科目) | ths_ncf_diff_from_ia_tbi_stock |  |
| 现金流量表-投资现金流 | 投资活动净现金流 | ths_ncf_from_ia_stock |  |
| 现金流量表-筹资现金流 | 吸收投资收到现金 | ths_cash_received_of_absorb_invest_stock |  |
| 现金流量表-筹资现金流 | 其中：子公司吸收少数股东投资收到的现金 | ths_cr_from_minority_holders_stock |  |
| 现金流量表-筹资现金流 | 取得借款收到的现金 | ths_cash_received_of_borrowing_stock |  |
| 现金流量表-筹资现金流 | 收到其他与筹资活动有关的现金 | ths_cash_received_of_othr_fa_stock |  |
| 现金流量表-筹资现金流 | 发行债券收到的现金 | ths_cash_received_from_bond_issue_stock |  |
| 现金流量表-筹资现金流 | 筹资活动现金流入差额(特殊报表科目) | ths_fa_cash_in_flow_diff_sri_stock |  |
| 现金流量表-筹资现金流 | 筹资活动现金流入差额(合计平衡科目) | ths_fa_cash_in_flow_diff_tbi_stock |  |
| 现金流量表-筹资现金流 | 筹资活动现金流入 | ths_sub_total_of_ci_from_fa_stock |  |
| 现金流量表-筹资现金流 | 偿还债务支付的现金 | ths_cash_pay_for_debt_stock |  |
| 现金流量表-筹资现金流 | 分配股利或偿付利息 | ths_cash_paid_of_distribution_stock |  |
| 现金流量表-筹资现金流 | 其中：子公司支付给少数股东的股利、利润 | ths_dap_paid_to_minority_holder_stock |  |
| 现金流量表-筹资现金流 | 支付其他筹资活动现金 | ths_othrcash_paid_relating_to_fa_stock |  |
| 现金流量表-筹资现金流 | 筹资活动现金流出差额(特殊报表科目) | ths_fa_cash_out_flow_diff_sri_stock |  |
| 现金流量表-筹资现金流 | 筹资活动现金流出差额(合计平衡科目) | ths_fa_cash_out_flow_diff_tbi_stock |  |
| 现金流量表-筹资现金流 | 筹资活动现金流出 | ths_sub_total_of_cos_from_fa_stock |  |
| 现金流量表-筹资现金流 | 筹资活动产生的现金流量净额差额(特殊报表科目) | ths_ncf_diff_from_fa_sri_stock |  |
| 现金流量表-筹资现金流 | 筹资活动产生的现金流量净额差额(合计平衡科目) | ths_ncf_diff_from_fa_tbi_stock |  |
| 现金流量表-筹资现金流 | 筹资活动净现金流 | ths_ncf_from_fa_stock |  |
| 现金流量表-汇率变动与净增加额 | 汇率变动影响 | ths_effect_of_exchange_chg_on_cce_stock |  |
| 现金流量表-汇率变动与净增加额 | 直接法-现金及现金等价物净增加额差额(特殊报表科目) | ths_cce_net_add_amt_diff_sri_dm_stock |  |
| 现金流量表-汇率变动与净增加额 | 直接法-现金及现金等价物净增加额差额(合计平衡科目) | ths_cce_net_add_amt_diff_tbi_dm_stock |  |
| 现金流量表-汇率变动与净增加额 | 现金等价物净增加额 | ths_net_increase_in_cce_stock |  |
| 现金流量表-汇率变动与净增加额 | 期初现金等价物余额 | ths_initial_cce_balance_stock |  |
| 现金流量表-汇率变动与净增加额 | 期末现金等价物余额 | ths_final_balance_of_cce_stock |  |
| 现金流量表-间接法 | 现金流量表-净利润 | ths_np_cfs_stock |  |
| 现金流量表-间接法 | 加：资产减值准备 | ths_asset_impairment_reserve_stock |  |
| 现金流量表-间接法 | 信用减值损失 | ths_credit_impairment_loss2_stock |  |
| 现金流量表-间接法 | 固定资产折旧、油气资产折耗、生产性生物资产折旧 | ths_depreciation_etc_stock |  |
| 现金流量表-间接法 | 投资性房地产折旧 | ths_depreciation_ire_stock | 编辑器清单新增（序位 82），2026-10-19 编辑器确认 |
| 现金流量表-间接法 | 无形资产摊销 | ths_intangible_assets_amortized_stock |  |
| 现金流量表-间接法 | 长期待摊费用摊销 | ths_lt_deferred_expenses_amrtzt_stock |  |
| 现金流量表-间接法 | 待摊费用减少 | ths_deferred_expense_reduce_stock | 编辑器清单新增（序位 85），2026-10-19 编辑器确认 |
| 现金流量表-间接法 | 预提费用增加 | ths_increase_in_accrued_expenses_stock | 编辑器清单新增（序位 86），2026-10-19 编辑器确认 |
| 现金流量表-间接法 | 处置固定资产、无形资产和其他长期资产的损失 | ths_loss_of_disposal_assets_stock |  |
| 现金流量表-间接法 | 使用权资产折旧 | ths_rou_depreciation_stock |  |
| 现金流量表-间接法 | 固定资产报废损失 | ths_fixed_assets_scrap_loss_stock |  |
| 现金流量表-间接法 | 公允价值变动损失 | ths_loss_from_fv_chg_stock |  |
| 现金流量表-间接法 | 现金流量表-财务费用 | ths_finance_cost_cfs_stock |  |
| 现金流量表-间接法 | 投资损失 | ths_invest_loss_stock |  |
| 现金流量表-间接法 | 递延所得税资产减少 | ths_dt_assets_decrease_stock |  |
| 现金流量表-间接法 | 递延所得税负债增加 | ths_dt_liab_increase_stock |  |
| 现金流量表-间接法 | 存货的减少 | ths_inventory_decrease_stock |  |
| 现金流量表-间接法 | 经营性应收项目的减少 | ths_operating_items_decrease_stock |  |
| 现金流量表-间接法 | 经营性应付项目的增加 | ths_increase_of_operating_item_stock |  |
| 现金流量表-间接法 | 其他 | ths_si_other_stock |  |
| 现金流量表-间接法 | 间接法-经营活动现金流量净额差额(特殊报表科目) | ths_ncf_diff_from_oa_im_sri_stock |  |
| 现金流量表-间接法 | 间接法-经营活动现金流量净额差额(合计平衡科目) | ths_ncf_diff_from_oa_im_tbi_stock |  |
| 现金流量表-间接法 | 间接法-经营活动产生的现金流量净额 | ths_ncf_from_oa_im_stock |  |
| 现金流量表-间接法 | 债务转为资本 | ths_debt_tranfer_to_capital_stock |  |
| 现金流量表-间接法 | 一年内到期的可转换公司债券 | ths_cb_due_within1y_stock |  |
| 现金流量表-间接法 | 融资租入固定资产 | ths_finance_lease_fixed_assets_stock |  |
| 现金流量表-间接法 | 现金的期末余额 | ths_ending_balance_of_cash_stock |  |
| 现金流量表-间接法 | 减：现金的期初余额 | ths_initial_balance_of_cash_stock |  |
| 现金流量表-间接法 | 加：现金等价物的期末余额 | ths_si_final_balance_of_cce_stock |  |
| 现金流量表-间接法 | 减：现金等价物的期初余额 | ths_initial_balance_of_cce_stock |  |
| 现金流量表-间接法 | 间接法-现金及现金等价物净增加额差额(特殊报表科目) | ths_cce_net_add_diff_im_sri_stock |  |
| 现金流量表-间接法 | 间接法-现金及现金等价物净增加额差额(合计平衡科目) | ths_cce_net_add_diff_im_tbi_stock |  |
| 现金流量表-间接法 | 间接法-现金及现金等价物净增加额 | ths_net_increase_in_cce_im_stock |  |

## 3.1 报表信息（meta，独立于三表，4 项，2026-10-19）

| 报表 | 科目 | ifind变量名 | 备注 |
|---|---|---|---|
| 报表信息 | 审计单位 | ths_audit_institution_stock | 用户编辑器公式补入；文本值 |
| 报表信息 | 审计意见类型 | ths_audit_opinion_type_stock | iFinD 实测恒空，单独请求 -209 |
| 报表信息 | 内控审计意见类型 | ths_ica_opinion_type_stock | iFinD 实测恒空，单独请求 -209 |
| 报表信息 | 定期报告实际披露日期 | ths_regular_report_actual_dd_stock | 批量请求正常；写入缓存 metadata.NOTICE_DATE |

用户拍板：4 码为额外元信息，独立成第 4 张表（statement=meta），不混三表；顺序=用户公式序。
（原利润表模板行 88-90 的 3 个信息行已从利润表移出；历史注：模板/注册表占位名「有数据」已改编辑器名。）

## 4. 反向差异：注册表有、2026-10-19 资产负债表清单没有（3 项，2026-10-19 拍板：不保留）

| 报表 | 科目 | ifind变量名 | 处置 |
|---|---|---|---|
| 资产负债表-非流动资产 | 以公允价值计量且其变动计入其他综合收益的金融资产 | ths_other_compre_fa_by_fv_stock | 不保留 |
| 资产负债表-非流动资产 | 以摊余成本计量的金融资产 | ths_fa_calc_by_amortized_cost_stock | 不保留 |
| 资产负债表-流动负债 | 应付短期债券 | ths_st_bond_payable_stock | 不保留，由新码 ths_st_bond_payable_new_stock 替代 |

## 5. 补充进度

| 报表/范围 | 状态 |
|---|---|
| 资产负债表（一般企业） | ✅ 定稿：接口编辑器清单 133 项，中文名齐全；3 项旧码拍板不保留，应付短期债券换用新码 |
| 利润表（一般企业） | ✅ 定稿：83 项（不含 3 条报表信息行，归 meta；含 2 EPS 非加总行）；不保留 4 项（在建工程合计误选、营业总成本2、扣非旧码、10,现金流量套期储备树内没有）；赔付支出/提取保险合同准备金漏勾补入 |
| 现金流量表（一般企业） | ✅ 定稿：110 项（模板 105 全含 + 5 新码，中文名全部确认）；报表列分组：经营 33/投资 19/筹资 18/汇率变动与净增加额 6/间接法 34 |
| 披露日期/报表格式等（财务报表(新准则)节点下） | ⬜ 定期报告实际/预计披露日期、最新报告期、报表格式；其中披露日码已归入 §3.1 的 meta，其余不在模板 |
| 商业银行/证券公司/保险公司模板 | 延后不做（金融行业延后，见决策记录 2026-10-14） |

## 6. 待确认问题项（2026-10-19，共 16 项，已全部闭环——三表清单定稿）

> 序位 = 该码在编辑器生成公式指标串中的位置（从 1 数起），便于回编辑器核对。

**A. 疑似误选（1 项，确认剔除或保留）**

| # | 表 | 编辑器序位 | ifind变量名 | 问题 |
|---|---|---|---|---|
| 1 | 利润表 | 1 | `ths_construction_in_process_sum_stock` | 在建工程合计，属资产负债表科目 |

**B. 新码中文名待确认（11 项，请编辑器悬停补名）**

| # | 表 | 编辑器序位 | ifind变量名 | 备注 |
|---|---|---|---|---|
| 2 | 利润表 | 9 | `ths_operating_total_cost_stock` | 与模板「营业总成本」码 `ths_operating_cost_2_stock`（序位 10）并存，请顺带确认两者区别 |
| 3 | 利润表 | 15 | `ths_compensate_net_pay_stock` | 疑似「赔付支出」净额变体 |
| 4 | 利润表 | 16 | `ths_extract_ic_reserve_net_amt_stock` | 疑似「提取保险合同准备金」净额变体 |
| 5 | 利润表 | 27 | `ths_asset_impairment_loss_publish_stock` | 紧随资产减值损失码（序位 26） |
| 6 | 利润表 | 29 | `ths_credit_impairment_loss_publish_stock` | 紧随信用减值损失码（序位 28） |
| 7 | 利润表 | 50 | `unconfirmed_invest_loss_is` | 无 ths_ 前缀；资产负债表清单另有 `unconfirmed_invest_loss_bs`=未确认的投资损失 |
| 8 | 现金流量表 | 23 | `ths_lending_funds_net_increase_stock` | 经营流出段，支付保单红利（序位 22）之后 |
| 9 | 现金流量表 | 24 | `ths_lend_to_other_finins_net_incre_stock` | 经营流出段，紧随上一条 |
| 10 | 现金流量表 | 82 | `ths_depreciation_ire_stock` | 间接法段，固定资产折旧行（序位 80）之后 |
| 11 | 现金流量表 | 85 | `ths_deferred_expense_reduce_stock` | 间接法段，长期待摊费用摊销行（序位 84）之后 |
| 12 | 现金流量表 | 86 | `ths_increase_in_accrued_expenses_stock` | 间接法段，紧随上一条 |

**C. 模板有而编辑器清单未含（4 项，确认树里是否存在/是否勾漏/如何处置）**

| # | 表 | ifind变量名 | 模板科目名 | 备注 |
|---|---|---|---|---|
| 13 | 利润表 | `ths_compen_payout_stock` | 赔付支出 | 疑似被 B-3 净额变体替代 |
| 14 | 利润表 | `ths_extract_ic_reserve_stock` | 提取保险合同准备金 | 疑似被 B-4 净额变体替代 |
| 15 | 利润表 | `ths_np_dnrgal_stock` | 扣非净利润 | 净利润段，归母净利润（序位 57）之后的位置清单里没有 |
| 16 | 利润表 | `ths_cash_flow_hedge_reserve_stock` | 10,现金流量套期储备 | 其他综合收益将重分类段，9,其他债权投资信用减值准备（序位 78）与序位 79 之间没有 |

> 非问题项：3 信息行（披露日期/审计两码）未勾选属预期，信息行非报表科目，维持现状。

**2026-10-19 回执**：#1 误选已忽略；#2=营业总成本、#3=赔付支出净额、#4=提取保险合同准备金净额、#5=资产减值损失(公布值)、#6=信用减值损失(公布值)、#7=未确认投资损失、#11=待摊费用减少、#12=预提费用增加（名称已确认）；#13 赔付支出树内存在、全量清单漏勾，补入清单；#15 编辑器现行码为 `ths_new_analyse_np_dnrgal_stock`（扣除非经常性损益后的归属母公司股东净利润）。**仍开放**：#8/#9/#10 中文名；#14、#16 树内存在性；扣非旧码 `ths_np_dnrgal_stock` 处置（拟按新码替代、旧码不保留，待拍板）。

**追加拍板（2026-10-19）**：「营业总成本2」`ths_operating_cost_2_stock` 忽略不保留，营业总成本以新码 `ths_operating_total_cost_stock` 为准。

**第三批拍板（2026-10-19，闭环）**：#8=拆出资金净增加额、#9=向其他金融机构拆出资金净增加额、#10=投资性房地产折旧；#14 提取保险合同准备金树内存在（公式验证）、漏勾补入；#16 现金流量套期储备树内没有、不保留；扣非旧码 `ths_np_dnrgal_stock` 拍板不保留、用新分析码。**无剩余开放项。**
