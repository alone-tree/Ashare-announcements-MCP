# -*- coding: utf-8 -*-
"""iFinD 请求模块（源 × 市场 × 档位）。

当前实现（拉到什么写什么，2026-08-09 用户拍板：字段级独立 json，items [{date,value,source}]）：
- `fetch_us_hfq`：**美股后复权收盘**（iFinD 单源，全程分红再投口径，无回退）→ 写 close_hfq
  （① THS_HQ 探测 .O/.N 后缀 → ② THS_DS `close_price`+`107,OC` 近 5 年序列
   → ③ THS_BD `日期,107,OC` 单点按纽交所交易日历逐日补 5 年前）
- `fetch_us_amount`：**美股成交额**（iFinD 单源）→ 写 amount
  （THS_DS `amt`+`OC` 近 5 年 + THS_BD 单点逐日补 5 年前；**单点非交易日返回空值**，
  必须严格按交易日历，不能用股本方案的日历月末采样）
- `fetch_shares`：**全市场股本**（iFinD 主源）→ 写 total_shares + floating_shares
  （THS_DS 近 5 年逐日 + THS_BD 月频单点补更早，日历月末采样）
- `fetch_statements`：**A/北交所三表**（2026-10-14 拍板切源，见架构设计 §3.8）
  （THS_BD 报表科目单点，每报告期一次调用带全部 318 科目，报表类型只取 100=合并；
  科目主数据=Excel 模板三表 sheet（financial_subjects.py）；THS_DS 不支持报表科目序列，
  多期一律逐期单点，单点不限年限；增量=晚于缓存最新期的报告期 + 各表最新期重取）

**铁律：iFinD 参数严禁猜测/试探变体**——所有参数写法来自官方手册与实测
（字段与数据源支持情况.md §7/§9，2026-08-09 用户提供公式速查）。
月度配额（用户提供官方信息）：THS_BD 60万 / THS_DS 60万 / THS_HQ 100万数据点，独立限额不共享。
国内服务，清代理直连。登录惰性一次（THS_iFinDLogin），退出 THS_iFinDLogout。
"""

from __future__ import annotations

import math
import os
import time
from datetime import date, timedelta

import iFinDPy as ths
import yaml

from market_data_mcp import audit, cache, financial_cache, financial_subjects
from market_data_mcp.routing import MarketCode, to_ifind

# iFinD 为国内服务：清代理直连（与新浪/东财一致）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

SOURCE = "ifind"

_LOGIN_STATE = {"done": False}
_SUFFIX_CACHE: dict[str, str] = {}

# 纽交所交易日历代码（美股 NYSE/NASDAQ/AMEX 统一日历，2026-08-09 实测）
_NYSE_CALENDAR = "212010"


def _load_accounts(root: str) -> list[tuple[str, str]]:
    """从 config.yaml 读 iFinD 账号列表（多账号容灾：按顺序尝试登录）。

    配置位置：{root}/config.yaml（root=MARKET_DATA_ROOT 或开发库根），回退 os.getcwd()。
    格式：
      ifind:
        accounts:
          - account: xxx
            password: yyy
    """
    for base in (root, os.getcwd()):
        path = os.path.join(base, "config.yaml")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
            accounts = ((config or {}).get("ifind") or {}).get("accounts") or []
            pairs = [(str(item["account"]), str(item["password"]))
                     for item in accounts if item.get("account") and item.get("password")]
            if pairs:
                return pairs
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"config.yaml 解析失败（{path}）：{exc}") from exc
    raise RuntimeError("config.yaml 中未找到 ifind.accounts（用户版根目录/当前目录）")


def _ensure_login(root: str) -> None:
    if _LOGIN_STATE["done"]:
        return
    accounts = _load_accounts(root)
    errors = []
    for acc, pwd in accounts:
        code = ths.THS_iFinDLogin(acc, pwd)
        if code == 0:
            _LOGIN_STATE["done"] = True
            return
        errors.append(f"{acc}（errorcode={code}）")
    raise RuntimeError(f"iFinD 全部账号登录失败：{'；'.join(errors)}")


def _clean_value(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _detect_suffix(root: str, base: str) -> str:
    """THS_HQ 探测美股 .O/.N 后缀（周线有数据即后缀正确）。结果进程内缓存。"""
    if base in _SUFFIX_CACHE:
        return _SUFFIX_CACHE[base]
    end_d = date.today()
    start_d = end_d - timedelta(days=10)
    for s in (".O", ".N"):
        r = ths.THS_HQ(base + s, "close", "Interval:W", start_d.isoformat(), end_d.isoformat())
        if r.errorcode == 0 and r.data is not None and len(r.data) > 0:
            _SUFFIX_CACHE[base] = s
            return s
    raise RuntimeError(f"美股 {base} 的 iFinD 后缀探测失败（.O/.N 均无数据）")


def _trade_days(start: str, end: str) -> list[str]:
    """纽交所交易日列表（THS_Date_Query 212010，返回逗号分隔日期串）。"""
    r = ths.THS_Date_Query(_NYSE_CALENDAR, "mode:1,dateType:0,period:D,dateFormat:0", start, end)
    if r.errorcode != 0 or not r.data:
        raise RuntimeError(f"iFinD 交易日历请求失败：{r.errmsg}")
    return [d for d in str(r.data).split(",") if d]


def _five_years_ago(today: date) -> date:
    try:
        return today.replace(year=today.year - 5)
    except ValueError:  # 2/29 无对应日
        return date(today.year - 5, 12, 31)


def _write_field(root: str, code: str, market: str, field: str, fresh: list[dict]) -> dict | None:
    """写单个字段缓存（同源合并）。fresh 为 [{date, value}]。返回 date_range。"""
    items = [{"date": r["date"], "value": r["value"], "source": SOURCE} for r in fresh]
    existing = cache.read_cache(root, code, field)
    existing_items = existing["items"] if existing else None
    merged = cache.merge_items(existing_items, items)
    date_range = None
    if merged:
        date_range = {"start": merged[0]["date"], "end": merged[-1]["date"]}
    cache.write_cache(root, code, field,
                      meta={"code": code, "market": market, "field": field,
                            "source": SOURCE, "date_range": date_range},
                      items=merged)
    return date_range


def _fetch_us_daily(
    root: str,
    mc: MarketCode,
    *,
    indicator: str,
    param: str,
    field: str,
    adjust: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """iFinD 美股逐日序列通用链路（hfq close / amount 共用）：

    ① THS_HQ 探测 .O/.N 后缀 → ② THS_DS 近 5 年序列（窗口从今天倒推，服务端视角）
    → ③ THS_BD 单点按纽交所交易日历（THS_Date_Query 212010）逐日补 5 年前，先近后远。
    返回 {ok, source, fields, error, notes}；部分失败不丢弃（notes 标注）。
    """
    code = f"{mc.code}.{mc.suffix}"
    t0 = time.time()
    try:
        _ensure_login(root)
        full = mc.code + _detect_suffix(root, mc.code)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_HQ/THS_iFinDLogin",
                          fields=indicator, adjust=adjust, start=start, end=end,
                          ok=False, elapsed=elapsed, error=str(exc))
        return {"ok": False, "source": SOURCE, "fields": {}, "error": str(exc), "notes": None}

    notes: list[str] = []
    today = date.today()
    ds_start = _five_years_ago(today)
    end_d = min(end or today.isoformat(), today.isoformat())
    fresh: list[dict] = []

    # ② THS_DS 近 5 年序列（仅当请求段与 5 年窗口有交集）
    if end_d >= ds_start.isoformat():
        ds_beg = max(start or ds_start.isoformat(), ds_start.isoformat())
        r = ths.THS_DS(full, indicator, param, "", ds_beg, end_d)
        if r.errorcode != 0:
            elapsed = time.time() - t0
            audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS",
                              fields=indicator, adjust=adjust, start=ds_beg, end=end_d,
                              ok=False, elapsed=elapsed, error=str(r.errmsg))
            return {"ok": False, "source": SOURCE, "fields": {},
                    "error": f"iFinD THS_DS 请求失败：{r.errmsg}", "notes": None}
        if r.data is not None and len(r.data):
            for _, row in r.data.iterrows():
                fresh.append({"date": str(row["time"]), "value": _clean_value(row[indicator])})
            audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS",
                              fields=f"{indicator}({param})", adjust=adjust, start=ds_beg, end=end_d,
                              ok=True, elapsed=time.time() - t0)

    # ③ THS_BD 单点补 5 年前（严格按交易日历，先近后远；跳过缓存已覆盖日期）
    if start is not None and start < ds_start.isoformat():
        existing = cache.read_cache(root, code, field)
        covered = {r["date"] for r in existing["items"] if r.get("source") == SOURCE} if existing else None
        days = [d for d in _trade_days(start, (ds_start - timedelta(days=1)).isoformat())]
        if covered:
            days = [d for d in days if d not in covered]
        fail = 0
        for d in reversed(days):  # 先近后远：中断只丢最老数据
            r = ths.THS_BD(full, indicator, f"{d},{param}")
            if r.errorcode != 0 or r.data is None or len(r.data) == 0:
                fail += 1
                if fail <= 3:
                    notes.append(f"{d} 单点失败")
                continue
            fresh.append({"date": d, "value": _clean_value(r.data.iloc[0][indicator])})
            time.sleep(0.05)  # 串行限速，防配额过快
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_BD",
                          fields=f"{indicator}({param})", adjust=adjust, start=start,
                          end=(ds_start - timedelta(days=1)).isoformat(), ok=fail == 0,
                          elapsed=time.time() - t0, error=f"失败 {fail} 个单点" if fail else None)
        if fail:
            notes.append(f"单点补全失败 {fail} 个交易日（缺失范围见日志）")

    if not fresh:
        # 请求成功但无新行：已有缓存只刷新 updated_at，启动固定 10 分钟重试窗口；
        # 无缓存时不创建空文件。
        date_range = cache.refresh_cache(root, code, field)
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                          fields=indicator, adjust=adjust, start=start, end=end,
                          ok=True, elapsed=elapsed)
        fields = {field: date_range} if date_range is not None else {}
        return {"ok": True, "source": SOURCE, "fields": fields,
                "error": None, "notes": notes or None}

    date_range = _write_field(root, code, mc.market, field, fresh)
    audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                      fields=f"{indicator}({param})", adjust=adjust, start=start, end=end,
                      ok=True, elapsed=time.time() - t0)
    return {"ok": True, "source": SOURCE, "fields": {field: date_range},
            "error": None, "notes": notes or None}


def fetch_us_hfq(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求美股后复权收盘（iFinD，分红再投）→ 写 close_hfq（date/value/source）。"""
    return _fetch_us_daily(root, mc, indicator="close_price", param="107,OC",
                           field="close_hfq", adjust="hfq", start=start, end=end)


def fetch_us_amount(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求美股成交额 amt（iFinD，单源无回退）→ 写 amount（date/value/source）。

    公式（用户提供官方版，2026-08-09 实测）：THS_DS('AAPL.O','amt','OC','',...) 近 5 年
    仅交易日行；THS_BD('AAPL.O','amt','日期,OC') 单点，非交易日返回空值——
    5 年前补全必须严格按交易日历逐日（不能用股本方案的日历月末采样）。
    """
    return _fetch_us_daily(root, mc, indicator="amt", param="OC",
                           field="amount", start=start, end=end)


def _month_ends(start: str, end: str) -> list[str]:
    """[start, end] 内每月日历月末日（THS_BD 非交易日自动返回最近交易日值，
    日历月末请求 = 该月最后一个交易日股本，与交易日历月末一致，省日历调用）。"""
    import calendar

    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        d = f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
        if d > end:
            break  # 升序：该月月末已超出 end，后续月份更大
        out.append(d)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fetch_shares(
    root: str,
    mc: MarketCode,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """请求股本（total_shares/floating_shares）→ 分写两个字段 json。

    iFinD 近 5 年 THS_DS 序列 + 更早 THS_BD 月频单点（先近后远），部分失败不丢弃（notes 标注）。
    代码格式：A/B/北交所原样（600519.SH/920002.BJ），港股 4 位带前导零（0700.HK），
    美股探测 .O/.N。返回 {ok, source, fields, error, notes}。
    """
    code = f"{mc.code}.{mc.suffix}"
    t0 = time.time()
    try:
        _ensure_login(root)
        if mc.market == "US":
            full = mc.code + _detect_suffix(root, mc.code)
        else:
            from market_data_mcp.routing import to_ifind
            full = to_ifind(mc)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_HQ/THS_iFinDLogin",
                          fields="total_shares;floating_shares", start=start, end=end,
                          ok=False, elapsed=elapsed, error=str(exc))
        return {"ok": False, "source": SOURCE, "fields": {}, "error": str(exc), "notes": None}

    notes: list[str] = []
    today = date.today()
    ds_start = _five_years_ago(today)
    end_d = min(end or today.isoformat(), today.isoformat())
    fresh: list[dict] = []

    # ① THS_DS 近 5 年逐日
    if end_d >= ds_start.isoformat():
        ds_beg = max(start or ds_start.isoformat(), ds_start.isoformat())
        r = ths.THS_DS(full, "total_shares;floating_shares", ";", "", ds_beg, end_d)
        if r.errorcode != 0:
            elapsed = time.time() - t0
            audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS",
                              fields="total_shares;floating_shares", start=ds_beg, end=end_d,
                              ok=False, elapsed=elapsed, error=str(r.errmsg))
            return {"ok": False, "source": SOURCE, "fields": {},
                    "error": f"iFinD THS_DS 股本请求失败：{r.errmsg}", "notes": None}
        if r.data is not None and len(r.data):
            for _, row in r.data.iterrows():
                fresh.append({"date": str(row["time"]),
                              "total_shares": _clean_value(row["total_shares"]),
                              "floating_shares": _clean_value(row["floating_shares"])})

    # ② THS_BD 月频单点补 [start, ds_start)，先近后远；跳过缓存已覆盖日期
    if start is not None and start < ds_start.isoformat():
        existing = cache.read_cache(root, code, "total_shares")
        covered = {r["date"] for r in existing["items"] if r.get("source") == SOURCE} if existing else None
        months = _month_ends(start, (ds_start - timedelta(days=1)).isoformat())
        if covered:
            months = [d for d in months if d not in covered]
        fail = 0
        for d in reversed(months):  # 先近后远：中断只丢最老数据
            r = ths.THS_BD(full, "total_shares;floating_shares", f"{d};{d}")
            if r.errorcode != 0 or r.data is None or len(r.data) == 0:
                fail += 1
                if fail <= 3:
                    notes.append(f"{d} 单点失败")
                continue
            row = r.data.iloc[0]
            fresh.append({"date": d,
                          "total_shares": _clean_value(row["total_shares"]),
                          "floating_shares": _clean_value(row["floating_shares"])})
            time.sleep(0.05)
        if fail:
            notes.append(f"股本月频补全失败 {fail} 个月点（缺失范围见日志）")
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_BD",
                          fields="total_shares;floating_shares", start=start,
                          end=(ds_start - timedelta(days=1)).isoformat(), ok=fail == 0,
                          elapsed=time.time() - t0, error=f"失败 {fail} 个单点" if fail else None)

    if not fresh:
        # 请求成功但无新行：仅刷新该市场实际归属 iFinD 的已有股本字段。
        fields = {}
        share_fields = ("total_shares", "floating_shares") if mc.market in ("HK", "US") else ("total_shares",)
        for field in share_fields:
            date_range = cache.refresh_cache(root, code, field)
            if date_range is not None:
                fields[field] = date_range
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                          fields="total_shares;floating_shares", start=start, end=end,
                          ok=True, elapsed=elapsed)
        return {"ok": True, "source": SOURCE, "fields": fields,
                "error": None, "notes": notes or None}

    fields = {
        "total_shares": _write_field(root, code, mc.market, "total_shares",
                                     [{"date": r["date"], "value": r["total_shares"]} for r in fresh]),
    }
    # floating_shares 字段归属：A/北交所 = sina（outstanding_share，全历史逐日，用户拍板口径）；
    # 港美股 = iFinD（新浪港股/美股无股本列）。避免同字段同日期双写（2026-08-09 用户指出）。
    if mc.market in ("HK", "US"):
        fields["floating_shares"] = _write_field(
            root, code, mc.market, "floating_shares",
            [{"date": r["date"], "value": r["floating_shares"]} for r in fresh])
    audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                      fields="total_shares;floating_shares", start=start, end=end,
                      ok=True, elapsed=time.time() - t0)
    return {"ok": True, "source": SOURCE, "fields": fields, "error": None, "notes": notes or None}


# --- A/北交所三表（THS_BD 报表科目，架构设计 §3.8） ---

_STATEMENTS = ("balance", "income", "cash_flow")
_STATEMENT_BACKFILL_YEARS = 30  # 无缓存回补的硬上限，防死循环
_STATEMENT_EMPTY_STOP = 8       # 回补时连续 N 期三表全空即停止（约等于上市前）
_QUARTER_MD = ("03-31", "06-30", "09-30", "12-31")
_QUARTER_NAMES = {"03-31": "一季报", "06-30": "半年报", "09-30": "三季报", "12-31": "年报"}
_AUDIT_DD_CODE = "ths_regular_report_actual_dd_stock"  # 实际披露日 → metadata.NOTICE_DATE


def _statement_codes() -> tuple[list[str], dict[str, list[str]]]:
    """全部科目码（固定顺序）+ 按报表分组。"""
    by_statement = {statement: financial_subjects.codes_for(statement) for statement in _STATEMENTS}
    all_codes = [code for statement in _STATEMENTS for code in by_statement[statement]]
    return all_codes, by_statement


def _quarter_ends_desc(today: date) -> list[str]:
    """从当期季度末往回的季度末列表（ISO 日期，降序），下限 today-N 年。"""
    floor = (today.replace(year=today.year - _STATEMENT_BACKFILL_YEARS)).isoformat()
    out: list[str] = []
    year, quarter = today.year, (today.month - 1) // 3
    while True:
        md = _QUARTER_MD[quarter]
        day = f"{year:04d}-{md}"
        if day < floor:
            break
        out.append(day)
        quarter -= 1
        if quarter < 0:
            year, quarter = year - 1, 3
    return out


def _read_statements_bundle(root: str, full_code: str) -> dict | None:
    try:
        return financial_cache.read_bundle(root, full_code)
    except (OSError, ValueError):
        return None


def _bundle_latest_per_statement(bundle: dict | None) -> dict[str, str | None]:
    latest: dict[str, str | None] = {}
    for statement in _STATEMENTS:
        reports = ((bundle or {}).get(statement) or {}).get("reports") or []
        dates = [str(r["report_date"]) for r in reports if r.get("report_date")]
        latest[statement] = max(dates) if dates else None
    return latest


def _current_version_report(report: dict) -> dict | None:
    """把缓存报告还原成 merge_statement 的 fresh 形状（保持 present_in_latest_refresh 语义）。"""
    current_id = report.get("current_version_id")
    for version in report.get("versions") or []:
        if version.get("version_id") == current_id:
            return {
                "report_date": str(report["report_date"]),
                "metadata": version.get("metadata") or {},
                "items": version.get("items") or [],
            }
    return None


def _statement_value(value):
    """THS_BD 单值 → JSON 安全原值（None/数值/字符串；其余 str()，不加工不改口径）。"""
    value = _clean_value(value)
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _thbd_statement_period(root: str, full_code: str, period: str,
                           all_codes: list[str]) -> dict[str, object]:
    """一次 THS_BD 调用取单期全科目（报表类型 100=合并）；瞬时失败重试一次。"""
    api_period = period.replace("-", "")  # SDK 报告期格式 YYYYMMDD
    params = ";".join([f"{api_period},100"] * len(all_codes))
    last_error = None
    for _attempt in (1, 2):
        started = time.time()
        result = ths.THS_BD(full_code, ";".join(all_codes), params)
        if result.errorcode == 0 and result.data is not None and len(result.data) > 0:
            frame = result.data
            row = frame.iloc[0]
            values: dict[str, object] = {}
            for code in all_codes:
                values[code] = _statement_value(row[code]) if code in frame.columns else None
            audit.log_request(root, source=SOURCE, market="A", code=full_code, api="THS_BD",
                              fields=f"statements({len(all_codes)}科目)", start=period, end=period,
                              ok=True, elapsed=time.time() - started)
            return values
        last_error = getattr(result, "errmsg", None) or f"errorcode={result.errorcode}"
        time.sleep(0.5)
    audit.log_request(root, source=SOURCE, market="A", code=full_code, api="THS_BD",
                      fields=f"statements({len(all_codes)}科目)", start=period, end=period,
                      ok=False, error=str(last_error), elapsed=time.time() - started)
    raise RuntimeError(f"THS_BD {period} 三表请求失败：{last_error}")


def _period_report(period: str, values: dict[str, object],
                   by_statement: dict[str, list[str]]) -> tuple[dict[str, dict], bool]:
    """单期取数结果 → {statement: report}；三表全空期不产出（返回 all_empty=True）。"""
    notice_date = values.get(_AUDIT_DD_CODE)
    metadata: dict[str, object] = {
        "REPORT_DATE_NAME": f"{period[:4]}{_QUARTER_NAMES[period[5:]]}",
        "CURRENCY": "CNY",
    }
    if notice_date is not None:
        metadata["NOTICE_DATE"] = str(notice_date)[:10]
    reports: dict[str, dict] = {}
    has_value = False
    for statement in _STATEMENTS:
        items = [
            {
                "item_code": code,
                "item_name": financial_subjects.display_name(code),
                "amount": values.get(code),
                "source": SOURCE,
            }
            for code in by_statement[statement]
        ]
        if any(item["amount"] is not None for item in items):
            has_value = True
        reports[statement] = {"report_date": period, "metadata": dict(metadata), "items": items}
    return reports, not has_value


def fetch_statements(
    root: str,
    mc: MarketCode,
    existing_metadata: dict | None = None,
) -> dict:
    """A/北交所三表（iFinD 单源）：无缓存全历史回补（连续 8 期全空停止），
    有缓存增量（晚于各表最新期的报告期 + 各表最新期重取）。
    返回形状与 financial_statements.fetch 一致：{ok, source, statements, metadata, error, notes}。
    任何组成部分失败返回 ok=false，不写缓存（service 回退旧缓存）。"""
    full_code = to_ifind(mc)
    t0 = time.time()
    notes: list[str] = []
    all_codes, by_statement = _statement_codes()
    try:
        _ensure_login(root)
    except Exception as exc:  # noqa: BLE001
        audit.log_request(root, source=SOURCE, market=mc.market, code=full_code,
                          api="THS_iFinDLogin", fields="statements", ok=False,
                          elapsed=time.time() - t0, error=str(exc))
        return {"ok": False, "source": SOURCE, "statements": None, "metadata": None,
                "error": f"iFinD 登录失败：{exc}", "notes": None}

    bundle = _read_statements_bundle(root, f"{mc.code}.{mc.suffix}")
    latest = _bundle_latest_per_statement(bundle)
    today = date.today()
    quarters_desc = _quarter_ends_desc(today)

    fresh_by_statement: dict[str, list[dict]] = {statement: [] for statement in _STATEMENTS}
    fetched_count = 0
    if bundle is None or all(value is None for value in latest.values()):
        # 全历史回补：先近后远，连续 _STATEMENT_EMPTY_STOP 期全空即停（约等于上市前）
        collected: list[dict[str, dict]] = []  # 降序 [{statement: report}]
        empty_streak = 0
        seen_value = False
        stopped = False
        for period in quarters_desc:
            if period > today.isoformat():
                continue  # 未到期的报告期不请求
            try:
                values = _thbd_statement_period(root, full_code, period, all_codes)
            except RuntimeError as exc:
                return {"ok": False, "source": SOURCE, "statements": None, "metadata": None,
                        "error": str(exc), "notes": None}
            reports, all_empty = _period_report(period, values, by_statement)
            collected.append(reports)
            if all_empty:
                empty_streak += 1
                if empty_streak >= _STATEMENT_EMPTY_STOP:
                    collected = collected[:-empty_streak]
                    if seen_value:
                        stopped = True
                    break
                continue
            seen_value = True
            empty_streak = 0
        if not seen_value:
            error = f"iFinD 三表请求完成但 {full_code} 无任何报告期数据（连续 {_STATEMENT_EMPTY_STOP} 期全空）"
            audit.log_request(root, source=SOURCE, market=mc.market, code=full_code,
                              api="THS_BD", fields="statements", ok=False,
                              elapsed=time.time() - t0, error=error)
            return {"ok": False, "source": SOURCE, "statements": None, "metadata": None,
                    "error": error, "notes": None}
        if not stopped:
            notes.append(f"触及 {_STATEMENT_BACKFILL_YEARS} 年回补下限（{quarters_desc[-1]}），可能未到上市前")
        collected.reverse()  # 升序
        notes.append(f"全历史回补 {len(collected)} 期（最早 {collected[0]['balance']['report_date']}）")
        fetched_count = len(collected)
        for reports in collected:
            for statement in _STATEMENTS:
                fresh_by_statement[statement].append(reports[statement])
    else:
        # 增量：晚于各表最新期的报告期 + 各表最新期重取（修订检测）
        oldest_needed = min(value for value in latest.values() if value)
        fetch_periods = [p for p in quarters_desc if oldest_needed < p <= today.isoformat()]
        for value in latest.values():
            if value and value not in fetch_periods and value <= today.isoformat():
                fetch_periods.append(value)
        fetch_periods.sort(reverse=True)
        notes.append(f"增量取 {len(fetch_periods)} 期（>= {oldest_needed}，含最新期重取）")
        fetched_count = len(fetch_periods)
        for period in fetch_periods:
            try:
                values = _thbd_statement_period(root, full_code, period, all_codes)
            except RuntimeError as exc:
                return {"ok": False, "source": SOURCE, "statements": None, "metadata": None,
                        "error": str(exc), "notes": None}
            reports, all_empty = _period_report(period, values, by_statement)
            if all_empty:
                continue
            for statement in _STATEMENTS:
                fresh_by_statement[statement].append(reports[statement])

    # 已有缓存报告按当前版本重新产出，保持 present_in_latest_refresh 语义（内容不变则不新增版本）
    statements: dict[str, list[dict]] = {}
    if bundle is not None:
        for statement in _STATEMENTS:
            carried = []
            for report in (bundle.get(statement) or {}).get("reports") or []:
                current = _current_version_report(report)
                if current is not None:
                    carried.append(current)
            statements[statement] = carried + fresh_by_statement[statement]
    else:
        statements = fresh_by_statement
    for statement in _STATEMENTS:
        statements[statement].sort(key=lambda report: report["report_date"])

    audit.log_request(root, source=SOURCE, market=mc.market, code=full_code,
                      api="THS_BD", fields=f"statements({fetched_count}期)",
                      ok=True, elapsed=time.time() - t0)
    return {
        "ok": True,
        "source": SOURCE,
        "statements": statements,
        "metadata": {
            "code": f"{mc.code}.{mc.suffix}",
            "market": mc.market,
            "sources": {"statements": SOURCE},
            "filings": [],
        },
        "error": None,
        "notes": notes or None,
    }
