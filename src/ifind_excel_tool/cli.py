# -*- coding: utf-8 -*-
"""ifind_excel_tool CLI：stdin JSON → stdout JSON，顶层字段 cmd。

先跑 {"cmd":"help"} 看导航（start_here 按需求指明该调哪个命令）。
主要命令：
  search       查证券代码，必须指定kind=股票/指数/外汇（每页10行，offset翻页）
  fetch_scene  按固定场景取数（优先用这个）；带export_path导CSV
  report       一条命令出完整报告：取数、换算、绘图、拼Markdown、落盘
  draw         读行情CSV按模板绘图（kline_volume等四模板）
  lookup/run/text  查公式、执行公式矩阵、取文本字段（场景没有才用）
  help/help_scene/help_indicators/scenes/scene_info  各种帮助查询
  open/status/close  Excel生命周期

详细用法见 usage.md。设计意图：让AI行动前先查清有什么、该用什么，
避免绕过现成场景自己拼公式踩坑（港股五位代码、非交易日前推等）。
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date as _date, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ifind_excel_tool import chart as _chart, engine, help as _help, resample as _resample, scenes as _scenes, search as _search, report as _report
from ifind_excel_tool import indicator_index as _indicators, indicators as _get

LIB = Path(__file__).resolve().parent / "formula_library"


def _load(name: str) -> list[dict]:
    path = LIB / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# 匹配强度：数字越小越靠前。用途是让 AI 一眼看出哪条才是用户要的科目，
# 避免「搜净资产取第一条却拿到归母口径」这类错。
MATCH_EXACT_INDICATOR = 1   # 指标码完全相同
MATCH_EXACT_NAME = 2        # 正式名称完全相同
MATCH_EXACT_ALIAS = 3       # 别名完全相同
MATCH_NAME_CONTAINS = 4     # 正式名称包含
MATCH_ALIAS_CONTAINS = 5    # 别名包含
MATCH_INDICATOR_CONTAINS = 6  # 指标码包含
MATCH_DEFINITION = 7        # 仅定义正文命中


def _match_rank(record: dict, keyword: str) -> int | None:
    """返回该记录对关键词的匹配强度；不命中返回 None。

    多词关键词（空格分隔）沿用历史语义：全部词都要出现在检索范围内才命中，
    匹配强度按整串关键词在字段中的位置判定。
    """
    words = keyword.split()
    name = (record.get("name") or "").strip()
    aliases = [a.strip() for a in (record.get("aliases") or [])]
    indicator = record.get("indicator") or ""
    definition = record.get("definition") or ""
    path = record.get("path") or ""

    # 全部词必须出现在合并检索范围内，否则不命中（保持原有可用性）
    haystack = " ".join([path, name, indicator, " ".join(aliases), definition])
    if not all(w in haystack for w in words):
        return None

    # 单字关键词才能做完全匹配判定；多词按包含处理
    if len(words) == 1:
        if keyword == indicator:
            return MATCH_EXACT_INDICATOR
        if keyword == name:
            return MATCH_EXACT_NAME
        if keyword in aliases:
            return MATCH_EXACT_ALIAS
        if keyword in name:
            return MATCH_NAME_CONTAINS
        if any(keyword in a for a in aliases):
            return MATCH_ALIAS_CONTAINS
        if keyword in indicator:
            return MATCH_INDICATOR_CONTAINS
        return MATCH_DEFINITION

    if all(w in name for w in words):
        return MATCH_NAME_CONTAINS
    if any(all(w in a for w in words) for a in aliases):
        return MATCH_ALIAS_CONTAINS
    if all(w in indicator for w in words):
        return MATCH_INDICATOR_CONTAINS
    return MATCH_DEFINITION


def lookup(req: dict) -> dict:
    kw = (req.get("keyword") or "").strip()
    limit = int(req.get("limit") or 5)
    offset = max(0, int(req.get("offset") or 0))
    if not kw:
        return {"ok": False, "error": "keyword 不能为空"}
    verified = _load("verified-formulas.jsonl")
    general = _load("general-notes.jsonl")
    ranked = []
    for order, r in enumerate(verified):
        rank = _match_rank(r, kw)
        if rank is None:
            continue
        item = {k: r[k] for k in ("path", "name", "indicator", "formula_template",
                                   "parameters", "unit", "verification", "notes")}
        # reading_mode 决定该走数值通道还是文本通道，缺了它 AI 会用错命令
        item["reading_mode"] = r.get("reading_mode") or "matrix"
        item["aliases"] = r.get("aliases") or []
        item["match"] = {MATCH_EXACT_INDICATOR: "指标码完全匹配",
                         MATCH_EXACT_NAME: "名称完全匹配",
                         MATCH_EXACT_ALIAS: "别名完全匹配",
                         MATCH_NAME_CONTAINS: "名称包含",
                         MATCH_ALIAS_CONTAINS: "别名包含",
                         MATCH_INDICATOR_CONTAINS: "指标码包含",
                         MATCH_DEFINITION: "仅定义正文命中"}[rank]
        item["general_notes"] = [{"id": g["id"], "note": g["note"]}
                                 for g in general if r["path"].startswith(g["scope"])]
        ranked.append((rank, order, item))
    # 先按匹配强度，同强度保持库内原有顺序
    ranked.sort(key=lambda x: (x[0], x[1]))
    hits = [item for _, _, item in ranked]
    return {"ok": True, "keyword": kw, "source": "verified",
            "hits": hits[offset:offset + limit], "total": len(hits),
            "offset": offset, "limit": limit}


def run(req: dict) -> dict:
    matrix = req.get("matrix")
    if not matrix or not isinstance(matrix[0], list):
        return {"ok": False, "error": "matrix 必须是非空二维数组"}
    result = engine.fetch_matrix(matrix, visible=req.get("visible"),
                                 timeout=float(req.get("timeout") or 300))
    return {"ok": True, "source": "ifind_excel", **result}


def text(req: dict) -> dict:
    formulas = req.get("formulas")
    if not formulas:
        return {"ok": False, "error": "formulas 不能为空"}
    result = engine.fetch_formulas(formulas, visible=req.get("visible"),
                                   timeout=float(req.get("timeout") or 120), text_ok=True)
    return {"ok": True, "source": "ifind_excel", **result}


def close(req: dict) -> dict:
    return {"ok": True, "source": "ifind_excel",
            **engine.close_excel(timeout=float(req.get("timeout") or 30))}


def status(req: dict) -> dict:
    """只读查询；Excel 未打开时不会启动它。"""
    return {"ok": True, "source": "ifind_excel",
            **engine.status(timeout=float(req.get("timeout") or 15))}


def open_excel(req: dict) -> dict:
    return {"ok": True, "source": "ifind_excel",
            **engine.open_excel(visible=req.get("visible", True),
                                timeout=float(req.get("timeout") or 60))}


def _fetch_table_scene(req: dict, spec: dict) -> dict:
    """表函数场景：一条公式返回整张表，需要写公式后等函数把数据写到下方。

    与矩阵场景的差别在等待方式：矩阵靠单元格是否还在显示抓取/提取，
    表函数是往下方逐步追加行，只能按行数稳定判断。实测约 1 秒到位。
    """
    params = dict(req.get("params") or {})
    for key in spec.get("inputs") or []:
        if key not in params and req.get(key) is not None:
            params[key] = req[key]
    for key, value in (spec.get("defaults") or {}).items():
        if value == "today_ymd" and key not in params:
            params[key] = f"{datetime.now():%Y%m%d}"
        elif key not in params:
            params[key] = value
    try:
        built = _scenes.build_table(spec, params=params)
    except ValueError as exc:
        return {"ok": False, "error": str(exc),
                "expected_inputs": spec.get("inputs"),
                "input_labels": spec.get("input_labels") or {}}

    connected, _ = engine._find_workbook()
    if connected is None:
        return {"ok": False, "error": "专用工作簿未打开，请先执行 {\"cmd\":\"open\"}"}
    app, book, pid = connected
    sheet = book.Worksheets("data")
    engine._ensure_functions(app)
    sheet.Cells.ClearContents()

    region = req.get("read_region") or "A1:J2000"
    sheet.Range("A1").Formula2 = built["formula"]

    limit = float(req.get("timeout") or 120)
    started = time.time()
    prev_sig, stable, rows_now = None, 0, 0
    block = []
    while time.time() - started < limit:
        time.sleep(0.8)
        try:
            block = sheet.Range(region).Value2
        except Exception:
            continue
        if not isinstance(block, tuple):
            block = ((block,),)
        rows_now = sum(1 for row in block
                       if isinstance(row, tuple) and any(v is not None for v in row))
        sig = str(block)
        if sig == prev_sig:
            stable += 1
            if stable >= 2 and rows_now > 1:
                break
        else:
            stable = 0
            prev_sig = sig

    records = _scenes.shape_table(spec, block,
                                  meta={"params": params, "formula": built["formula"]})
    units = spec.get("field_units") or {}
    for record in records:
        for field, unit in units.items():
            if field in record:
                record[f"{field}__unit"] = unit
    resp = {"ok": True, "source": "ifind_excel", "scene": spec.get("name"),
            "kind": "table", "formula": built["formula"],
            "params": params, "rows": len(records), "records": records,
            "elapsed_seconds": round(time.time() - started, 2)}
    export_path = req.get("export_path")
    if export_path or len(records) > int(req.get("auto_export_rows") or 200):
        target = export_path or str(
            Path(__file__).resolve().parent / "exports"
            / f"{spec.get('name')}_{params.get('idx_code') or 'table'}_"
              f"{datetime.now():%Y%m%d-%H%M%S}.csv")
        resp["export"] = _scenes.to_csv(records, target)
        if not export_path:
            resp["records"] = records[:20]
            resp["truncated"] = True
    return resp


def find_indicator(req: dict) -> dict:
    """在全部能力里搜指标，返回用法（命令、参数、返回形状）。

    范围覆盖公式型、场景型、报表函数型、自定义派生指标、指标组、特殊能力，
    不按存储形态割裂。看到想要的指标后用 get 命令取数。
    """
    return _indicators.search(req.get("keyword") or "",
                              limit=int(req.get("limit") or 10),
                              offset=int(req.get("offset") or 0),
                              kind=req.get("kind") or "")


def get_indicator(req: dict) -> dict:
    """按指标名或指标码取数，类型自动分派。

    给指标名（如「毛利率」「固定资产」）或指标码（如 ths_operating_cost_stock），
    底层自动决定走公式、多候选取值还是派生计算，调用方不用判断。
    """
    return _get.get(req.get("indicator") or "",
                    code=(req.get("code") or "").strip(),
                    date=(req.get("report_date") or "").strip(),
                    params=req.get("params"))


def search(req: dict) -> dict:
    """按名称或代码查证券，返回可直接用于取数的ifind代码（每页最多10行）。"""
    return _search.search(
        req.get("keyword") or "",
        offset=int(req.get("offset") or 0),
        limit=int(req.get("limit") or _search.PAGE_SIZE),
        kind=req.get("kind") or "",
    )


def scenes(req: dict) -> dict:
    """列出固定场景，让调用方知道自己能直接取哪几套数据。"""
    return {"ok": True, "scenes": _scenes.list_scenes()}


def scene_info(req: dict) -> dict:
    """看某个场景会取哪些字段，取数前先确认再取。"""
    spec = _scenes.load_scene(req.get("scene") or "")
    return {"ok": True, "name": spec.get("name"),
            "description": spec.get("description", ""),
            "dims": spec.get("dims") or {},
            "defaults": spec.get("defaults") or {},
            "periods": ["daily", "weekly", "monthly"] if spec.get("resample") else ["daily"],
            "fields": [{"label": f["label"],
                        "indicator": f.get("indicator") or "+".join(f.get("candidates") or []),
                        "pick": f.get("pick")} for f in spec["fields"]]}


def _probe_report_date(code: str) -> str | None:
    """探最新已披露报告期，返回 YYYY-MM-DD；探不到返回 None。

    依据：verified-formulas.jsonl 的 ths_regular_report_latest_rp_stock（A股）
    与 ths_latest_rp_hks（港股），均为已验证的文本公式，取插件原文写法，
    不猜参数。交易日用当天，公式按公告日返回截止日。
    """
    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    indicator = "ths_latest_rp_hks" if suffix == "HK" else "ths_regular_report_latest_rp_stock"
    today = _date.today().isoformat()
    formula = f'=@thsiFinD("{indicator}","{code}","{today}")'
    result = engine.fetch_formulas([formula], text_ok=True)
    values = result.get("values") or []
    raw = values[0] if values else None
    if not isinstance(raw, str):
        return None
    m = re.fullmatch(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", raw.strip()[:10])
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}-{mo}-{d}"


def fetch_scene(req: dict) -> dict:
    """按固定场景取数。换公司与日期只改 code 和 report_date。

    历史行情场景支持 period=daily/weekly/monthly（默认 daily）：始终先取日K，
    再按需本地聚合为周/月线，不直接取周月K。
    财报场景不传 report_date 时自动探最新已披露期，探不到明确报错；
    传 report_dates 列表时一次取回多期，跳过探测。
    dims 可覆盖场景的维度取值（分红传年份、历史估值传日期等）。
    """
    name = req.get("scene") or ""
    spec = _scenes.load_scene(name)
    if spec.get("kind") == "table":
        return _fetch_table_scene(req, spec)
    period = req.get("period") or "daily"
    if period not in ("daily", "weekly", "monthly"):
        return {"ok": False, "error": f"不支持的周期 {period}（支持 daily/weekly/monthly）"}
    resample_spec = spec.get("resample") or {}
    if period != "daily" and not resample_spec:
        return {"ok": False, "error": f"场景「{name}」不支持 period={period}（仅日线）"}
    dims_override = req.get("dims")
    if dims_override:
        spec = {**spec, "dims": {**(spec.get("dims") or {}), **dims_override}}
    codes = req.get("codes") or []
    single = (req.get("code") or "").strip()
    if single:
        codes = [single]
    if not codes:
        return {"ok": False, "error": "code 或 codes 至少要给一个"}
    report_dates = req.get("report_dates")
    if report_dates and not isinstance(report_dates, list):
        return {"ok": False, "error": "report_dates 必须是日期字符串数组"}
    report_date = req.get("report_date")
    probed = None
    if not report_date and not report_dates and spec.get("date_kind") == "report":
        # 财报类场景 date 是报告期。留空不能填空串（实测返回全零），
        # 必须先探最新已披露期；多代码探第一个，不同公司报告期通常一致。
        probed = _probe_report_date(codes[0])
        if not probed:
            return {"ok": False, "error": f"无法确定最新报告期，请显式传 report_date（探测 {codes[0]} 失败）"}
        report_date = probed
    library = _scenes._load_library()
    results = []
    for one in codes:
        built = _scenes.build(spec, library, code=one,
                              report_date=report_date,
                              params=req.get("params"),
                              start=req.get("start"), end=req.get("end"),
                              report_dates=report_dates)
        raw = engine.fetch_matrix(built["matrix"], visible=req.get("visible"),
                                  timeout=float(req.get("timeout") or 300),
                                  text_ok=True)
        records = _scenes.shape(spec, built["plan"], built["columns"],
                                built["combos"], raw["values"])
        for record in records:
            record["code"] = one
        if period != "daily":
            records = _resample.resample_ohlcv(
                records, period, resample_spec.get("field_map") or {})
        results.extend(records)
    resp = {"ok": True, "source": "ifind_excel", "scene": spec.get("name"),
            "period": period, "fields": len(spec["fields"]),
            "rows": len(results), "records": results}
    if probed:
        resp["report_date"] = probed
        resp["report_date_probed"] = True
    if report_dates:
        resp["report_dates"] = report_dates
    # 导出口径：调用方给了路径就写文件；没给且行数超过阈值，自动落盘避免把大结果塞进对话
    export_path = req.get("export_path")
    if export_path or len(results) > int(req.get("auto_export_rows") or 200):
        target = export_path or str(
            Path(__file__).resolve().parent / "exports"
            / f"{spec.get('name')}_{(req.get('code') or (req.get('codes') or [''])[0]).replace('.', '_')}"
              f"_{datetime.now():%Y%m%d-%H%M%S}.csv")
        resp["export"] = _scenes.to_csv(results, target)
        if not export_path:
            resp["records"] = results[:20]  # 大结果只回前20行示意，完整数据在文件里
            resp["truncated"] = True
    return resp


def help_overview(req: dict) -> dict:
    """一页看清所有场景与族归属。"""
    return _help.overview()


def help_scene(req: dict) -> dict:
    """某场景要什么参数、有哪些字段、默认值是什么。"""
    return _help.scene_params(req.get("scene") or "")


def help_indicators(req: dict) -> dict:
    """按市场或关键词列出库里可用的指标。"""
    return _help.list_indicators(req.get("market") or "",
                                 req.get("keyword") or "",
                                 int(req.get("limit") or 100))


def draw(req: dict) -> dict:
    """按模板绘图：读已导出的行情CSV（data_path），输出PNG。"""
    return _chart.draw(req)


REPORT_COLUMNS = 7
REPORT_BLOCKS = ("工商信息", "十大股东", "IPO信息", "历史行情", "估值快照", "分红",
                 "资产负债表", "利润表", "现金流量表", "分产品", "分地区",
                 "客户供应商", "盈利预测", "历史估值")


def _report_periods(latest: str, columns: int = REPORT_COLUMNS) -> list[str]:
    """按旧脚本与 iFinD 模板共用的口径铺报告期列。

    最新期若不是年报，第2列放去年同期（同比），其余补最近年报；
    最新期是年报时全部按年报铺。资产负债表也照此，不单独处理。
    """
    year = int(latest[:4])
    periods = [latest]
    if not latest.endswith("12-31"):
        periods.append(f"{year - 1}{latest[4:]}")
    annual_start = year - 1
    for offset in range(0, columns + 2):
        if len(periods) >= columns:
            break
        periods.append(f"{annual_start - offset}-12-31")
    return periods[:columns]


def _segment_periods(latest: str, columns: int = REPORT_COLUMNS) -> list[str]:
    """营收结构/分地区/客户供应商只在年报和中报披露，不能用三季报/一季报。

    口径：最新中报或年报 + 去年同类中报/年报 + 逐年年报，去重后共7列。
    例：最新2026三季报 → 2026中报、2025中报、2025年、2024年、2023年、2022年、2021年。
    最新是年报时全用年报：2025年、2024年……2019年。
    """
    year, md = int(latest[:4]), latest[5:]
    if md == "09-30":
        first = f"{year}-06-30"
    elif md == "03-31":
        first = f"{year - 1}-12-31"
    else:
        first = latest
    fy, fmd = first[:4], first[5:]
    out = [first, f"{int(fy) - 1}-{fmd}"]
    annual_start = int(fy) if fmd == "12-31" else int(fy) - 1
    for offset in range(columns + 4):
        if len(out) >= columns:
            break
        period = f"{annual_start - offset}-12-31"
        if period not in out:
            out.append(period)
    # 去重保序
    seen, result = set(), []
    for period in out:
        if period not in seen:
            seen.add(period)
            result.append(period)
        if len(result) >= columns:
            break
    return result


def _scene_groups(name: str) -> dict[str, str]:
    spec = _scenes.load_scene(name)
    return {field["label"]: field.get("group") or ""
            for field in spec.get("fields") or []}


def _fetch_block(scene: str, **kwargs) -> dict:
    payload = {"cmd": "fetch_scene", "scene": scene, **kwargs}
    result = fetch_scene(payload)
    if not result.get("ok"):
        return {"ok": False, "scene": scene, "error": result.get("error")}
    return result


def report(req: dict) -> dict:
    """一条命令出完整报告：取数、换算、绘图、拼Markdown、落盘。

    传 code 与 output（输出目录）；company 省略时取工商信息里的证券简称。
    events 可给事件CSV路径，画进市值与收盘价双轴图。
    """
    code = (req.get("code") or "").strip()
    output = (req.get("output") or "").strip()
    if not code:
        return {"ok": False, "error": "code 必须提供"}
    if not output:
        return {"ok": False, "error": "output 必须提供（输出目录）"}
    end_date = req.get("end_date") or (_date.today()).isoformat()
    chart_start = req.get("chart_start") or "2016-01-01"
    warnings: list[str] = []

    latest = _probe_report_date(code)
    if not latest:
        return {"ok": False, "error": f"无法确定最新报告期（探测 {code} 失败）"}
    periods = _report_periods(latest)
    segment_periods = _segment_periods(latest)
    annuals = [p for p in periods if p.endswith("12-31")]
    annual_year = int(annuals[0][:4]) if annuals else int(periods[0][:4]) - 1
    forecast_years = [str(annual_year + offset) for offset in (1, 2, 3)]

    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    data: dict[str, list[dict]] = {}
    csv_paths: dict[str, str] = {}

    def take(block: str, **kwargs) -> None:
        result = _fetch_block(block, code=code, **kwargs)
        if not result.get("ok"):
            warnings.append(f"{block}取数失败：{result.get('error')}")
            data[block] = []
            return
        data[block] = result.get("records") or []

    basic = _fetch_block("工商信息", code=code)
    if not basic.get("ok"):
        return {"ok": False, "error": f"工商信息取数失败：{basic.get('error')}"}
    data["工商信息"] = basic.get("records") or []
    profile = data["工商信息"][0] if data["工商信息"] else {}
    company = (req.get("company") or profile.get("证券简称")
               or profile.get("公司中文名称") or code).strip()

    def export(block: str) -> str:
        path = out_dir / f"{company}-{block}.csv"
        csv_paths[block] = str(path)
        return str(path)

    take("十大股东", report_date=latest, export_path=export("十大股东"))
    take("IPO信息", report_date=end_date)
    # 分红当年（如2026）也要列，虽然多数公司中报未宣告；取数年份=年报年份+当年
    dividend_years = sorted({p[:4] for p in annuals} | {str(end_date)[:4]}, reverse=True)
    take("分红", dims={"year": dividend_years})
    take("资产负债表", report_dates=periods)
    # 营收占比需要中报的营业总收入/成本作分母，利润表要同时覆盖三表期次与营收期次
    income_periods = sorted(set(periods) | set(segment_periods), reverse=True)
    take("利润表", report_dates=income_periods)
    take("现金流量表", report_dates=periods)
    take("分产品", report_dates=segment_periods)
    take("分地区", report_dates=segment_periods)
    take("客户供应商", report_dates=segment_periods)
    take("盈利预测", report_date=end_date, dims={"year": forecast_years})
    take("历史估值", dims={"date": annuals})
    take("估值快照", report_date=end_date)

    quote_path = export("历史行情")
    quote = _fetch_block("历史行情", code=code, start=chart_start,
                         end=end_date, export_path=quote_path)
    if quote.get("ok"):
        data["历史行情"] = quote.get("records") or []
    else:
        data["历史行情"] = []
        warnings.append(f"历史行情取数失败：{quote.get('error')}")

    # 非图表板块的CSV：用已取到的记录直接写，避免重复调一次取数
    for block in REPORT_BLOCKS + ("报表元信息",):
        if block in ("历史行情",) or block not in data:
            continue
        path = out_dir / f"{company}-{block}.csv"
        csv_paths[block] = str(path)
        _scenes.to_csv(data[block], path)

    chart_file = None
    if data.get("历史行情"):
        png = out_dir / f"{company}-行情图.png"
        drawn = _chart.draw({"template": "close_mcap_events", "data_path": quote_path,
                             "output": str(png), "events": req.get("events")})
        if drawn.get("ok"):
            chart_file = png.name
        else:
            warnings.append(f"绘图失败：{drawn.get('error')}")

    # 违规次数依赖实际上市日，单独取：工商信息场景里没有这个动态参数
    violations = "—"
    ipo_date = str(profile.get("上市日期") or "")
    if ipo_date:
        violation_result = run({"cmd": "run", "matrix": [[
            f'=@thsiFinD("ths_int_illegality_num_stock","{code}","{ipo_date}","{end_date}")']]})
        values = violation_result.get("values") or []
        number = values[0][0] if values and values[0] else None
        if isinstance(number, (int, float)):
            violations = f"{number:,.0f}"

    # 报表元信息：发布时间、审计单位、审计意见，一次矩阵取全部期。
    # 一季度/三季度无审计数据，上游返回空或0属正常，原样留空。
    meta_rows = []
    meta_formulas = []
    for period in periods:
        # 披露日期只接受3个参数；审计单位与审计意见第4参数传100（地域类别）
        meta_formulas.append(
            f'=@thsiFinD("ths_regular_report_actual_dd_stock","{code}","{period}")')
        meta_formulas.append(
            f'=@thsiFinD("ths_audit_institution_stock","{code}","{period}",100)')
        meta_formulas.append(
            f'=@thsiFinD("ths_audit_opinion_type_stock","{code}","{period}",100)')
    # 三项都是文本指标，必须走 text（text_ok=True），否则文本被当错误置空
    meta_result = text({"cmd": "text", "formulas": meta_formulas})
    if meta_result.get("ok"):
        values = meta_result.get("values") or []
        for index, period in enumerate(periods):
            chunk = values[index * 3:index * 3 + 3]
            published = chunk[0] if len(chunk) > 0 else None
            auditor = chunk[1] if len(chunk) > 1 else None
            opinion = chunk[2] if len(chunk) > 2 else None
            meta_rows.append({
                "date": period,
                "披露日期": str(published)[:10] if isinstance(published, str) else "",
                "审计单位": auditor if isinstance(auditor, str) else "",
                "审计意见": opinion if isinstance(opinion, str) else "",
            })
    else:
        warnings.append(f"报表元信息取数失败：{meta_result.get('error')}")
    data["报表元信息"] = meta_rows

    groups = {name: _scene_groups(name)
              for name in ("资产负债表", "利润表", "现金流量表")}
    markdown_text = _report.build_report(
        company=company, code=code, periods=periods, segment_periods=segment_periods,
        data=data, groups=groups,
        chart_file=chart_file, data_date=end_date, violations=violations,
        warnings=warnings)
    md_path = out_dir / f"{company}-报告骨架-{stamp}.md"
    md_path.write_text(markdown_text, encoding="utf-8")

    return {"ok": True, "output": str(md_path), "company": company, "code": code,
            "latest_report": latest, "periods": periods,
            "forecast_years": forecast_years, "chart": chart_file,
            "csv": csv_paths, "warnings": warnings,
            "chars": len(markdown_text)}


CMDS = {"lookup": lookup, "run": run, "text": text, "close": close,
        "status": status, "open": open_excel, "search": search,
        "scenes": scenes, "scene_info": scene_info, "fetch_scene": fetch_scene,
        "find": find_indicator, "get": get_indicator,
        "report": report,
        "draw": draw,
        "help": help_overview, "help_scene": help_scene, "help_indicators": help_indicators}


def main() -> None:
    try:
        req = json.loads(sys.stdin.read())
    except json.JSONDecodeError as error:
        print(json.dumps({"ok": False, "error": f"输入不是合法JSON：{error}"},
                         ensure_ascii=False))
        return
    if not isinstance(req, dict):
        print(json.dumps({"ok": False, "error": "输入必须是JSON对象"},
                         ensure_ascii=False))
        return
    cmd = req.get("cmd")
    if cmd not in CMDS:
        resp = {"ok": False, "error": f"未知 cmd：{cmd}；支持 {list(CMDS)}"}
    else:
        try:
            resp = CMDS[cmd](req)
        except Exception as exc:
            resp = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    # 结果含®等字符时，GBK终端print会抛UnicodeEncodeError，强制UTF-8输出
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(json.dumps(resp, ensure_ascii=False))


if __name__ == "__main__":
    main()
