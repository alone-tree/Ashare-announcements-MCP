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
- `probe_latest_report`：**最新报告期探针**（`ths_regular_report_latest_rp_stock`，1 数据点/代码）
- `fetch_statements(root, mc, periods)`：**A/北交所三表 + 报表信息 meta**（2026-10-14 拍板切源，见架构设计 §3.8）
  （THS_BD 报表科目单点，每报告期一次调用带全部科目，报表类型只取 100=合并；
  科目主数据=iFinD 编辑器清单三表 330 + meta 报表信息 4（financial_subjects.py，
  2026-10-19 扩全；meta 独立成表不混三表，同批调用取回）；
  THS_DS 不支持报表科目序列，多期一律逐期单点，单点不限年限；
  2026-10-21 改为惰性拉取：只取调用方点名的报告期，单期失败不中断其余期，
  不再自行回补历史，也不再写缓存——每期合并与提交由 service 逐期完成）

**铁律：iFinD 参数严禁猜测/试探变体**——所有参数写法来自官方手册与实测
（字段与数据源支持情况.md §7/§9，2026-08-09 用户提供公式速查）。
月度配额（用户提供官方信息）：THS_BD 60万 / THS_DS 60万 / THS_HQ 100万数据点，独立限额不共享。
国内服务，清代理直连。登录惰性一次（THS_iFinDLogin），退出 THS_iFinDLogout。
"""

from __future__ import annotations

import math
import os
import time
import threading
import contextlib
import sys
from types import SimpleNamespace
from datetime import date, timedelta

with contextlib.redirect_stdout(sys.stderr):
    import iFinDPy as ths
import yaml

from market_data_mcp import audit, cache, financial_subjects
from market_data_mcp.routing import MarketCode, to_ifind

# iFinD 为国内服务：清代理直连（与新浪/东财一致）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

SOURCE = "ifind"

_LOGIN_STATE = {"done": False}
_SESSION_LOCK = threading.RLock()
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
            raise RuntimeError(f"config.yaml 解析失败（{path}，{type(exc).__name__}）") from None
    raise RuntimeError("config.yaml 中未找到 ifind.accounts（用户版根目录/当前目录）")


def _ensure_login(root: str) -> None:
    with _SESSION_LOCK:
        if _LOGIN_STATE["done"] and _LOGIN_STATE.get("root") == root:
            return
        accounts = _load_accounts(root)
        errors = []
        for index, (acc, pwd) in enumerate(accounts):
            code = _sdk_call("THS_iFinDLogin", acc, pwd)
            if code == 0:
                _LOGIN_STATE.update(done=True, root=root, index=index)
                return
            errors.append(f"账号{index + 1}（errorcode={code}）")
        raise RuntimeError(f"iFinD 全部账号登录失败：{'；'.join(errors)}")


def _sdk_call(api, *args):
    # SDK的提示不得混入MCP stdio或CLI的JSON stdout。
    with contextlib.redirect_stdout(sys.stderr):
        return getattr(ths, api)(*args)


def request_ifind(root: str, api: str, *args, required_columns=()):
    """串行执行一个原始SDK批次；业务空值不换号，错误有限重试后换号。"""
    with _SESSION_LOCK:
        accounts = _load_accounts(root)
        current = _LOGIN_STATE.get("index", 0)
        order = list(range(len(accounts)))
        if _LOGIN_STATE.get("done") and _LOGIN_STATE.get("root") == root and current in order:
            order.remove(current)
            order.insert(0, current)
        errors = []
        for index in order:
            acc, pwd = accounts[index]
            repaired = False
            retries = 0
            if not (_LOGIN_STATE.get("done") and _LOGIN_STATE.get("root") == root
                    and _LOGIN_STATE.get("index") == index):
                if _LOGIN_STATE.get("done"):
                    _sdk_call("THS_iFinDLogout")
                _LOGIN_STATE["done"] = False
                login = _sdk_call("THS_iFinDLogin", acc, pwd)
                if login != 0:
                    errors.append(f"账号{index + 1}: 登录错误码{login}")
                    continue
                _LOGIN_STATE.update(done=True, root=root, index=index)
            while True:
                started = time.time()
                try:
                    result = _sdk_call(api, *args)
                    code = getattr(result, "errorcode", None)
                    message = str(getattr(result, "errmsg", ""))
                    frame = getattr(result, "data", None)
                    valid = not (required_columns and frame is not None and len(frame) > 0
                                 and not set(required_columns).issubset(frame.columns))
                    if code == 0 and valid:
                        audit.log_request(root, source=SOURCE, market="", code=str(args[0]) if args else "",
                            api=f"sdk:{api}", fields=str(args[1]) if len(args) > 1 else None,
                            ok=True, elapsed=time.time() - started)
                        return result
                    if code == 0:
                        message = "响应缺少约定字段"
                except Exception as exc:
                    code, message = "exception", str(exc)
                for account, password in accounts:
                    message = message.replace(account, "[账号]").replace(password, "[凭据]")
                audit.log_request(root, source=SOURCE, market="", code=str(args[0]) if args else "",
                    api=f"sdk:{api}", fields=str(args[1]) if len(args) > 1 else None,
                    ok=False, elapsed=time.time() - started, error=f"账号{index + 1}: {code} {message}")
                if "you have not done login operation" in message.lower() and not repaired:
                    repaired = True
                    _LOGIN_STATE["done"] = False
                    if _sdk_call("THS_iFinDLogin", acc, pwd) == 0:
                        _LOGIN_STATE.update(done=True, root=root, index=index)
                        continue
                elif (code == -205 or "request data error" in message.lower()) and retries < 3:
                    time.sleep((0.5, 2.0, 5.0)[retries])
                    retries += 1
                    continue
                errors.append(f"账号{index + 1}: {code} {message}")
                break
        return SimpleNamespace(errorcode=-1, errmsg="；".join(errors), data=None)


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
        r = request_ifind(root, "THS_HQ", base + s, "close", "Interval:W", start_d.isoformat(), end_d.isoformat())
        if r.errorcode == 0 and r.data is not None and len(r.data) > 0:
            _SUFFIX_CACHE[base] = s
            return s
    raise RuntimeError(f"美股 {base} 的 iFinD 后缀探测失败（.O/.N 均无数据）")


def _trade_days(start: str, end: str, root: str | None = None) -> list[str]:
    """纽交所交易日列表（THS_Date_Query 212010，返回逗号分隔日期串）。"""
    r = request_ifind(root or _LOGIN_STATE.get("root") or os.getcwd(), "THS_Date_Query", _NYSE_CALENDAR, "mode:1,dateType:0,period:D,dateFormat:0", start, end)
    if r.errorcode != 0 or not r.data:
        raise RuntimeError(f"iFinD 交易日历请求失败：{r.errmsg}")
    return [d for d in str(r.data).split(",") if d]


def _five_years_ago(today: date) -> date:
    try:
        return today.replace(year=today.year - 5)
    except ValueError:  # 2/29 无对应日
        return date(today.year - 5, 12, 31)


def _field_batch(fresh: list[dict]) -> list[dict]:
    """仅规范化一个字段批次，写缓存由行情调度层执行。"""
    return sorted([{"date": r["date"], "value": r["value"], "source": SOURCE} for r in fresh],
                  key=lambda row: row["date"])


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
        r = request_ifind(root, "THS_DS", full, indicator, param, "", ds_beg, end_d)
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
            r = request_ifind(root, "THS_BD", full, indicator, f"{d},{param}")
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
        existing = cache.read_cache(root, code, field)
        date_range = existing["meta"].get("date_range") if existing else None
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                          fields=indicator, adjust=adjust, start=start, end=end,
                          ok=True, elapsed=elapsed)
        fields = {field: date_range} if date_range is not None else {}
        return {"ok": True, "source": SOURCE, "fields": fields, "data": {field: []},
                "error": None, "notes": notes or None}

    batch = _field_batch(fresh)
    date_range = {"start": batch[0]["date"], "end": batch[-1]["date"]}
    audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                      fields=f"{indicator}({param})", adjust=adjust, start=start, end=end,
                      ok=True, elapsed=time.time() - t0)
    return {"ok": True, "source": SOURCE, "fields": {field: date_range}, "data": {field: batch},
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


def fetch_fx(root: str, mc: MarketCode, start: str | None = None,
             end: str | None = None) -> dict:
    """汇率HQ原值批次；分段及缓存提交由forex调度，见架构§2.7。"""
    from market_data_mcp.forex import LIVE_START

    code = f"{mc.code}.{mc.suffix}"
    start = max(start or LIVE_START, LIVE_START)
    end = end or date.today().isoformat()
    result = request_ifind(root, "THS_HQ", code, "close", "", start, end,
                           required_columns=("time", "close"))
    if result.errorcode != 0:
        return {"ok": False, "source": SOURCE, "data": {},
                "error": f"iFinD THS_HQ请求失败：{result.errmsg}", "notes": None}
    frame = result.data
    records = []
    if frame is not None:
        for row in frame.to_dict("records"):
            stamp = str(row["time"])[:10]
            if start <= stamp <= end:
                records.append({"date": stamp, "value": _clean_value(row["close"])})
    return {"ok": True, "source": SOURCE, "data": {"close": _field_batch(records)},
            "error": None, "notes": None}


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
        r = request_ifind(root, "THS_DS", full, "total_shares;floating_shares", ";", "", ds_beg, end_d)
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
            r = request_ifind(root, "THS_BD", full, "total_shares;floating_shares", f"{d};{d}")
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
            existing = cache.read_cache(root, code, field)
            date_range = existing["meta"].get("date_range") if existing else None
            if date_range is not None:
                fields[field] = date_range
        elapsed = time.time() - t0
        audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                          fields="total_shares;floating_shares", start=start, end=end,
                          ok=True, elapsed=elapsed)
        return {"ok": True, "source": SOURCE, "fields": fields, "data": {field: [] for field in share_fields},
                "error": None, "notes": notes or None}

    data = {
        "total_shares": _field_batch([{"date": r["date"], "value": r["total_shares"]} for r in fresh]),
    }
    # floating_shares 字段归属：A/北交所 = sina（outstanding_share，全历史逐日，用户拍板口径）；
    # 港美股 = iFinD（新浪港股/美股无股本列）。避免同字段同日期双写（2026-08-09 用户指出）。
    if mc.market in ("HK", "US"):
        data["floating_shares"] = _field_batch([{"date": r["date"], "value": r["floating_shares"]} for r in fresh])
    fields = {field: {"start": records[0]["date"], "end": records[-1]["date"]} for field, records in data.items()}
    audit.log_request(root, source=SOURCE, market=mc.market, code=code, api="THS_DS/THS_BD",
                      fields="total_shares;floating_shares", start=start, end=end,
                      ok=True, elapsed=time.time() - t0)
    return {"ok": True, "source": SOURCE, "fields": fields, "data": data, "error": None, "notes": notes or None}


# --- A/北交所三表（THS_BD 报表科目，架构设计 §3.8） ---

_STATEMENTS = ("balance", "income", "cash_flow", "meta")
_QUARTER_NAMES = {"03-31": "一季报", "06-30": "半年报", "09-30": "三季报", "12-31": "年报"}
_AUDIT_DD_CODE = "ths_regular_report_actual_dd_stock"  # 实际披露日 → metadata.NOTICE_DATE
_LATEST_RP_CODE = "ths_regular_report_latest_rp_stock"  # 最新报告期探针（1 数据点/代码）


def _statement_codes() -> tuple[list[str], dict[str, list[str]]]:
    """全部科目码（固定顺序）+ 按报表分组。"""
    by_statement = {statement: financial_subjects.codes_for(statement) for statement in _STATEMENTS}
    all_codes = [code for statement in _STATEMENTS for code in by_statement[statement]]
    return all_codes, by_statement


def bundle_matches_subjects(bundle: dict | None) -> bool:
    """缓存版本科目码是否全部属于 iFinD 注册表（东财旧缓存整体重建的判定）。"""
    if bundle is None:
        return False
    for statement in _STATEMENTS:
        for report in ((bundle.get(statement) or {}).get("reports") or []):
            for version in report.get("versions") or []:
                items = version.get("items") or []
                if items and str(items[0].get("item_code") or "") in financial_subjects.BY_CODE:
                    continue
                return False
    return True


def probe_latest_report(root: str, mc: MarketCode) -> dict[str, object]:
    """探最新报告期（`ths_regular_report_latest_rp_stock`，1 数据点/代码）。

    返回 {ok, report_date, error}；report_date 为 YYYY-MM-DD，失败为 None。
    与取数一样退避重试三次（同花顺偶发 -205 数秒内自愈）。"""
    full_code = to_ifind(mc)
    started = time.time()
    try:
        _ensure_login(root)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "report_date": None, "error": f"iFinD 登录失败：{exc}"}
    last_error = None
    for attempt in range(1):  # 有限重试、会话修复与换号统一由request_ifind承担
        result = request_ifind(root, "THS_BD", full_code, _LATEST_RP_CODE, date.today().isoformat())
        if result.errorcode == 0 and result.data is not None and len(result.data) > 0:
            frame = result.data
            raw = frame.iloc[0, -1]
            text = str(raw).strip()[:8]
            audit.log_request(root, source=SOURCE, market=mc.market, code=full_code,
                              api="THS_BD", fields="latest_report_probe", ok=True,
                              elapsed=time.time() - started)
            if len(text) == 8 and text.isdigit():
                return {"ok": True, "report_date": f"{text[:4]}-{text[4:6]}-{text[6:]}", "error": None}
            return {"ok": False, "report_date": None, "error": f"探针返回值无法解析：{raw!r}"}
        last_error = getattr(result, "errmsg", None) or f"errorcode={result.errorcode}"
    audit.log_request(root, source=SOURCE, market=mc.market, code=full_code,
                      api="THS_BD", fields="latest_report_probe", ok=False,
                      error=str(last_error), elapsed=time.time() - started)
    return {"ok": False, "report_date": None, "error": f"最新报告期探测失败：{last_error}"}


def _statement_value(value):
    """THS_BD 单值 → JSON 安全原值（None/数值/字符串；其余 str()，不加工不改口径）。"""
    value = _clean_value(value)
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _thbd_statement_period(root: str, full_code: str, period: str,
                           all_codes: list[str]) -> dict[str, object]:
    """一次 THS_BD 调用取单期全科目（报表类型 100=合并）；瞬时失败退避重试三次。

    2026-10-19 实测：同花顺偶发 errorcode=-205「request data error」，数秒内自愈
    （同参数单查立即成功），0.5 秒单次重试扛不住，改为 0.5/2/5 秒三次退避重试。"""
    api_period = period.replace("-", "")  # SDK 报告期格式 YYYYMMDD
    params = ";".join([f"{api_period},100"] * len(all_codes))
    last_error = None
    started = time.time()
    for attempt in range(1):  # 不在业务层叠加SDK重试
        result = request_ifind(root, "THS_BD", full_code, ";".join(all_codes), params)
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
    audit.log_request(root, source=SOURCE, market="A", code=full_code, api="THS_BD",
                      fields=f"statements({len(all_codes)}科目)", start=period, end=period,
                      ok=False, error=str(last_error), elapsed=time.time() - started)
    raise RuntimeError(f"THS_BD {period} 报表科目请求失败：{last_error}")


def _period_report(period: str, values: dict[str, object],
                   by_statement: dict[str, list[str]]) -> tuple[dict[str, dict], bool]:
    """单期取数结果 → {statement: report}；全部表（含 meta）全空期不产出（返回 all_empty=True）。"""
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
    periods: list[str],
) -> dict:
    """A/北交所三表（iFinD 单源）：只取调用方点名的报告期，逐期独立成败。

    返回 {ok, source, periods: {报告期: {statement: report}}, failed, empty, error, notes}。
    ok=False 只表示登录失败；单期失败进 failed 不影响其余期；上游对未上市/无数据的
    期返回全空，该期进 empty、不产出报告也不计失败。不写缓存——每期合并与提交由
    service 逐期完成（惰性拉取，2026-10-21）。"""
    full_code = to_ifind(mc)
    t0 = time.time()
    all_codes, by_statement = _statement_codes()
    try:
        _ensure_login(root)
    except Exception as exc:  # noqa: BLE001
        audit.log_request(root, source=SOURCE, market=mc.market, code=full_code,
                          api="THS_iFinDLogin", fields="statements", ok=False,
                          elapsed=time.time() - t0, error=str(exc))
        return {"ok": False, "source": SOURCE, "periods": {}, "failed": [], "empty": [],
                "error": f"iFinD 登录失败：{exc}", "notes": None}

    fetched: dict[str, dict[str, dict]] = {}
    failed: list[dict[str, str]] = []
    empty: list[str] = []
    for period in periods:
        try:
            values = _thbd_statement_period(root, full_code, period, all_codes)
        except RuntimeError as exc:
            failed.append({"period": period, "error": str(exc)})
            continue
        reports, all_empty = _period_report(period, values, by_statement)
        if all_empty:
            empty.append(period)
            continue
        fetched[period] = reports

    audit.log_request(root, source=SOURCE, market=mc.market, code=full_code,
                      api="THS_BD", fields=f"statements({len(periods)}期)",
                      ok=bool(fetched) or not periods, elapsed=time.time() - t0,
                      error="; ".join(f"{item['period']}:{item['error']}" for item in failed) or None)
    return {
        "ok": True,
        "source": SOURCE,
        "periods": fetched,
        "failed": failed,
        "empty": empty,
        "error": None,
        "notes": None,
    }
