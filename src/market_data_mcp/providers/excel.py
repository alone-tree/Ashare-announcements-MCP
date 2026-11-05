"""内地行情唯一 Excel 取数模块；矩阵原式来自支持情况§12—14，不写业务缓存。"""
from datetime import date, timedelta
import time

from market_data_mcp import audit, ifind_excel

SOURCE = "ifind_excel"
PRICE_CODES = {"open": "ths_open_price_stock", "high": "ths_high_price_stock",
               "low": "ths_low_stock", "close": "ths_close_price_stock",
               "avg_price": "ths_avg_price_stock"}
FIELDS = tuple(PRICE_CODES) + tuple(f"{f}_hfq" for f in PRICE_CODES) + (
    "amount", "turnover", "company_total_shares", "security_total_shares",
    "company_total_market_cap", "security_total_market_cap")


def formulas(code, days, share_type):
    """每行日期、每列字段；未知股份类型仅略过依赖分类的证券总股本。"""
    specs = {}
    for field, indicator in PRICE_CODES.items():
        specs[field] = (indicator, 100, "") if field != "avg_price" else (indicator, 100)
    for field, indicator in PRICE_CODES.items():
        specs[f"{field}_hfq"] = (indicator, 107, "") if field != "avg_price" else (indicator, 107)
    specs.update({"amount": ("ths_amt_stock",), "turnover": ("ths_turnover_ratio_stock",),
        "company_total_shares": ("ths_total_shares_stock",),
        "company_total_market_cap": ("ths_market_value_stock",),
        "security_total_market_cap": ("ths_mv_sec_oriented_stock",)})
    share_code = {"A股": "ths_total_ashare_stock", "B股": "ths_total_bshare_stock"}.get(share_type)
    if share_code:
        specs["security_total_shares"] = (share_code,)
    columns = [f for f in FIELDS if f in specs]
    matrix = []
    for day in days:
        row = []
        for field in columns:
            indicator, *args = specs[field]
            parts = [f'"{indicator}"', f'"{code}"', f'"{day}"'] + [
                f'"{arg}"' if isinstance(arg, str) else str(arg) for arg in args]
            row.append('=@thsiFinD(' + ','.join(parts) + ')')
        matrix.append(row)
    return columns, matrix


def fetch_quote(root, mc, start, end, security):
    code = f"{mc.code}.{mc.suffix}"
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    days = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    columns, matrix = formulas(code, days, security.get("股份类型"))
    started = time.monotonic()
    try:
        result = ifind_excel.fetch_matrix(matrix, visible=False)
        if len(result["values"]) != len(days) or any(len(row) != len(columns) for row in result["values"]):
            raise RuntimeError("Excel 返回矩阵尺寸与请求不一致")
        errors = result.get("errors") or []
        bad_columns = {item["column"] for item in errors}
        data = {field: [{"date": day, "value": result["values"][i][j], "source": SOURCE}
                        for i, day in enumerate(days)]
                for j, field in enumerate(columns) if j not in bad_columns}
        notes = [f"{columns[item['column']]} {days[item['row']]}: {item['error']}" for item in errors]
        if "security_total_shares" not in columns:
            notes.append("股份类型缺失或未识别，证券总股本未取数；不默认归类为A股")
        audit.log_request(root, source=SOURCE, market=mc.market, code=code,
            api="Excel:thsiFinD", fields=columns, start=start, end=end,
            ok=not errors, elapsed=time.monotonic() - started,
            error="；".join(notes) if errors else None)
        return {"ok": bool(data), "source": SOURCE, "data": data, "notes": notes,
                "metrics": result.get("metrics"), "formula_shape": [len(days), len(columns)]}
    except Exception as exc:
        audit.log_request(root, source=SOURCE, market=mc.market, code=code,
            api="Excel:thsiFinD", fields=columns, start=start, end=end,
            ok=False, elapsed=time.monotonic() - started, error=str(exc))
        return {"ok": False, "source": SOURCE, "error": str(exc), "notes": []}
