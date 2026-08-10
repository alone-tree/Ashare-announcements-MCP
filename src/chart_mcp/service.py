# -*- coding: utf-8 -*-
"""chart MCP 绘图服务：K线/折线行情图（三 MCP 一体的第三块）。

数据链路：直接 import 调用 market_data_mcp.service.get_quote()，不复制取数代码；
绘图层完全不操心数据（有缓存用缓存，没缓存由 get_quote 自动补拉）。

视觉风格全部代码写死（尺寸/PPI/中文字体/配色），不提供模板系统：
- 红涨绿跌（A股口径）
- MA5/10/20/60 按当前周期计算（周图 MA5 = 5 周均线）；均线数据不足不绘制
- log_scale 对 K线/折线/成交量副图都生效；数据含负值或 0 时退回普通坐标
- 每次调用都重新绘图（不按参数做图缓存复用），PNG 落盘 {root}/cache/_charts/
- 只返回文件路径，不返回图片内容
"""

from __future__ import annotations

import csv
import os
from typing import Any

try:
    from market_data_mcp.service import get_quote as get_quote_service
except ImportError:  # 用户版单独导出 chart 时缺 market-data（依赖检查，设计 §三.3）
    get_quote_service = None  # type: ignore[assignment]

# matplotlib 延迟导入（后端 Agg 无窗口）
_MPL_READY = False


def _ensure_mpl() -> None:
    global _MPL_READY
    if _MPL_READY:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: F401

    # 中文字体（Windows 常见；找不到时回退默认，用户版 Windows 均有）
    for name in ("Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC"):
        try:
            matplotlib.rcParams["font.sans-serif"] = [name]
            break
        except Exception:  # noqa: BLE001
            continue
    matplotlib.rcParams["axes.unicode_minus"] = False
    _MPL_READY = True


# K线请求的字段
_KLINE_VARS = ("open", "high", "low", "close", "volume")
_MA_WINDOWS = (5, 10, 20, 60)
_MA_COLORS = {5: "#f7b731", 10: "#4a90d9", 20: "#d9567a", 60: "#7b5ea7"}
# 红涨绿跌（A股口径）
_RED = "#d9403f"
_GREEN = "#2ea26d"
_GRID = "#e6e6e6"
_FIGSIZE = (11.5, 6.8)
_DPI = 150


def _to_float(value: Any) -> float | None:
    """CSV/JSON 值统一转 float；空/非法返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _load_rows(quote: dict) -> list[dict]:
    """从 get_quote 返回拿 rows：直接返回时用 rows；超长自动导出时读 CSV。"""
    if quote.get("rows"):
        return quote["rows"]
    path = quote.get("path")
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _has_nonpositive(values: list[float | None]) -> bool:
    """数据是否含负值或 0（决定是否退回普通坐标）。"""
    return any(v is not None and v <= 0 for v in values)


def _rolling_ma(values: list[float | None], window: int) -> list[float | None]:
    """按当前周期滚动均线；不足窗口的数据为 None（不绘制）。"""
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        if i + 1 < window:
            continue
        window_vals = values[i + 1 - window : i + 1]
        if any(v is None for v in window_vals):
            continue
        out[i] = sum(window_vals) / window  # type: ignore[arg-type]
    return out


def _draw_kline(ax, rows: list[dict]) -> tuple[list[float | None], list[float | None]]:
    """蜡烛图 + 成交量（主图 axes）。返回 (收盘序列, 成交量序列) 供均线/量副图用。"""
    import matplotlib.pyplot as plt

    closes: list[float | None] = []
    volumes: list[float | None] = []
    for row in rows:
        o = _to_float(row.get("open"))
        h = _to_float(row.get("high"))
        l = _to_float(row.get("low"))
        c = _to_float(row.get("close"))
        closes.append(c)
        volumes.append(_to_float(row.get("volume")))
        if o is None or h is None or l is None or c is None:
            continue
        color = _RED if c >= o else _GREEN
        # 影线
        ax.vlines(len(closes) - 1, l, h, color=color, linewidth=0.8)
        # 实体
        body_bottom = min(o, c)
        body_height = abs(c - o) or 0.01  # 十字星给最小实体，避免不可见
        ax.bar(len(closes) - 1, body_height, bottom=body_bottom, width=0.6,
               color=color, edgecolor=color, linewidth=0.5, align="center")
    return closes, volumes


def _set_log_scale(ax, values: list[float | None], enabled: bool) -> bool:
    """对数坐标：仅当 enabled 且数据全为正才启用；否则普通坐标。返回是否实际启用。"""
    if not enabled or _has_nonpositive(values):
        return False
    ax.set_yscale("log")
    return True


def _draw_volume(ax, volumes: list[float | None], closes: list[float | None],
                 log_scale: bool) -> bool:
    """成交量副图（与主图共享 x 轴）。返回是否启用对数。"""
    for i, (v, c) in enumerate(zip(volumes, closes)):
        if v is None or c is None:
            continue
        color = _RED if c >= 0 else _GREEN  # 红绿由主图收盘涨跌决定
        ax.bar(i, v, width=0.6, color=color, linewidth=0)
    return _set_log_scale(ax, volumes, log_scale)


def _format_x_ticks(ax, rows: list[dict]) -> None:
    """x 轴刻度：稀疏日期标签（最多 ~8 个）。"""
    n = len(rows)
    step = max(1, n // 8)
    ticks = list(range(0, n, step))
    labels = [str(rows[i].get("date", ""))[:10] for i in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=0, fontsize=8)
    ax.set_xlim(-0.8, n - 0.2)


def get_quote_chart(
    root: str,
    code: str,
    adjust: str = "raw",
    start_date: str | None = None,
    end_date: str | None = None,
    period: str = "daily",
    log_scale: bool = False,
    field: str | None = None,
) -> dict:
    """绘制行情图（K线或折线），PNG 落盘 {root}/cache/_charts/，返回文件路径。

    code: 带市场后缀代码（300308.SZ / 00700.HK / AAPL.US）。
    adjust: raw/hfq/qfq。
    start_date/end_date: YYYY-MM-DD；都不传 = 全部缓存数据（start=all 语义）；
        start_date 传了而 end_date 留空 = 该日起至今；只传 end_date = 早期数据（起点不限）。
    period: daily/weekly/monthly（周/月由 get_quote 按日线聚合，MA 按当前周期计算）。
    log_scale: 对数坐标；对 K线/折线/成交量副图都生效，数据含负值或 0 自动退回普通坐标。
    field: 不传 = K线（蜡烛+成交量+MA5/10/20/60）；传 open/high/low/close 任一 = 单字段折线（无均线无副图）。

    返回 {ok, path, code, chart_type, start, end, period, adjust, field, notes}；失败 {ok:false, error}。
    """
    try:
        _ensure_mpl()
        import matplotlib.pyplot as plt

        if field is not None and field not in ("open", "high", "low", "close"):
            return {"ok": False,
                    "error": f"field 仅支持 open/high/low/close（折线模式），不传 field 为 K线"}

        if get_quote_service is None:
            return {"ok": False,
                    "error": "数据未配置：chart 依赖 market-data MCP（取数），请同时导出 market-data MCP"}

        # 数据：不传日期区间 = 全部缓存（start=all）
        if start_date is None:
            q_start = "all"
        else:
            q_start = start_date
        vars_list = list(_KLINE_VARS) if field is None else [field]
        quote = get_quote_service(
            root, code, vars=vars_list, adjust=adjust,
            start_date=q_start, end_date=end_date, period=period,
        )
        if not quote.get("ok"):
            return {"ok": False, "error": quote.get("error", "取数失败")}
        rows = _load_rows(quote)
        if not rows:
            notes = quote.get("notes") or []
            return {"ok": False, "error": f"无数据可绘制（{notes}）"}

        notes: list[str] = []
        chart_type = "line" if field is not None else "kline"

        if chart_type == "line":
            fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
            values = [_to_float(r.get(field)) for r in rows]
            xs = list(range(len(rows)))
            ax.plot(xs, values, color="#1f6fb2", linewidth=1.3)
            log_on = _set_log_scale(ax, values, log_scale)
            if log_scale and not log_on:
                notes.append("数据含非正值，对数坐标退回普通坐标")
            _format_x_ticks(ax, rows)
            ax.set_title(f"{code} {field.upper()} {period}（{adjust}）", fontsize=12)
            ax.grid(True, color=_GRID, linewidth=0.6)
            ax.set_ylabel(field.upper())
        else:
            fig, (ax, ax_vol) = plt.subplots(
                2, 1, figsize=_FIGSIZE, dpi=_DPI, sharex=True,
                gridspec_kw={"height_ratios": [3.2, 1]})
            closes, volumes = _draw_kline(ax, rows)
            log_on = _set_log_scale(ax, [v for v in closes if v is not None],
                                    log_scale) if any(v is not None for v in closes) else False
            # 均线（按当前周期；数据不足窗口不绘制）
            if closes and any(v is not None for v in closes):
                drawn_any = False
                for w in _MA_WINDOWS:
                    ma = _rolling_ma(closes, w)
                    xs_ma = [i for i, v in enumerate(ma) if v is not None]
                    vals_ma = [v for v in ma if v is not None]
                    if xs_ma:
                        ax.plot(xs_ma, vals_ma, color=_MA_COLORS[w], linewidth=1.0,
                                label=f"MA{w}")
                        drawn_any = True
                if drawn_any:
                    ax.legend(fontsize=8, loc="upper left")
            else:
                notes.append("无有效收盘价，均线未绘制")
            _format_x_ticks(ax, rows)
            vol_log = _draw_volume(ax_vol, volumes, closes, log_scale)
            if log_scale and not log_on:
                notes.append("价格数据含非正值，对数坐标退回普通坐标")
            elif log_scale and not vol_log:
                notes.append("成交量含非正值，成交量对数坐标退回普通坐标")
            ax.set_title(f"{code} {period} K线（{adjust}）", fontsize=12)
            ax.grid(True, color=_GRID, linewidth=0.6)
            ax_vol.set_ylabel("成交量", fontsize=9)
            ax_vol.grid(True, color=_GRID, linewidth=0.6, axis="y")

        fig.tight_layout()
        charts_dir = os.path.join(root, "cache", "_charts")
        os.makedirs(charts_dir, exist_ok=True)
        start_tag = str(start_date or "all").replace("-", "")
        end_tag = str(end_date or "latest").replace("-", "")
        field_tag = field or "kline"
        fname = f"{code}_{adjust}_{period}_{field_tag}_{start_tag}_{end_tag}.png"
        path = os.path.join(charts_dir, fname)
        fig.savefig(path, dpi=_DPI)
        plt.close(fig)

        result = {
            "ok": True,
            "path": path,
            "code": code,
            "chart_type": chart_type,
            "start": quote.get("start", start_tag),
            "end": quote.get("end", end_tag),
            "period": period,
            "adjust": adjust,
            "rows": len(rows),
        }
        if field is not None:
            result["field"] = field
        if notes:
            result["notes"] = notes
        return result
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
