"""按已验证指标请求公司信息、营收结构；不写业务缓存。"""
from datetime import date
from decimal import Decimal, InvalidOperation

from market_data_mcp.providers import ifind
from market_data_mcp.routing import to_ifind

PROFILE = {
    "证券简称": "ths_stock_short_name_stock", "证券代码": "ths_thscode_stock",
    "公司名称": "ths_corp_cn_name_stock", "公司网站": "ths_corp_website_stock",
    "上市板块": "ths_listedsector_stock", "交易所": "ths_listing_exchange_stock",
    "上市日期": "ths_ipo_date_stock", "成立日期": "ths_established_date_stock",
    "注册地址": "ths_reg_address_stock", "办公地址": "ths_office_address_stock",
    "法定代表人": "ths_legal_representative_stock", "企业性质": "ths_corp_nature_stock",
    "董事长": "ths_chairman_stock", "总经理": "ths_general_manager_stock",
    "控股股东": "ths_controlling_holder_stock", "控股股东持股比例": "ths_controlling_holder_held_ratio_stock",
    "实际控制人": "ths_actual_controller_stock", "实际控制人持股比例": "ths_actual_controller_held_ratio_stock",
    "主要产品": "ths_mo_product_name_stock", "产品类型": "ths_mo_product_type_stock",
}
IPO = {"发行股数": "ths_ipo_quantity_stock", "发行价格": "ths_ipo_price_stock",
       "募集资金总额": "ths_ipo_rc_stock", "募集资金净额": "ths_ipo_actual_rc_stock",
       "发行后总股本": "ths_total_shares_after_ipo_ld_stock", "发行后市盈率": "ths_ipo_pe_dlt_stock",
       "发行后市净率": "ths_ipo_pb_stock", "发行费用": "ipo_fee",
       "保荐机构（主承销商）": "ths_ipo_main_underwrite_stock", "保荐代表人": "ths_ipo_sponsor_representative_stock",
       "发行人律师": "ths_law_firm_stock", "经办律师": "ths_lawyer_stock",
       "会计事务所": "ths_accounting_firm_stock", "经办会计师": "ths_accountant_stock",
       "资产评估机构": "ths_asset_evaluate_org_stock", "经办评估师": "ths_charged_evaluator_stock",
       "上市日期": "ths_ipo_date_stock"}
HOLDERS = {"名称": "ths_holder_name_stock", "性质": "ths_holder_nature_stock",
           "持股数": "ths_holder_held_num_stock", "限售股数": "ths_holder_held_ls_num_stock",
           "质押股数": "ths_ma_holder_pledge_stock", "冻结股数": "ths_holder_freeze_stock",
           "持股比例": "ths_holder_held_ratio_stock"}
FORECAST = {
    "营收均值": "ths_fore_mob_income_mean_consensus_stock",
    "营收中值": "ths_fore_mobi_median_consensus_stock",
    "营收最大值": "ths_fore_mob_income_max_consensus_stock",
    "营收最小值": "ths_fore_mob_income_min_consensus_stock",
    "归母净利润均值": "ths_fore_np_mean_consensus_stock",
    "归母净利润中值": "ths_fore_np_median_consensus_stock",
    "归母净利润最大值": "ths_fore_np_max_consensus_stock",
    "归母净利润最小值": "ths_fore_np_min_consensus_stock",
    "机构家数": "ths_eps_fore_org_num_consensus_stock",
}


def basic(root, mc, fields: dict, parameters: str | dict = "") -> dict:
    codes = list(fields.values())
    params = [parameters.get(name, "") if isinstance(parameters, dict) else parameters for name in fields]
    result = ifind.request_ifind(root, "THS_BD", to_ifind(mc), ";".join(codes), ";".join(params),
                                 required_columns=codes)
    if result.errorcode != 0:
        raise RuntimeError(result.errmsg)
    if result.data is None or len(result.data) == 0:
        return {name: None for name in fields}
    row = result.data.iloc[0]
    return {name: ifind._statement_value(row[code]) for name, code in fields.items()}


def latest_report(root, mc):
    result = ifind.probe_latest_report(root, mc)
    if not result.get("ok"):
        raise RuntimeError(result.get("error"))
    return result["report_date"]


# 集中度指标（2026-10-26 实测：8位报告期,排名；name 与 ratio 两码同批 -209，必须逐码调用；
# 上游返回百分数，/100 存比值；未披露期与超界排名返回 None 不报错）
CONCENTRATION = {
    "customer": {"name": "ths_main_customer_name_stock", "ratio": "ths_main_customer_ratio_stock",
                 "top5": "ths_main_customer_sales_amt_ratio_stock"},
    "supplier": {"name": "ths_main_supplier_name_stock", "ratio": "ths_main_supplier_ratio_stock",
                 "top5": "ths_main_supplier_pur_amt_ratio_stock"},
}


def _ratio_value(value):
    """上游百分数转比值；非数值（None 等）原样。"""
    return value / 100 if isinstance(value, (int, float)) else value


def segment_row_empty(row):
    return all(row.get(key) in (None, "") for key in ("name", "income", "gross_profit"))


def segments(root, mc, period, dimension, top_n=5, start_rank=1):
    """依据财报细则§5，主营按请求上限获取，保留末项空行供缓存判断覆盖。"""
    api_period = period.replace("-", "")
    if dimension in CONCENTRATION:
        spec = CONCENTRATION[dimension]
        rows = []
        for rank in range(1, 6):
            row = {"rank": rank}
            for key in ("name", "ratio"):
                row[key] = _ratio_value(basic(root, mc, {key: spec[key]}, f"{api_period},{rank}")[key])
            rows.append(row)
        top5 = basic(root, mc, {"ratio": spec["top5"]}, api_period)["ratio"]
        rows.append({"rank": "top5", "ratio": _ratio_value(top5)})
        return rows
    fields = {"name": f"ths_moc_project_name_{dimension}_stock",
              "income": f"ths_moc_project_income_{dimension}_stock",
              "gross_profit": f"ths_moc_project_profit_{dimension}_stock"}
    rows = []
    # 同一码不同排名不能合并；每个排名是独立SDK批次。
    for rank in range(start_rank, top_n + 1):
        row = {"rank": rank, **basic(root, mc, fields, f"{api_period},{rank}")}
        rows.append(row)
        if segment_row_empty(row):
            break
    return rows


def annual_report_info(root, mc, period):
    """财报细则§2的年报补充；参数原式与样本在支持情况§7维护。"""
    api_period = period.replace("-", "")
    fields = {"AUDITOR": "ths_audit_institution_stock", "OPINION_TYPE": "ths_audit_opinion_type_stock",
              "INTERNAL_CONTROL_OPINION": "ths_ica_opinion_type_stock", "NOTICE_DATE": "ths_regular_report_actual_dd_stock"}
    return basic(root, mc, fields, {key: api_period + (",100" if key in ("AUDITOR", "OPINION_TYPE") else "")
                                  for key in fields})


def _annual_year(latest: str) -> int:
    """最新已披露年报年份（模板 N8 口径：最新报告期非 12-31 则取其上一年）。"""
    year = int(latest[:4])
    return year if latest[5:] == "12-31" else year - 1


def section(root, mc, name, *, periods=None, years=None, as_of_date=None):
    if name == "profile":
        output = basic(root, mc, PROFILE)
        today = date.today().strftime("%Y%m%d")
        dated = {"申万行业": "ths_the_ths_industry_stock", "证监会行业": "ths_the_new_csrc_industry_stock",
                 "主营业务": "ths_main_businuess_stock"}
        output.update(basic(root, mc, dated, {"申万行业": f"103,{today}", "证监会行业": f"102,{today}", "主营业务": today}))
        # 员工人数=最新已披露年报期末；违规次数=(上市日期,查询日)，上市日期取同批 PROFILE 原值（8 位）
        year = _annual_year(latest_report(root, mc))
        output.update(basic(root, mc, {"员工人数": "ths_ygzs_new_stock"}, f"{year}1231"))
        ipo_date = output.get("上市日期")
        if ipo_date:
            output.update(basic(root, mc, {"上市以来违规次数": "ths_int_illegality_num_stock"},
                                f"{ipo_date},{today}"))
        else:
            output["上市以来违规次数"] = None
        return output
    if name == "ipo":
        output = basic(root, mc, IPO, {"发行费用": "10000"})
        fee = output.get("发行费用")
        if fee not in (None, ""):
            try:
                amount = Decimal(str(fee)) * 10000
                if amount.is_finite():
                    output["发行费用"] = float(amount)
            except InvalidOperation:
                pass  # 文本占位保留，不由募资差额编造费用。
        return output
    if name == "holders":
        return [{"report_date": period, "rank": rank,
                 **basic(root, mc, HOLDERS, f"{period.replace('-', '')},{rank}")}
                for period in periods for rank in range(1, 11)]
    if name == "forecast":
        return [{"year": year, "as_of_date": as_of_date,
                 **basic(root, mc, FORECAST, f"{year},{as_of_date.replace('-', '')}")}
                for year in years]
    if name == "dividends":
        fields = {"现金分红": "ths_annual_accum_divid_ann_stock", "分红含回购": "ths_annual_accum_divid_ann_inclu_stock"}
        output = []
        for year in years:
            values = basic(root, mc, fields, str(year))
            cash, total = values["现金分红"], values["分红含回购"]
            output.append({"year": year, **values, "回购": total - cash if isinstance(cash, (int, float)) and isinstance(total, (int, float)) else None})
        return output
    raise ValueError(f"未知section：{name}")
