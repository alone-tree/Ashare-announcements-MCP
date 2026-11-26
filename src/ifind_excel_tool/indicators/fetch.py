# -*- coding: utf-8 -*-
"""第二块 取数：按科目定义取回数据，类型自动分派。

对调用方只有一个入口 get()：给科目名或指标码，拿回加工好的结果，不用判断底层
是原始公式、批量公式、衍生科目、科目组合还是特殊能力。

三条纪律：
- 依赖合并取数：一个科目组合的多项依赖一次矩阵提交，不重复跑 Excel。
- 算式只走四则运算白名单，不执行任意代码。
- 缺依赖、分母为零时该值不可用并给原因，不静默回退成 0。
"""
from __future__ import annotations

import ast
import operator

from ifind_excel_tool.execution import engine
from ifind_excel_tool.formulas import library
from ifind_excel_tool.indicators import definitions

_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub,
            ast.Mult: operator.mul, ast.Div: operator.truediv}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def evaluate(definition: dict, values: dict):
    """按四则运算白名单求值。不可用（缺依赖、分母为零）时返回 None 并留原因。"""
    expr = definition.get("expr")
    if not expr:
        return None
    missing = [d["label"] for d in definition.get("deps") or []
               if d["label"] not in values]
    if missing:
        return None
    try:
        number = _eval_expr(expr, values)
    except ZeroDivisionError:
        return None
    except ValueError:
        return None
    decimals = definition.get("decimals")
    if isinstance(decimals, int) and decimals >= 0:
        number = round(number, decimals)
    return number


def _eval_expr(expr: str, names: dict[str, float]) -> float:
    """对只含四则运算与变量名的表达式求值，不用 eval。"""
    tree = ast.parse(expr, mode="eval")

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError(f"算式里出现非数值常量：{node.value!r}")
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise ValueError(f"算式引用了未提供的依赖：{node.id}")
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](walk(node.operand))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "max" and not node.keywords):
            return max(walk(arg) for arg in node.args)
        raise ValueError(f"算式含不支持的写法：{ast.dump(node)}")

    return walk(tree)


def probe_latest_report(code: str) -> str | None:
    """探最新已披露报告期，返回 YYYY-MM-DD；探不到返回 None。

    用库内已验证的文本公式，不猜参数。交易日用当天，公式按公告日返回截止日。
    """
    import re

    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    indicator = "ths_latest_rp_hks" if suffix == "HK" else "ths_regular_report_latest_rp_stock"
    from datetime import date as _date

    formula = f'=@thsiFinD("{indicator}","{code}","{_date.today().isoformat()}")'
    result = engine.fetch_formulas([formula], text_ok=True)
    values = result.get("values") or []
    raw = values[0] if values else None
    if not isinstance(raw, str):
        return None
    matched = re.fullmatch(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", raw.strip()[:10])
    if not matched:
        return None
    year, month, day = matched.groups()
    return f"{year}-{month}-{day}"


def _probe_if_needed(kind: str, code: str, date: str) -> tuple[str, str | None]:
    """财报类科目不给日期时先探最新已披露报告期，探不到明确报错，不静默取空。

    原始公式不给日期则保持原样：行情类指标有意留空取最新值。
    """
    if date or kind not in ("derived", "package", "select") or not code:
        return date, None
    probed = probe_latest_report(code)
    if not probed:
        raise ValueError(f"无法确定最新报告期，请显式传 report_date（探测 {code} 失败）。"
                         f"{engine.ZERO_VALUE_HINT}")
    return probed, probed


_QUARTER_ENDS = ["03-31", "06-30", "09-30", "12-31"]


def _base_period(t1: str, mode: str) -> str:
    """对比基期。yoy=上年同期；qoq=上一报告期。"""
    year = int(t1[:4])
    if mode == "yoy":
        return f"{year - 1}{t1[4:]}"
    if mode == "qoq":
        index = _QUARTER_ENDS.index(t1[5:])
        if index == 0:
            return f"{year - 1}-12-31"
        return f"{year}-{_QUARTER_ENDS[index - 1]}"
    raise ValueError(f"不支持的对比口径：{mode}")


def _last_n_quarters(count: int, t1: str) -> list[str]:
    """以 t1 为最新一期，往回数 count 个季末报告期。"""
    if t1[5:] not in _QUARTER_ENDS:
        raise ValueError(f"报告期 {t1} 不是季末（03-31/06-30/09-30/12-31），无法铺单季序列")
    index = _QUARTER_ENDS.index(t1[5:])
    year = int(t1[:4])
    out = []
    for offset in range(count):
        position = index - offset
        shift = position // 4
        out.append(f"{year + shift}-{_QUARTER_ENDS[position % 4]}")
    return out


def _package_indicators(*names: str) -> set[str]:
    """收集若干组合的全部底层指标码（含衍生依赖与多候选）。"""
    single = library.load_single()
    derived = definitions.load_derived()
    specs = definitions.load_packages()
    out: set[str] = set()
    for name in names:
        for field in (specs.get(name) or {}).get("fields") or []:
            if field.get("derived"):
                for dep in (derived.get(field["derived"]) or {}).get("deps") or []:
                    out.add(dep["indicator"])
            for candidate in field.get("candidates") or [field.get("indicator")]:
                if candidate and candidate in single:
                    out.add(candidate)
    return out


def _qoq_reason(indicators: list[str]) -> str | None:
    """环比适用性检查。返回 None 表示允许，否则返回给调用方的提示文案。

    单季科目（ths_sq_ 前缀）与资产负债表科目可环比；利润表/现金流量表
    累计口径不提供环比；其余科目同样不支持。
    """
    if any(code.startswith("ths_sq_") for code in indicators):
        return None
    if any(code in _package_indicators("资产负债表", "资产负债表常用科目")
           for code in indicators):
        return None
    if any(code in _package_indicators("利润表", "现金流量表")
           for code in indicators):
        return "累计报不支持环比计算"
    return "仅单季度科目和资产负债表科目支持环比计算"


def _entry_indicators(entry: dict) -> list[str]:
    """一个科目条目背后的真实指标码（衍生取依赖，多候选取全部候选）。"""
    if entry["kind"] == "derived":
        definition = definitions.load_derived().get(entry["name"]) or {}
        return [dep["indicator"] for dep in definition.get("deps") or []]
    return list(entry.get("candidates") or [entry.get("indicator")])


def _growth_result(name: str, decimals, t1: str, t0: str,
                   current, base) -> dict:
    """按公告口径算增速：(本期-基期)/|基期|。基期为负时附标记，不自创算法。"""
    if not isinstance(current, (int, float)):
        return {"ok": False, "indicator": name,
                "error": f"本期（{t1}）无数据，同比/环比不可用"}
    if not isinstance(base, (int, float)):
        return {"ok": False, "indicator": name,
                "error": f"基期（{t0}）无数据，同比/环比不可用"}
    if base == 0:
        return {"ok": False, "indicator": name,
                "error": f"基期（{t0}）为0，增速无定义，不可用"}
    value = round((float(current) - float(base)) / abs(float(base)) * 100,
                  decimals if isinstance(decimals, int) else 2)
    out = {"ok": True, "indicator": name, "value": value, "unit": "%",
           "period": t1, "base_period": t0,
           "current": current, "base": base}
    if base < 0:
        out["base_negative"] = True
    return out


def _growth_value(entry: dict, code: str, date: str,
                  params: dict | None, mode: str) -> dict:
    """对任意科目取同比/环比：基期各取一次该科目的值再算增速。"""
    name = entry["name"]
    if mode not in ("yoy", "qoq"):
        return {"ok": False, "indicator": name,
                "error": f"不支持的对比口径 {mode}（支持 yoy=同比、qoq=环比）"}
    reason = _qoq_reason(_entry_indicators(entry)) if mode == "qoq" else None
    if reason:
        out = {"ok": False, "indicator": name, "error": reason}
        if reason == "累计报不支持环比计算":
            out["note"] = "环比仅对单季度科目和资产负债表科目生效"
        return out
    lookup = entry["indicator"] if entry["kind"] == "formula" else name
    t1 = date
    if not t1:
        t1 = probe_latest_report(code)
    if not t1:
        return {"ok": False, "indicator": name,
                "error": f"无法确定本期报告期，请显式传 report_date（探测 {code} 失败）",
                "hint": engine.ZERO_VALUE_HINT}
    t0 = _base_period(t1, mode)
    current = get(lookup, code=code, date=t1, params=params)
    base = get(lookup, code=code, date=t0, params=params)
    if not current.get("ok"):
        return {"ok": False, "indicator": name,
                "error": f"本期取数失败：{current.get('error')}"}
    if not base.get("ok"):
        return {"ok": False, "indicator": name,
                "error": f"基期取数失败：{base.get('error')}"}
    result = _growth_result(name, entry.get("decimals"), t1, t0,
                            current.get("value"), base.get("value"))
    if result.get("ok"):
        result["code"] = code
    return result


def _growth_from_definition(definition: dict, code: str, date: str) -> dict:
    """衍生同比科目：deps[0] 在本期与基期各取一次，一次矩阵提交。"""
    name = definition["name"]
    mode = definition.get("growth")
    dep = (definition.get("deps") or [None])[0]
    if dep is None:
        return {"ok": False, "indicator": name, "error": "同比科目缺少依赖定义"}
    t1 = date
    if not t1:
        t1 = probe_latest_report(code)
    if not t1:
        return {"ok": False, "indicator": name,
                "error": f"无法确定本期报告期，请显式传 report_date（探测 {code} 失败）",
                "hint": engine.ZERO_VALUE_HINT}
    t0 = _base_period(t1, mode)
    single = library.load_single()
    record = single.get(dep["indicator"])
    if record is None:
        return {"ok": False, "indicator": name,
                "error": f"指标未入库：{dep['indicator']}"}
    formulas = [library.render(record, {"code": code, "date": period,
                                        **(dep.get("params") or {})})
                for period in (t1, t0)]
    block = (engine.fetch_matrix([formulas], text_ok=True).get("values") or [[]])[0]
    current = library.coerce(block[0]) if len(block) > 0 else None
    base = library.coerce(block[1]) if len(block) > 1 else None
    result = _growth_result(name, definition.get("decimals"), t1, t0,
                            current, base)
    if result.get("ok"):
        result["code"] = code
        result["base_negative_label"] = ("扭亏为盈" if base < 0 <= current
                                         else "减亏" if base < 0 and current < 0
                                         else "")
        if not result.get("base_negative_label"):
            result.pop("base_negative_label")
    return result


def _mv_route(code: str) -> str:
    """证券市值的路由：按代码后缀与号段选类别市值公式。美股ADR返回空串。"""
    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    if suffix == "HK":
        return "ths_totalcapitalforsecurities_hk"
    if suffix in ("N", "O", "US", "A", "P", "K"):
        return ""          # 美股ADR/多类别股：无类别股本数据，拒绝而非给错值
    digits = code.split(".")[0]
    if digits.startswith("900") or digits.startswith("200"):
        return "ths_bshare_mv_with_limit_tc_stock"
    return "ths_ashare_mv_include_ls_stock"


_MV_ROUTES = {
    "ths_ashare_mv_include_ls_stock": "A股市值(含限售股)",
    "ths_bshare_mv_with_limit_tc_stock": "B股市值(含限售股,交易币种)",
    "ths_totalcapitalforsecurities_hk": "港股类别市值",
}


def _securities_mv(code: str, date: str, params: dict | None) -> dict:
    """证券市值：类别口径按代码自动路由，B股附带交易币种。"""
    single = library.load_single()
    indicator = _mv_route(code)
    if not indicator:
        return {"ok": False, "indicator": "证券市值", "code": code,
                "error": "美股ADR与多类别股算不出证券市值：iFinD无ADR实际发行量字段，"
                         "「证券总股本」是按全股本÷ADR比例折算的，传入ADR代码得到的是"
                         "约等于公司总市值的数，与主上市代码的证券市值相加即双倍。"
                         "请改用「总市值」（取任一主上市代码）作为公司口径。"}
    record = single.get(indicator)
    if record is None:
        return {"ok": False, "indicator": "证券市值",
                "error": f"指标未入库：{indicator}"}
    context = {"code": code, "date": date, "unit": "1"}
    currency = None
    if indicator == "ths_totalcapitalforsecurities_hk":
        currency = (params or {}).get("currency") or "HKD"
        context["currency"] = currency
    formula = library.render(record, context)
    value = library.coerce(_fetch_one(record, formula))
    out = {"ok": True, "indicator": "证券市值", "code": code, "date": date,
           "value": value, "unit": "元", "source_indicator": indicator,
           "route": _MV_ROUTES[indicator]}
    if indicator == "ths_bshare_mv_with_limit_tc_stock":
        currency_row = single.get("ths_trade_currency_stock")
        currency_value = None
        if currency_row is not None:
            currency_value = _fetch_one(
                currency_row, library.render(currency_row, {"code": code}))
        out["currency"] = str(currency_value).strip() if currency_value is not None else None
        out["note"] = "B股市值按交易币种计价，见 currency 字段，勿直接当人民币。"
    elif indicator == "ths_totalcapitalforsecurities_hk":
        out["currency"] = currency
    return out


def get(name_or_code: str, code: str = "", date: str = "",
        params: dict | None = None, growth: str = "") -> dict:
    """按科目名或指标码取数。类型自动分派，调用方不用判断底层形态。

    growth 可选 yoy（同比）/ qoq（环比）：对任意单科目按公告口径算增速，
    基期自动取上年同期或上一报告期。
    """
    entry = definitions.resolve(name_or_code, code)
    kind = entry["kind"]
    date, probed = _probe_if_needed(kind, code, date)

    if growth and kind in ("formula", "derived", "select") \
            and not (kind == "derived"
                     and (definitions.load_derived().get(entry["name"]) or {}).get("growth")):
        return _growth_value(entry, code, date, params, growth)

    if kind == "special":
        if entry["name"] == "证券市值":
            return _securities_mv(code, date, params)
        latest = probe_latest_report(code)
        if not latest:
            return {"ok": False, "indicator": entry["name"],
                    "error": f"无法确定最新报告期（探测 {code} 失败）",
                    "hint": engine.ZERO_VALUE_HINT}
        return {"ok": True, "indicator": entry["name"], "code": code,
                "value": latest, "unit": "报告期"}

    if kind == "package":
        return get_package(entry["name"], code=code, date=date)

    if kind == "batch":
        return {"ok": False, "indicator": entry["name"],
                "error": f"「{entry['name']}」是批量公式，需要专有输入参数，"
                         f"请用 fetch_batch 指定：{entry.get('required_inputs')}"}

    if kind == "select":
        # 多候选：一次取全部候选，取较大值，与组合内同一套规则
        single = library.load_single()
        formulas = [library.render(single[c], {"code": code, "date": date,
                                               **(params or {})})
                    for c in entry["candidates"]]
        block = (engine.fetch_matrix([formulas], text_ok=True).get("values") or [[]])[0]
        cells = [library.coerce(v) for v in block]
        numbers = [(v, c) for v, c in zip(cells, entry["candidates"])
                   if isinstance(v, (int, float))]
        if not numbers:
            return {"ok": True, "indicator": entry["name"], "value": 0,
                    "unit": entry.get("unit", ""), "candidates": entry["candidates"]}
        value, picked = max(numbers, key=lambda x: x[0])
        out = {"ok": True, "indicator": entry["name"], "value": value,
               "unit": entry.get("unit", ""), "picked": picked,
               "date": date, "date_probed": probed is not None,
               "candidates": entry["candidates"]}
        if len({v for v, _ in numbers}) > 1:
            out["choices"] = {c: v for v, c in zip(cells, entry["candidates"])}
        return out

    if kind == "derived":
        definition = definitions.load_derived()[entry["name"]]
        if definition.get("growth"):
            return _growth_from_definition(definition, code, date)
        values, missing = _fetch_deps(definition.get("deps") or [], code, date)
        if missing:
            return {"ok": False, "indicator": entry["name"],
                    "error": f"缺依赖：{'、'.join(missing)}，{entry['name']}不可用"}
        computed = evaluate(definition, values)
        if computed is None:
            return {"ok": False, "indicator": entry["name"],
                    "error": f"{entry['name']}不可用：分母为零或依赖缺失"}
        return {"ok": True, "indicator": entry["name"], "value": computed,
                "unit": definition.get("unit", ""),
                "decimals": definition.get("decimals"),
                "date": date, "date_probed": probed is not None, "deps": values}

    # 原始单点公式
    if not code:
        return {"ok": False, "indicator": entry["name"], "error": "code 必须提供"}
    single = library.load_single()
    record = single.get(entry["indicator"])
    if record is None:
        return {"ok": False, "indicator": entry["name"],
                "error": f"指标未入库：{entry['indicator']}"}
    formula = library.render(record, {"code": code, "date": date, **(params or {})})
    raw = _fetch_one(record, formula)
    return {"ok": True, "indicator": entry["name"], "code": code, "date": date,
            "value": library.coerce(raw), "unit": record.get("unit", ""),
            "indicator_code": entry["indicator"]}


def _fetch_one(record: dict, formula: str):
    """取单个公式的值。文本指标走 text 通道。"""
    if (record.get("reading_mode") or "matrix") == "text":
        values = engine.fetch_formulas([formula], text_ok=True).get("values") or []
        return values[0] if values else None
    block = engine.fetch_matrix([[formula]], text_ok=True).get("values") or []
    return block[0][0] if block and block[0] else None


def _fetch_deps(deps: list[dict], code: str, date: str) -> tuple[dict, list[str]]:
    """一次取回全部依赖。返回 (label→数值, 缺失说明)。

    dep 可带 sum_periods=N：对最近N个季末报告期各取一次后求和（如TTM），
    任一期缺失则整体缺失。dep 可带 date_mode=latest：不传日期取最新（行情类）。
    """
    single = library.load_single()
    formulas: list[str] = []
    plan: list[tuple[str, dict, int]] = []  # (label, dep, 占几个单元格)
    for dep in deps:
        record = single.get(dep["indicator"])
        if record is None:
            raise ValueError(f"指标未入库：{dep['indicator']}")
        if dep.get("sum_periods"):
            dates = _last_n_quarters(int(dep["sum_periods"]), date)
            for period in dates:
                formulas.append(library.render(
                    record, {"code": code, "date": period,
                             **(dep.get("params") or {})}))
            plan.append((dep["label"], dep, len(dates)))
        else:
            dep_date = "" if dep.get("date_mode") == "latest" else date
            formulas.append(library.render(
                record, {"code": code, "date": dep_date,
                         **(dep.get("params") or {})}))
            plan.append((dep["label"], dep, 1))
    if not formulas:
        return {}, []
    block = (engine.fetch_matrix([formulas], text_ok=True).get("values") or [[]])[0]
    values, missing = {}, []
    position = 0
    for label, dep, size in plan:
        cells = [library.coerce(v) for v in block[position:position + size]]
        position += size
        if size == 1:
            if isinstance(cells[0], (int, float)):
                values[label] = float(cells[0])
            else:
                missing.append(label)
        elif cells and all(isinstance(v, (int, float)) for v in cells):
            values[label] = float(sum(cells))
        else:
            missing.append(f"{label}（{dep['sum_periods']}期中有缺失）")
    return values, missing


def get_package(name: str, code: str = "", date: str = "", *,
                dims: dict | None = None, report_dates: list[str] | None = None,
                start: str | None = None, end: str | None = None,
                period: str = "daily", params: dict | None = None,
                export_path: str | None = None,
                auto_export_rows: int | None = 200) -> dict:
    """一次取回整块科目组合，组内衍生科目已算好。

    这是唯一的科目组合取数入口，供 CLI 与报告共用。历史行情支持周月聚合。
    """
    import time
    from pathlib import Path

    from ifind_excel_tool.indicators import aggregate, packages

    spec = definitions.load_packages().get(name)
    if spec is None:
        return {"ok": False, "error": f"没有名为「{name}」的科目组合"}
    if spec.get("kind") == "batch" or spec.get("kind") == "table":
        return {"ok": False, "indicator": name,
                "error": f"「{name}」是批量公式，请用 fetch_batch 指定输入参数"}
    period = period or "daily"
    if period not in ("daily", "weekly", "monthly"):
        return {"ok": False, "error": f"不支持的周期 {period}（支持 daily/weekly/monthly）"}
    resample_spec = spec.get("resample") or {}
    if period != "daily" and not resample_spec:
        return {"ok": False, "error": f"「{name}」不支持 period={period}（仅日线）"}

    if not code:
        return {"ok": False, "error": "code 必须提供"}
    if report_dates and not isinstance(report_dates, list):
        return {"ok": False, "error": "report_dates 必须是日期字符串数组"}

    probed = None
    if not date and not report_dates and spec.get("date_kind") == "report":
        probed = probe_latest_report(code)
        if not probed:
            return {"ok": False,
                    "error": f"无法确定最新报告期，请显式传 report_date（探测 {code} 失败）",
                    "hint": engine.ZERO_VALUE_HINT}
        date = probed

    started = time.time()
    expanded = packages.expand(name, code=code, report_date=date or None,
                               params=params, start=start, end=end,
                               report_dates=report_dates,
                               dims_override=dims)
    raw = engine.fetch_matrix(expanded["matrix"], text_ok=True)
    records = packages.shape(name, expanded, raw.get("values") or [])
    for record in records:
        record["code"] = code
    if period != "daily":
        records = aggregate.resample_ohlcv(records, period,
                                           resample_spec.get("field_map") or {})

    resp = {"ok": True, "indicator": name, "kind": "package", "code": code,
            "period": period, "fields": len(spec["fields"]),
            "rows": len(records), "records": records,
            "elapsed_seconds": round(time.time() - started, 2)}
    if probed:
        resp["report_date"] = probed
        resp["report_date_probed"] = True
    if report_dates:
        resp["report_dates"] = report_dates
    if _all_zero(records):
        resp["hint"] = engine.ZERO_VALUE_HINT
    if export_path or (auto_export_rows is not None and len(records) > auto_export_rows):
        target = export_path or str(
            Path(__file__).resolve().parent / "exports"
            / f"{name}_{code.replace('.', '_')}_{int(time.time())}.csv")
        resp["export"] = packages.to_csv(records, target)
        if not export_path:
            resp["records"] = records[:20]
            resp["truncated"] = True
    return resp


def _all_zero(records: list[dict]) -> bool:
    """判断一批结果是不是「看起来有数据但全为0」。

    这种情形常常是插件缓存而非上游没数据，值得提示一句；不做自动重试，
    以免把偶发情况做成通用兜底。
    """
    numbers = [v for record in records for k, v in record.items()
               if not k.endswith("__unit") and isinstance(v, (int, float))]
    return bool(numbers) and all(v == 0 for v in numbers)
