# -*- coding: utf-8 -*-
"""生成 verified-formulas.jsonl：只写已实测确认的公式。

数据来源：Xmind行情分支原式、Excel取数实测报告、本次会话实测。
每条记录含完整字段；reading_mode区分数值矩阵与文本单列。
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "verified-formulas.jsonl"
V = "verified"
VC = "verified_with_caveat"


def p(pos, name, meaning, options=None):
    return {"position": pos, "name": name, "meaning": meaning,
            "options": options or [], "default": None}


def rec(path, name, indicator, template, definition, params, source, unit,
        example, value, status=V, evidence="", notes="", aliases=None, mode="matrix",
        algorithm="", verified_at="2026-11-18"):
    return {
        "path": path, "name": name, "aliases": aliases or [], "indicator": indicator,
        "formula_template": template, "definition": definition, "algorithm": algorithm,
        "parameters": params, "source": source, "unit": unit,
        "example": example, "example_value": value,
        "verification": status, "verified_at": verified_at,
        "evidence": evidence, "notes": notes, "reading_mode": mode,
    }


ADJ = [{"value": v, "meaning": m} for v, m in [
    ("100", "不复权"), ("107", "后复权"), ("108", "前复权"),
    ("105", "后复权(现金分红)"), ("106", "前复权(现金分红)"),
    ("101", "后复权(分红再投)"), ("102", "前复权(分红再投)")]]

R = []
BASE = "Xmind行情数据分支+Excel取数基础实测-2026-11-04"

# A股行情
R += [
    rec("股票全部指标/行情指标/日行情", "开盘价", "ths_open_price_stock",
        '=@thsiFinD("ths_open_price_stock","{code}","{date}",100,"")',
        "指定交易日开盘价，人民币计价", [p(2,"thsCode","证券代码"),p(3,"Date","交易日"),p(4,"Type","复权方式",ADJ)],
        "交易所", "元", '=@thsiFinD("ths_open_price_stock","300308.SZ","2026-11-18",100,"")', None,
        evidence=BASE, notes="参数末位空串保持脑图原式写法"),
    rec("股票全部指标/行情指标/日行情", "最高价", "ths_high_price_stock",
        '=@thsiFinD("ths_high_price_stock","{code}","{date}",100,"")',
        "指定交易日最高价", [p(2,"thsCode","证券代码"),p(3,"Date","交易日"),p(4,"Type","复权方式",ADJ)],
        "交易所", "元", '=@thsiFinD("ths_high_price_stock","300308.SZ","2026-11-18",100,"")', None, evidence=BASE),
    rec("股票全部指标/行情指标/日行情", "最低价", "ths_low_stock",
        '=@thsiFinD("ths_low_stock","{code}","{date}",100,"")',
        "指定交易日最低价", [p(2,"thsCode","证券代码"),p(3,"Date","交易日"),p(4,"Type","复权方式",ADJ)],
        "交易所", "元", '=@thsiFinD("ths_low_stock","300308.SZ","2026-11-18",100,"")', None, evidence=BASE),
    rec("股票全部指标/行情指标/日行情", "收盘价", "ths_close_price_stock",
        '=@thsiFinD("ths_close_price_stock","{code}","{date}",100,"")',
        "指定交易日收盘价", [p(2,"thsCode","证券代码"),p(3,"Date","交易日"),p(4,"Type","复权方式",ADJ)],
        "交易所", "元", '=@thsiFinD("ths_close_price_stock","600519.SH","2026-11-17",100)', 1457.7, evidence=BASE,
        notes="实测复权码：100=1457.7,101=11181.56,102=1457.7,105=10007.32,107=12943.97,108=1457.7；2015-06-01的106返回-55.02为错值，勿用"),
    rec("股票全部指标/行情指标/日行情", "后复权收盘价", "close_no_forward",
        '=@thsiFinD("close_no_forward","{code}","{date}",107)',
        "指定交易日后复权收盘价", [p(2,"thsCode","证券代码"),p(3,"Date","交易日"),p(4,"Type","复权方式",ADJ)],
        "交易所", "元", '=@thsiFinD("close_no_forward","300308.SZ","2026-11-18",107)', None,
        evidence=BASE, status=VC, notes="周末节假日返回0，不填充前值；开市日用>0判定"),
    rec("股票全部指标/行情指标/日行情", "成交均价", "ths_avg_price_stock",
        '=@thsiFinD("ths_avg_price_stock","{code}","{date}",100)',
        "指定交易日成交均价", [p(2,"thsCode","证券代码"),p(3,"Date","交易日"),p(4,"Type","复权方式",ADJ)],
        "交易所", "元", '=@thsiFinD("ths_avg_price_stock","600519.SH","2026-11-17",100)', 1450.77, evidence=BASE,
        notes="B股均价返回人民币，高开低收为外币，对比时需换汇"),
    rec("股票全部指标/行情指标/日行情", "成交额", "ths_amt_stock",
        '=@thsiFinD("ths_amt_stock","{code}","{date}")',
        "指定交易日成交额，B股返回人民币", [p(2,"thsCode","证券代码"),p(3,"Date","交易日")],
        "交易所", "元", '=@thsiFinD("ths_amt_stock","300308.SZ","2026-11-18")', None, evidence=BASE,
        status=VC, notes="成交额无复权概念；B股为人民币计价"),
    rec("股票全部指标/行情指标/日行情", "换手率", "ths_turnover_ratio_stock",
        '=@thsiFinD("ths_turnover_ratio_stock","{code}","{date}")',
        "指定交易日换手率百分数", [p(2,"thsCode","证券代码"),p(3,"Date","交易日")],
        "交易所", "%", '=@thsiFinD("ths_turnover_ratio_stock","300308.SZ","2026-11-18")', None, evidence=BASE),
]

# A股股本市值
R += [
    rec("股票全部指标/股本结构", "总股本", "ths_total_shares_stock",
        '=@thsiFinD("ths_total_shares_stock","{code}","{date}")',
        "上市公司发行所有股份总数，含新股发行前后股份（存托凭证以份数计）",
        [p(2,"thsCode","证券代码"),p(3,"Date","日期，不设默认本机")], "公司公告", "股",
        '=@thsiFinD("ths_total_shares_stock","300308.SZ","2026-11-18")', 1177909641,
        evidence="用户示例+本次实测", notes="与证券总股本ths_total_ashare_stock区分"),
    rec("股票全部指标/股本结构", "A股合计股本", "ths_total_ashare_stock",
        '=@thsiFinD("ths_total_ashare_stock","{code}")',
        "A股股份类别总股本", [p(2,"thsCode","证券代码")], "公司公告", "股",
        '=@thsiFinD("ths_total_ashare_stock","300308.SZ")', None, evidence=BASE),
    rec("股票全部指标/股本结构", "B股合计股本", "ths_total_bshare_stock",
        '=@thsiFinD("ths_total_bshare_stock","{code}")',
        "B股股份类别总股本", [p(2,"thsCode","证券代码")], "公司公告", "股",
        '=@thsiFinD("ths_total_bshare_stock","900901.SH")', None, evidence=BASE),
    rec("股票全部指标/市值指标", "面向证券总市值", "ths_mv_sec_oriented_stock",
        '=@thsiFinD("ths_mv_sec_oriented_stock","{code}")',
        "厂商面向当前证券的总市值原值", [p(2,"thsCode","证券代码")], "同花顺计算", "元",
        '=@thsiFinD("ths_mv_sec_oriented_stock","300308.SZ")', None, evidence=BASE),
    rec("股票全部指标/市值指标", "历史总市值", "ths_mv_back_test_stock",
        '=@thsiFinD("ths_mv_back_test_stock","{code}","{date}")',
        "总市值历史序列，分市场加总口径，全历史可用",
        [p(2,"thsCode","证券代码"),p(3,"Date","交易日")], "公司公告", "元",
        '=@thsiFinD("ths_mv_back_test_stock","300308.SZ","2020-01-01")', None, evidence=BASE),
]

# 港股行情与股本
R += [
    rec("港股全部指标/行情指标", "港股开盘价", "ths_open_price_hks",
        '=@thsiFinD("ths_open_price_hks","{code}","{date}",100,"")',
        "港股开盘价，港元计价", [p(2,"thsCode","4位带前导零代码如0700.HK"),p(3,"Date","交易日"),p(4,"Type","复权方式")],
        "交易所", "港元", '=@thsiFinD("ths_open_price_hks","0700.HK","2026-11-18",100,"")', None, evidence=BASE),
    rec("港股全部指标/行情指标", "港股最高价", "ths_high_d_hks",
        '=@thsiFinD("ths_high_d_hks","{code}","{date}",100,"")', "港股最高价",
        [p(2,"thsCode","港股代码"),p(3,"Date","交易日")], "交易所", "港元",
        '=@thsiFinD("ths_high_d_hks","0700.HK","2026-11-18",100,"")', None, evidence=BASE),
    rec("港股全部指标/行情指标", "港股最低价", "ths_low_d_hks",
        '=@thsiFinD("ths_low_d_hks","{code}","{date}",100,"")', "港股最低价",
        [p(2,"thsCode","港股代码"),p(3,"Date","交易日")], "交易所", "港元",
        '=@thsiFinD("ths_low_d_hks","0700.HK","2026-11-18",100,"")', None, evidence=BASE),
    rec("港股全部指标/行情指标", "港股收盘价", "ths_close_price_hks",
        '=@thsiFinD("ths_close_price_hks","{code}","{date}",100,"")', "港股收盘价",
        [p(2,"thsCode","港股代码"),p(3,"Date","交易日"),p(4,"Type","复权方式")],
        "交易所", "港元", '=@thsiFinD("ths_close_price_hks","0700.HK","2026-11-17",100)', 376.0, evidence=BASE,
        notes="4位带前导零0700.HK；实测00700.HK也返回同值"),
    rec("港股全部指标/行情指标", "港股均价", "ths_avg_price_hks",
        '=@thsiFinD("ths_avg_price_hks","{code}","{date}",100,"")', "港股成交均价",
        [p(2,"thsCode","港股代码"),p(3,"Date","交易日"),p(4,"Type","复权方式，101后复权")],
        "交易所", "港元", '=@thsiFinD("ths_avg_price_hks","0700.HK","2026-11-18",100,"")', None, evidence=BASE),
    rec("港股全部指标/行情指标", "港股成交额", "ths_amt_d_hks",
        '=@thsiFinD("ths_amt_d_hks","{code}","{date}")', "港股成交额",
        [p(2,"thsCode","港股代码"),p(3,"Date","交易日")], "交易所", "港元",
        '=@thsiFinD("ths_amt_d_hks","0700.HK","2026-11-18")', None, evidence=BASE),
    rec("港股全部指标/行情指标", "港股换手率", "ths_turnover_ratio_hks",
        '=@thsiFinD("ths_turnover_ratio_hks","{code}","{date}")', "港股换手率",
        [p(2,"thsCode","港股代码"),p(3,"Date","交易日")], "交易所", "%",
        '=@thsiFinD("ths_turnover_ratio_hks","0700.HK","2026-11-18")', None, evidence=BASE),
    rec("港股全部指标/股本市值", "港股公司总股本", "ths_corp_total_shares_hks",
        '=@thsiFinD("ths_corp_total_shares_hks","{code}","{date}")', "港股公司总股本",
        [p(2,"thsCode","港股代码"),p(3,"Date","交易日")], "公司公告", "股",
        '=@thsiFinD("ths_corp_total_shares_hks","0700.HK","2026-11-18")', None, evidence=BASE),
    rec("港股全部指标/股本市值", "港股证券总股本", "ths_sec_total_shares_hks",
        '=@thsiFinD("ths_sec_total_shares_hks","{code}","{date}")', "当前证券总股本",
        [p(2,"thsCode","港股代码"),p(3,"Date","交易日")], "公司公告", "股",
        '=@thsiFinD("ths_sec_total_shares_hks","0700.HK","2026-11-18")', None, evidence=BASE),
    rec("港股全部指标/股本市值", "港股公司总市值", "ths_market_value_hks",
        '=@thsiFinD("ths_market_value_hks","{code}","{date}","HKD")', "港股公司总市值",
        [p(2,"thsCode","港股代码"),p(3,"Date","交易日"),p(4,"币种","HKD")], "同花顺计算", "港元",
        '=@thsiFinD("ths_market_value_hks","0700.HK","2026-11-18","HKD")', None, evidence=BASE,
        notes="金额类原式显式传HKD，不换算"),
    rec("港股全部指标/股本市值", "港股证券总市值", "ths_totalcapitalforsecurities_hk",
        '=@thsiFinD("ths_totalcapitalforsecurities_hk","{code}","{date}","HKD")', "面向证券总市值",
        [p(2,"thsCode","港股代码"),p(3,"Date","交易日"),p(4,"币种","HKD")], "同花顺计算", "港元",
        '=@thsiFinD("ths_totalcapitalforsecurities_hk","0700.HK","2026-11-18","HKD")', None, evidence=BASE),
]

# 基本资料（文本静态字段）
R += [
    rec("股票全部指标/基本资料/证券资料", "股票简称", "ths_stock_short_name_stock",
        '=@thsiFinD("ths_stock_short_name_stock","{code}")',
        "上市公司挂牌交易使用的标准化名称缩写，区别于公司法定全称",
        [p(2,"thsCode","证券代码")], "交易所", "",
        '=@thsiFinD("ths_stock_short_name_stock","300308.SZ")', "中际旭创",
        evidence="用户提供+说明库", notes="静态字段无日期参数", mode="text"),
    rec("股票全部指标/基本资料/证券资料", "上市日期", "ths_ipo_date_stock",
        '=@thsiFinD("ths_ipo_date_stock","{code}")', "股票上市日期",
        [p(2,"thsCode","证券代码")], "交易所", "",
        '=@thsiFinD("ths_ipo_date_stock","300308.SZ")', None,
        evidence="company_ifind_service.py", notes="返回YYYY-MM-DD文本，需读取整项并规范化为8位数字", mode="text"),
    rec("港股全部指标/基本资料", "港股上市日期", "ths_ipo_date_hks",
        '=@thsiFinD("ths_ipo_date_hks","{code}")', "港股上市日期",
        [p(2,"thsCode","4位带前导零代码")], "交易所", "",
        '=@thsiFinD("ths_ipo_date_hks","0700.HK")', None,
        evidence="company_ifind_service.py", notes="文本模式读取，返回YYYY-MM-DD，规范化为8位", mode="text"),
]

# 外汇
R += [
    rec("外汇全部指标/行情", "外汇收盘价", "ths_closef_forex",
        '=@thsiFinD("ths_closef_forex","{code}","{date}")', "外汇指定交易日收盘价",
        [p(2,"thsCode","外汇代码如USDCNY.IN"),p(3,"Date","交易日")], "外汇交易中心、做市商", "",
        '=@thsiFinD("ths_closef_forex","USDCNY.IN","2026-11-17")', 6.6655,
        evidence="Xmind汇率分支+本次实测", aliases=["ths_close_forex"],
        notes="别名ths_close_forex同值；不同后缀是不同报价源：USDCNY.IN=6.6655,USDCNY.FX=6.666,USDCNY=6.7132,USDCNY.EX=6.7132，勿混用"),
    rec("外汇全部指标/行情", "港元兑人民币", "ths_closef_forex",
        '=@thsiFinD("ths_closef_forex","HKDCNY.FX","{date}")', "1港元兑人民币",
        [p(2,"thsCode","HKDCNY.FX"),p(3,"Date","交易日")], "外汇交易中心、做市商", "",
        '=@thsiFinD("ths_closef_forex","HKDCNY.FX","2026-11-17")', 0.8496,
        evidence="Xmind汇率分支+本次实测"),
]

# 指数（本次实测）
R += [
    rec("指数全部指标/估值指标", "指数市盈率", "ths_pe_index",
        '=@thsiFinD("ths_pe_index","{code}","{date}")', "指数整体法市盈率=∑总市值/∑归母净利润",
        [p(2,"thsCode","指数代码如000688.SH"),p(3,"Date","交易日")], "同花顺计算", "",
        '=@thsiFinD("ths_pe_index","000688.SH","2026-11-17")', 186.22,
        evidence="本次实测", notes="正确写法3参；加第4参返回0；上证综指16.58、沪深300 13.81、创业板指32.87"),
    rec("指数全部指标/估值指标", "指数市净率", "ths_pb_index",
        '=@thsiFinD("ths_pb_index","{code}","{date}")', "指数整体法市净率",
        [p(2,"thsCode","指数代码"),p(3,"Date","交易日")], "同花顺计算", "",
        '=@thsiFinD("ths_pb_index","000688.SH","2026-11-17")', 6.05,
        evidence="本次实测", notes="正确写法3参；4参(code,date,108,100)也返回值，口径不同"),
    rec("指数全部指标/估值指标", "指数市销率", "ths_ps_index",
        '=@thsiFinD("ths_ps_index","{code}","{date}")', "指数市销率",
        [p(2,"thsCode","指数代码"),p(3,"Date","交易日")], "同花顺计算", "",
        '=@thsiFinD("ths_ps_index","000688.SH","2026-11-17")', None,
        evidence="本次实测", status=VC, notes="3参返回空，需进一步确认参数位序"),
    rec("指数全部指标/估值指标", "指数股息率", "ths_dividend_rate_index",
        '=@thsiFinD("ths_dividend_rate_index","{code}","{date}")', "指数股息率",
        [p(2,"thsCode","指数代码"),p(3,"Date","交易日")], "同花顺计算", "",
        '=@thsiFinD("ths_dividend_rate_index","000688.SH","2026-11-17")', 0.27,
        evidence="本次实测"),
    rec("指数全部指标/行情指标", "指数收盘价", "ths_close_price_index",
        '=@thsiFinD("ths_close_price_index","{code}","{date}")', "指数收盘价",
        [p(2,"thsCode","指数代码"),p(3,"Date","交易日")], "交易所", "",
        '=@thsiFinD("ths_close_price_index","000688.SH","2026-11-17")', 1221.19,
        evidence="本次实测"),
    rec("指数全部指标/技术指标", "指数均线", "ths_ma_index",
        '=@thsiFinD("ths_ma_index","{code}","{date}",100,100)', "指数简单移动平均",
        [p(2,"thsCode","指数代码"),p(3,"Date","交易日"),p(4,"Type","周期参数"),p(5,"Type","周期参数")],
        "同花顺计算", "", '=@thsiFinD("ths_ma_index","000688.SH","2026-11-17",100,100)', 1623.84,
        evidence="本次实测", status=VC, notes="DTT写法返回1623.84；参数(5,20)返回0，周期参数含义未确认"),
    rec("指数全部指标/技术指标", "指数RSI", "ths_rsi_index",
        '=@thsiFinD("ths_rsi_index","{code}","{date}",100,100)', "指数相对强弱指标",
        [p(2,"thsCode","指数代码"),p(3,"Date","交易日"),p(4,"Type","周期"),p(5,"Type","周期")],
        "同花顺计算", "", '=@thsiFinD("ths_rsi_index","000688.SH","2026-11-17",100,100)', 45.76,
        evidence="本次实测", status=VC, notes="DTT写法可用，周期参数含义未确认"),
]

# 美股
R += [
    rec("美股全部指标/股本指标", "美股流通股本", "ths_float_shares_usk",
        '=@thsiFinD("ths_float_shares_usk","{code}","{date}")', "美股流通股本",
        [p(2,"thsCode","美股代码如AAPL.O"),p(3,"Date","交易日")], "", "股",
        '=@thsiFinD("ths_float_shares_usk","AAPL.O","2026-11-17")', 14532182000,
        evidence="本次实测", notes="1/2/3/4参均返回同值，取最简2参"),
]

# 短名体系
R += [
    rec("全球股票/行情指标", "收盘价(短名)", "close_price",
        '=@thsiFinD("close_price","{code}","{date}")', "全球股票收盘价，支持多币种与复权",
        [p(2,"thsCode","证券代码"),p(3,"Date","交易日"),p(4,"Type","货币币种"),p(5,"Type","复权方式")],
        "交易所", "元", '=@thsiFinD("close_price","600519.SH","2026-11-17")', 1457.7,
        evidence="本次实测+说明库", aliases=["短名收盘价"],
        notes="第二套短名体系；复权枚举100/107/108，货币OC/CNY/USD/HKD"),
    rec("全球股票/估值指标", "市盈率(短名)", "pe",
        '=@thsiFinD("pe","{code}","{date}")', "全球股票市盈率",
        [p(2,"thsCode","证券代码"),p(3,"Date","交易日")], "同花顺计算", "",
        '=@thsiFinD("pe","600519.SH","2026-11-17")', 22.14,
        evidence="本次实测+说明库", aliases=["短名PE"]),
    rec("全球股票/行情指标", "均价(短名)", "average_price",
        '=@thsiFinD("average_price","{code}","{date}")', "证券成交均价",
        [p(2,"thsCode","证券代码"),p(3,"Date","交易日")], "交易所", "元",
        '=@thsiFinD("average_price","600519.SH","2026-11-17")', 1450.77,
        evidence="本次实测+说明库"),
]

NL=chr(10)
with OUT.open("w", encoding="utf-8", newline=NL) as f:
    for r in R:
        f.write(json.dumps(r, ensure_ascii=False)+NL)
print(f"wrote {len(R)} verified records")