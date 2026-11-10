"""iFinD Excel 行情取数：内地与港股同构13列矩阵；原式来自支持情况§12—16。"""
from datetime import date, timedelta
import time

from market_data_mcp import audit, ifind_excel, routing

SOURCE = "ifind_excel"
PRICE_CODES = {"open": "ths_open_price_stock", "high": "ths_high_price_stock",
               "low": "ths_low_stock", "close": "ths_close_price_stock",
               "avg_price": "ths_avg_price_stock"}
PRICE_CODES_HK = {"open": "ths_open_price_hks", "high": "ths_high_d_hks",
                  "low": "ths_low_d_hks", "close": "ths_close_price_hks",
                  "avg_price": "ths_avg_price_hks"}
# 公开字段13列：5价格(除权)+close_no_forward+均价hfq+量额换手+4股本市值；
# 开高低的后复权由因子 F(t)=收后复权÷收 还原现算，不再直取（quote_excel加工）。
FIELDS = tuple(PRICE_CODES) + ("close_no_forward", "avg_price_hfq",
    "amount", "turnover", "company_total_shares", "security_total_shares",
    "company_total_market_cap", "security_total_market_cap")
FAULT_NOTE = ("Excel整批返回0，疑似请求失败；已关闭并重开Excel重试一次仍失败，"
              "可稍后重试或调用close_ifind_excel后检查")


def _specs(market: str, share_type):
    """字段→(iFinD指标, 参数)；未知股份类型仅略过证券总股本。港股金额列显式HKD。"""
    price = PRICE_CODES_HK if market == "HK" else PRICE_CODES
    specs = {}
    for field, indicator in price.items():
        if field == "avg_price":
            specs[field] = (indicator, 100) if market != "HK" else (indicator, 100, "")
        else:
            specs[field] = (indicator, 100, "")
    specs["close_no_forward"] = ("close_no_forward", 107)
    if market == "HK":
        specs["avg_price_hfq"] = (price["avg_price"], 101, "")
        specs["security_total_shares"] = ("ths_sec_total_shares_hks",)
    else:
        specs["avg_price_hfq"] = (price["avg_price"], 107)
        share_code = {"A股": "ths_total_ashare_stock",
                      "B股": "ths_total_bshare_stock"}.get(share_type)
        if share_code:
            specs["security_total_shares"] = (share_code,)
    specs["amount"] = ("ths_amt_d_hks",) if market == "HK" else ("ths_amt_stock",)
    specs["turnover"] = (("ths_turnover_ratio_hks",) if market == "HK"
                         else ("ths_turnover_ratio_stock",))
    specs["company_total_shares"] = (("ths_corp_total_shares_hks",) if market == "HK"
                                     else ("ths_total_shares_stock",))
    specs["company_total_market_cap"] = (("ths_market_value_hks", "HKD") if market == "HK"
                                         else ("ths_market_value_stock",))
    specs["security_total_market_cap"] = (("ths_totalcapitalforsecurities_hk", "HKD")
                                          if market == "HK"
                                          else ("ths_mv_sec_oriented_stock",))
    return specs


def formulas(code: str, days_list: list[str], share_type, market: str):
    """每行日期（剔除周六周日）、每列字段。"""
    specs = _specs(market, share_type)
    columns = [f for f in FIELDS if f in specs]
    matrix = []
    for day in days_list:
        row = []
        for field in columns:
            indicator, *args = specs[field]
            parts = [f'"{indicator}"', f'"{code}"', f'"{day}"'] + [
                f'"{arg}"' if isinstance(arg, str) else str(arg) for arg in args]
            row.append('=@thsiFinD(' + ','.join(parts) + ')')
        matrix.append(row)
    return columns, matrix


def _zero_fault(values: list[list], columns: list[str], market: str) -> bool:
    """行情0值故障判定（方案0值判定节）。A股按行；港股整块。"""
    idx = {c: i for i, c in enumerate(columns)}
    if "close_no_forward" not in idx or "close" not in idx:
        return False
    cnf_i, close_i = idx["close_no_forward"], idx["close"]

    def zero(value):
        return isinstance(value, (int, float)) and value == 0

    def positive(value):
        return isinstance(value, (int, float)) and value > 0

    if market == "HK":
        return all(zero(row[close_i]) and zero(row[cnf_i]) for row in values)
    ohl = [idx[f] for f in ("open", "high", "low") if f in idx]
    if not ohl:
        return False
    for row in values:
        if all(zero(row[i]) for i in ohl) and zero(row[close_i]) and zero(row[cnf_i]):
            return True
    return False


def _working_days(start: str, end: str, ipo_date: str) -> list[str]:
    """日历日区间剔除周六周日，起点不早于上市日。"""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if len(ipo_date) == 8 and ipo_date.isdigit():
        ipo_day = date(int(ipo_date[:4]), int(ipo_date[4:6]), int(ipo_date[6:]))
        if first < ipo_day:
            first = ipo_day
    return [(first + timedelta(days=i)).isoformat()
            for i in range((last - first).days + 1)
            if (first + timedelta(days=i)).weekday() < 5]


def fetch_quote(root, mc, start, end, security):
    market = mc.market
    code = routing.to_ifind(mc)
    days_list = _working_days(start, end, str((security or {}).get("上市日期") or ""))
    if not days_list:
        return {"ok": False, "source": SOURCE,
                "error": f"区间{start}~{end}剔除周六周日并按上市日期裁剪后为空", "notes": []}
    columns, matrix = formulas(code, days_list, (security or {}).get("股份类型"), market)
    started = time.monotonic()
    try:
        result = ifind_excel.fetch_matrix(matrix, visible=True)
        if len(result["values"]) != len(days_list) or any(
                len(row) != len(columns) for row in result["values"]):
            raise RuntimeError("Excel 返回矩阵尺寸与请求不一致")
        fault = _zero_fault(result["values"], columns, market)
        if fault:
            # iFinD 同公式缓存：取数失败的重试必须关闭Excel重开，仅重输公式无效。
            ifind_excel.close_excel(timeout=120)
            result = ifind_excel.fetch_matrix(matrix, visible=True)
            fault = _zero_fault(result["values"], columns, market)
        errors = result.get("errors") or []
        bad_columns = {item["column"] for item in errors}
        data = {field: [{"date": day, "value": result["values"][i][j], "source": SOURCE}
                        for i, day in enumerate(days_list)]
                for j, field in enumerate(columns) if j not in bad_columns}
        notes = [f"{columns[item['column']]} {days_list[item['row']]}: {item['error']}"
                 for item in errors]
        if "security_total_shares" not in columns:
            notes.append("股份类型缺失或未识别，证券总股本未取数；不默认归类为A股")
        if fault:
            notes.append(FAULT_NOTE)
        audit.log_request(root, source=SOURCE, market=market, code=code,
            api="Excel:thsiFinD", fields=columns, start=days_list[0], end=days_list[-1],
            ok=not errors and not fault, elapsed=time.monotonic() - started,
            error="；".join(notes) if (errors or fault) else None)
        if fault:
            return {"ok": False, "source": SOURCE, "error": "；".join(notes), "notes": notes}
        return {"ok": bool(data), "source": SOURCE, "data": data, "notes": notes,
                "metrics": result.get("metrics"), "formula_shape": [len(days_list), len(columns)]}
    except Exception as exc:
        audit.log_request(root, source=SOURCE, market=market, code=code,
            api="Excel:thsiFinD", fields=columns, start=start, end=end,
            ok=False, elapsed=time.monotonic() - started, error=str(exc))
        return {"ok": False, "source": SOURCE, "error": str(exc), "notes": []}
