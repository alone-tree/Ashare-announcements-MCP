# -*- coding: utf-8 -*-
"""ifind_excel_tool绘图底层：读已导出的行情CSV，按模板输出PNG。

零import依赖：不引用market_data_mcp任何模块，只用标准库与matplotlib。
不取数：数据由fetch_scene导出到data_path，本模块只读文件。
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

_MPL_READY = False

_RED = "#d9403f"       # 涨（A股口径）
_GREEN = "#2ea26d"     # 跌
_BG = "white"
_GRID = "#e6e6e6"
_FIGSIZE = (16, 11)
_DPI = 200
_DEFAULT_MA = (5, 10, 20, 60)
_MA_COLORS = {5: "#f7b731", 10: "#4a90d9", 20: "#d9567a", 60: "#7b5ea7"}

# 列名映射：iFinD中文导出列名优先，英文列名兼容
_ALIASES = {
    "date": ("date", "日期", "交易日"),
    "open": ("open", "开盘价", "开盘"),
    "high": ("high", "最高价", "最高"),
    "low": ("low", "最低价", "最低"),
    "close": ("close", "收盘价", "收盘"),
    "qfq_close": ("前复权收盘价", "qfq_close", "复权收盘价"),
    "volume": ("volume", "成交量"),
    "amount": ("amount", "成交额", "成交金额"),
    "mcap": ("total_market_cap", "总市值", "市值", "market_cap"),
}


def _ensure_mpl() -> None:
    global _MPL_READY
    if _MPL_READY:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    plt.style.use("tableau-colorblind10")
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC"):
        if name in fonts:
            plt.rcParams["font.sans-serif"] = [name, "sans-serif"]
            break
    plt.rcParams["axes.unicode_minus"] = False
    _MPL_READY = True


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    try:
        result = float(str(value).strip().replace(",", ""))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _read_rows(path: str) -> tuple[list[dict], list[str]]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"data_path 不存在：{path}")
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    headers = list(rows[0].keys()) if rows else []
    if not rows:
        raise ValueError("行情CSV为空")
    return rows, headers


def _resolve_col(headers: list[str], aliases: tuple[str, ...],
                 explicit: str | None = None, label: str = "列") -> str:
    for header in headers:
        if explicit and header.strip().lower() == explicit.strip().lower():
            return header
    if explicit:
        raise ValueError(f"找不到{label}「{explicit}」；可用列：{headers}")
    for alias in aliases:
        for header in headers:
            if header.strip().lower() == alias.lower():
                return header
    raise ValueError(f"找不到{label}（候选{list(aliases)}）；可用列：{headers}")


def _standard_cols(headers: list[str]) -> dict[str, str]:
    cols = {}
    for key in ("date", "open", "high", "low", "close", "volume"):
        cols[key] = _resolve_col(headers, _ALIASES[key], label=key)
    return cols


def _sorted_rows(rows: list[dict], date_col: str) -> list[dict]:
    return sorted(rows, key=lambda r: str(r.get(date_col) or "")[:10])


def _has_nonpositive(values: list[float | None]) -> bool:
    return any(v is not None and v <= 0 for v in values)


def _set_log_scale(ax, values: list[float | None], enabled: bool) -> bool:
    if not enabled or _has_nonpositive(values):
        return False
    ax.set_yscale("log")
    return True


def _rolling_ma(values: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(window - 1, len(values)):
        chunk = values[i + 1 - window:i + 1]
        if all(v is not None for v in chunk):
            out[i] = sum(chunk) / window  # type: ignore[arg-type]
    return out


def _style_axes(ax, grid: bool = True) -> None:
    ax.set_facecolor(_BG)
    ax.grid(True, color=_GRID, alpha=0.3, linewidth=0.5) if grid else None
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=12)


def _format_x_ticks(ax, dates: list[str], right_pad: float = 14.0) -> None:
    n = len(dates)
    step = max(1, n // 8)
    ticks = list(range(0, n, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i][:10] for i in ticks], rotation=0, fontsize=12)
    ax.set_xlim(-1, n + right_pad)


def _inline_labels(ax, entries: list[tuple[Any, str]], x_pos: float,
                   fontsize: int = 12) -> None:
    """右侧inline标签：测量字高后纵向避让，白底描边，不画图例框。"""
    import matplotlib.patheffects as pe

    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    items = []
    for line, label in entries:
        y = None
        for value in reversed(list(line.get_ydata())):
            num = _to_float(value)
            if num is not None:
                y = num
                break
        if y is None:
            continue
        text = ax.text(x_pos, y, label, fontsize=fontsize, color=line.get_color(),
                       ha="left", va="center", zorder=100)
        text.set_path_effects([pe.withStroke(linewidth=3, foreground=_BG)])
        items.append({"text": text, "desired": ax.transData.transform((x_pos, y))[1],
                      "height": text.get_window_extent(renderer).height})
    if not items:
        return
    items.sort(key=lambda it: it["desired"])
    cursor = ax.bbox.y0
    for it in items:
        center = max(it["desired"], cursor + it["height"] / 2 + 2)
        it["center"] = center
        cursor = center + it["height"] / 2
    overflow = max(it["center"] + it["height"] / 2 for it in items) - ax.bbox.y1
    if overflow > 0:
        for it in items:
            it["center"] -= overflow
    for it in items:
        y_data = ax.transData.inverted().transform((x_pos, it["center"]))[1]
        it["text"].set_y(y_data)
    fig.canvas.draw()


def _parse_events(events: Any) -> list[dict]:
    """事件输入：CSV路径（date,description）、JSON文件路径或数组。"""
    if not events:
        return []
    if isinstance(events, list):
        raw = events
    elif isinstance(events, str) and events.strip().startswith("["):
        raw = json.loads(events)
    else:
        path = Path(str(events))
        if not path.is_file():
            raise ValueError(f"events 文件不存在：{events}")
        if path.suffix.lower() == ".json":
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        else:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                raw = list(csv.DictReader(stream))
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        day = str(item.get("date") or item.get("d") or "").strip()[:10]
        desc = str(item.get("description") or item.get("desc") or "").strip()
        if day and desc:
            out.append({"date": day, "description": desc})
    return out


def _align_events(events: list[dict], dates: list[str]) -> list[tuple[int, str]]:
    """事件日对齐到不早于事件日的最近交易日（CSV的date列）。"""
    out = []
    for ev in events:
        idx = next((i for i, d in enumerate(dates) if d >= ev["date"]), None)
        if idx is not None:
            out.append((idx, ev["description"]))
    return out


def _annotate_events(ax, events: list[tuple[int, str]], color: str) -> tuple[int, int]:
    """按渲染字宽测量、分层避让的事件标注；越界或重叠时明确报错。

    移植「绘制市值与前复权股价.py」的annotate_events，x轴改为交易日序号。
    """
    if not events:
        return 0, 0
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    x_min, x_max = ax.get_xlim()
    pixels_per_point = fig.dpi / 72
    pad_points = 3
    pad = pad_points * pixels_per_point
    gap = 6 * pixels_per_point

    labels = []
    for idx, desc in events:
        if not x_min <= idx <= x_max:
            continue
        probe = ax.text(0, 0, desc, fontsize=15)
        box = probe.get_window_extent(renderer)
        probe.remove()
        labels.append((idx, desc, box.width + 2 * pad, box.height + 2 * pad))
    if not labels:
        return 0, 0
    labels.sort(key=lambda item: item[0])
    if max(w for _, _, w, _ in labels) + pad + gap >= ax.bbox.width:
        raise ValueError("单个事件标签超过绘图区宽度，请缩短文案")

    # 起点附近的长标签：自动扩展时间轴左侧留白
    x_min = min(x_min, min(
        (x - ratio * x_max) / (1 - ratio)
        for x, _, width, _ in labels
        for ratio in [(width + pad + gap) / ax.bbox.width]))
    ax.set_xlim(x_min, x_max)

    lane_ends: list[float] = []
    placements = []
    for x, text, width, _ in labels:
        line_x = ax.transData.transform((x, 0))[0]
        end = line_x
        start = end - width
        lane = next((i for i, occupied in enumerate(lane_ends)
                     if start >= occupied + gap), len(lane_ends))
        if lane == len(lane_ends):
            lane_ends.append(end)
        else:
            lane_ends[lane] = end
        placements.append((x, text, lane))

    height = max(h for _, _, _, h in labels)
    row_height = height + gap
    # 预留标题区（suptitle固定在画布顶部），避免事件框压住标题
    header_height = len(lane_ends) * row_height + 52 * pixels_per_point
    top = min(0.86, 1 - header_height / fig.bbox.height)
    if top < 0.5:
        raise ValueError(f"事件标记需要{len(lane_ends)}层，画布放不下；请减少标记数量")
    fig.subplots_adjust(top=top)

    texts = []
    for x, text, lane in placements:
        offset_pixels = pad + lane * row_height
        ax.axvline(x, color=color, linestyle="--", linewidth=0.8, alpha=0.85)
        ax.plot([x, x], [1, 1 + (offset_pixels + height / 2) / ax.bbox.height],
                transform=ax.get_xaxis_transform(), color=color, linewidth=0.8,
                clip_on=False)
        texts.append(ax.annotate(
            text, xy=(x, 1), xycoords=ax.get_xaxis_transform(),
            xytext=(-pad_points, (offset_pixels + pad) / pixels_per_point),
            textcoords="offset points", ha="right", va="bottom", fontsize=14,
            annotation_clip=False,
            bbox={"boxstyle": f"square,pad={pad_points / 11}",
                  "facecolor": "white", "edgecolor": color, "linewidth": 0.8},
            zorder=100))
    fig.canvas.draw()
    boxes = [t.get_bbox_patch().get_window_extent(renderer) for t in texts]
    if any(box.x0 < 0 or box.x1 > fig.bbox.width or box.y1 > fig.bbox.height
           for box in boxes):
        raise ValueError("事件标签超出画布，无法清晰导出")
    if any(a.overlaps(b) for i, a in enumerate(boxes) for b in boxes[i + 1:]):
        raise ValueError("事件标签仍有重叠，无法清晰导出")
    return len(texts), len(lane_ends)


def _extract_keypoints(values: list[float | None],
                       threshold: float) -> list[tuple[int, float, str]]:
    """每轮回撤的阶段前高+最大回撤低点；回撤不足阈值不记录。"""
    prices = [v for v in values if v is not None]
    idxs = [i for i, v in enumerate(values) if v is not None]
    n = len(prices)
    if n < 2:
        return []
    points: list[tuple[int, float, str]] = []
    i = 0
    while i < n - 1:
        peak = i
        while peak + 1 < n and prices[peak + 1] >= prices[peak]:
            peak += 1
        if peak >= n - 1:
            break
        trough = peak + 1
        recovery = None
        k = peak + 1
        while k < n:
            if prices[k] < prices[trough]:
                trough = k
            if prices[k] >= prices[peak]:
                recovery = k
                break
            k += 1
        if prices[trough] / prices[peak] - 1.0 <= -threshold:
            points.append((idxs[peak], float(prices[peak]), "peak"))
            points.append((idxs[trough], float(prices[trough]), "trough"))
        if recovery is None:
            break
        i = recovery
    return points


_TEMPLATE_TITLES = {
    "kline_volume": "K线图",
    "kline_log_volume": "K线图（对数坐标）",
    "close_mcap_events": "总市值与前复权收盘价",
    "close_line_keypoints": "收盘价走势",
}


def _title(rows: list[dict], template: str, date_col: str) -> str:
    code = str(rows[0].get("code") or "").strip()
    first = str(rows[0].get(date_col) or "")[:10]
    last = str(rows[-1].get(date_col) or "")[:10]
    label = _TEMPLATE_TITLES.get(template, template)
    return f"{code + ' ' if code else ''}{label}（{first} 至 {last}）"


def _finish(fig, output: str, notes: list[str], rows: int,
            template: str, **extra: Any) -> dict:
    import matplotlib.pyplot as plt

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=_DPI, facecolor=_BG)
    plt.close(fig)
    result = {"ok": True, "output": str(path), "template": template,
              "rows": rows, "notes": notes}
    result.update(extra)
    return result


def _kline(req: dict, rows: list[dict], headers: list[str],
           template: str) -> dict:
    import matplotlib.pyplot as plt

    cols = _standard_cols(headers)
    dates = [str(r.get(cols["date"]) or "")[:10] for r in rows]

    fig, (ax_main, ax_vol) = plt.subplots(
        2, 1, figsize=_FIGSIZE, dpi=_DPI, sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1]})
    fig.patch.set_facecolor(_BG)
    fig.subplots_adjust(left=0.07, right=0.93, bottom=0.08, top=0.88, hspace=0.12)
    _style_axes(ax_main)
    _style_axes(ax_vol)

    closes: list[float | None] = []
    volumes: list[float | None] = []
    colors: list[str | None] = []
    for row in rows:
        o = _to_float(row.get(cols["open"]))
        h = _to_float(row.get(cols["high"]))
        low = _to_float(row.get(cols["low"]))
        c = _to_float(row.get(cols["close"]))
        closes.append(c)
        volumes.append(_to_float(row.get(cols["volume"])))
        if None in (o, h, low, c):
            colors.append(None)
            continue
        color = _RED if c >= o else _GREEN
        colors.append(color)
        i = len(closes) - 1
        ax_main.vlines(i, low, h, color=color, linewidth=0.8)
        ax_main.bar(i, abs(c - o) or 0.01, bottom=min(o, c), width=0.6,
                    color=color, edgecolor=color, linewidth=0.5)

    windows = req.get("ma_windows") or list(_DEFAULT_MA)
    if isinstance(windows, str):
        windows = [int(w) for w in windows.replace("，", ",").split(",") if w.strip()]
    windows = [int(w) for w in windows if int(w) > 0]
    notes: list[str] = []
    lines = []
    for window in windows:
        ma = _rolling_ma(closes, window)
        xs = [i for i, v in enumerate(ma) if v is not None]
        if not xs:
            continue
        ys = [ma[i] for i in xs]
        color = _MA_COLORS.get(window)
        line, = ax_main.plot(xs, ys, linewidth=1.1, color=color,
                             label=f"MA{window}" if color else None)
        lines.append((line, f"MA{window}"))
    if lines:
        _inline_labels(ax_main, lines, len(rows) + 1)

    log_scale = bool(req.get("log_scale") or template == "kline_log_volume")
    log_on = _set_log_scale(ax_main, [v for v in closes if v is not None], log_scale)
    if log_scale and not log_on:
        notes.append("价格数据含非正值，对数坐标退回普通坐标")

    for i, (volume, color) in enumerate(zip(volumes, colors)):
        if volume is None or color is None:
            continue
        ax_vol.bar(i, volume / 1e4, width=0.6, color=color, linewidth=0)
    vol_log = _set_log_scale(ax_vol, [v / 1e4 if v is not None else None for v in volumes], log_scale)
    if log_scale and not vol_log:
        notes.append("成交量含非正值，对数坐标退回普通坐标")

    _format_x_ticks(ax_main, dates)
    _format_x_ticks(ax_vol, dates)
    events = _align_events(_parse_events(req.get("events")), dates)
    if req.get("events") and not events:
        notes.append("events未匹配到交易日，未标注")
    visible, lanes = _annotate_events(ax_main, events, "#59A14F")
    fig.suptitle(_title(rows, template, cols["date"]), fontsize=18, y=0.985)
    ax_main.set_ylabel("价格（元）", fontsize=14)
    ax_vol.set_ylabel("成交量（万股）", fontsize=14)
    return _finish(fig, req.get("output") or str(
        Path(req["data_path"]).with_name(Path(req["data_path"]).stem + f"_{template}.png")),
        notes, len(rows), template, events=visible, label_rows=lanes)


def _close_mcap_events(req: dict, rows: list[dict], headers: list[str]) -> dict:
    import matplotlib.pyplot as plt

    date_col = _resolve_col(headers, _ALIASES["date"], label="date")
    price_col = _resolve_col(headers, _ALIASES["qfq_close"] + _ALIASES["close"],
                             req.get("price_col"), "price_col")
    mcap_col = _resolve_col(headers, _ALIASES["mcap"], req.get("mcap_col"), "mcap_col")
    dates = [str(r.get(date_col) or "")[:10] for r in rows]
    prices = [_to_float(r.get(price_col)) for r in rows]
    mcaps = [(_to_float(r.get(mcap_col)) or 0) / 1e8 for r in rows]
    if not any(v is not None for v in prices):
        raise ValueError("收盘价列无有效数值")
    if not any(v > 0 for v in mcaps):
        raise ValueError(f"市值列「{mcap_col}」无有效数值")

    fig, left = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    fig.patch.set_facecolor(_BG)
    fig.subplots_adjust(left=0.07, right=0.93, bottom=0.08, top=0.88)
    left.set_facecolor(_BG)
    left.grid(True, color=_GRID, alpha=0.3, linewidth=0.5)
    left.spines["top"].set_visible(False)
    left.spines["right"].set_visible(False)
    right = left.twinx()
    right.spines["top"].set_visible(False)
    right.spines["right"].set_visible(False)
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    line_mcap, = left.plot(range(len(rows)), mcaps, color=colors[0], linewidth=1.7)
    line_price, = right.plot(range(len(rows)), prices, color=colors[1], linewidth=1.7)
    left.set_ylabel(f"{mcap_col}（亿元）", color=colors[0], fontsize=15)
    right.set_ylabel(f"{price_col}（元）", color=colors[1], fontsize=15)
    left.tick_params(axis="y", colors=colors[0], labelsize=12)
    right.tick_params(axis="y", colors=colors[1], labelsize=12)
    left.tick_params(axis="x", labelsize=12)
    left.set_ylim(bottom=0)
    right.set_ylim(bottom=0)
    _format_x_ticks(left, dates)
    _format_x_ticks(right, dates)
    # 左右轴已标明总市值/收盘价，线上不再重复inline标签

    events = _align_events(_parse_events(req.get("events")), dates)
    if req.get("events") and not events:
        events = []
    visible, lanes = _annotate_events(left, events, colors[2])
    fig.suptitle(_title(rows, "close_mcap_events", date_col), fontsize=18, y=0.985)
    notes: list[str] = []
    if not events and req.get("events"):
        notes.append("events未匹配到交易日，未标注")
    return _finish(fig, req.get("output") or str(
        Path(req["data_path"]).with_name(Path(req["data_path"]).stem + "_close_mcap_events.png")),
        notes, len(rows), "close_mcap_events", events=visible, label_rows=lanes,
        price_col=price_col, mcap_col=mcap_col)


def _close_line_keypoints(req: dict, rows: list[dict], headers: list[str]) -> dict:
    import matplotlib.pyplot as plt

    date_col = _resolve_col(headers, _ALIASES["date"], label="date")
    price_col = _resolve_col(headers, _ALIASES["qfq_close"] + _ALIASES["close"],
                             req.get("price_col"), "price_col")
    threshold = float(req.get("drawdown_threshold") or 0.30)
    if not 0 < threshold < 1:
        raise ValueError("drawdown_threshold 必须在0-1之间（如0.30=30%）")
    dates = [str(r.get(date_col) or "")[:10] for r in rows]
    values = [_to_float(r.get(price_col)) for r in rows]
    valid = [(i, v) for i, v in enumerate(values) if v is not None]
    if not valid:
        raise ValueError(f"列「{price_col}」无有效数值")

    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    fig.patch.set_facecolor(_BG)
    fig.subplots_adjust(left=0.07, right=0.93, bottom=0.08, top=0.88)
    _style_axes(ax)
    line, = ax.plot([i for i, _ in valid], [v for _, v in valid], linewidth=1.5)
    log_on = _set_log_scale(ax, values, bool(req.get("log_scale")))
    notes: list[str] = []
    if req.get("log_scale") and not log_on:
        notes.append("数据含非正值，对数坐标退回普通坐标")

    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    low_idx, low_val = min(valid, key=lambda item: item[1])
    high_idx, high_val = max(valid, key=lambda item: item[1])
    last_idx, last_val = valid[-1]
    # 偏移方向分开相邻点（最新与最低常落在末端附近）
    # 末端最低/最新常相邻，标注方向分开：最低正下方、最高正上方、最新左上
    marks = [(low_idx, low_val, "最低", _RED, (0, -18), "center"),
             (high_idx, high_val, "最高", "#16a34a", (0, 12), "center")]
    # 最新点与最低/最高同处末端时不重复标（数值已由该点给出）
    if last_idx not in (low_idx, high_idx):
        marks.append((last_idx, last_val, "最新", colors[2], (-18, 10), "right"))
    for idx, val, name, color, offset, ha in marks:
        ax.scatter([idx], [val], s=30, color=color, zorder=6,
                   edgecolors="white", linewidths=0.6)
        ax.annotate(f"{name} {val:,.2f}", xy=(idx, val), xytext=offset,
                    textcoords="offset points", fontsize=12, color=color, ha=ha,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8))

    keypoints = _extract_keypoints(values, threshold)
    # 回撤点与最高/最低重合时不再重复标注
    marked = {low_idx, high_idx}
    n_total = max(1, len(rows))
    for idx, val, kind in keypoints:
        if idx in marked:
            continue
        marked.add(idx)
        color = "#16a34a" if kind == "peak" else _RED
        ax.scatter([idx], [val], s=22, color=color, zorder=6,
                   edgecolors="white", linewidths=0.6)
        # 左右边缘的点把标签朝内放，避免被画布裁切
        if idx <= n_total * 0.04:
            offset, ha = (10, -12), "left"
        elif idx >= n_total * 0.96:
            offset, ha = (-10, -12), "right"
        else:
            offset, ha = (4, -12), "left"
        ax.annotate(f"{val:,.2f}", xy=(idx, val), xytext=offset,
                    textcoords="offset points", fontsize=12, color=color, ha=ha,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.7))
    if not keypoints:
        notes.append(f"未找到回撤超过{threshold:.0%}的高低点，未标注回撤")
    _format_x_ticks(ax, dates)
    # 单线无需inline标签（避免与"最新"点标注挤在一起），轴ylabel已标列名
    events = _align_events(_parse_events(req.get("events")), dates)
    if req.get("events") and not events:
        notes.append("events未匹配到交易日，未标注")
    visible, lanes = _annotate_events(ax, events, "#59A14F")
    fig.suptitle(_title(rows, "close_line_keypoints", date_col), fontsize=18, y=0.985)
    ax.set_ylabel(price_col, fontsize=14)
    return _finish(fig, req.get("output") or str(
        Path(req["data_path"]).with_name(Path(req["data_path"]).stem + "_close_line_keypoints.png")),
        notes, len(rows), "close_line_keypoints", events=visible, label_rows=lanes,
        price_col=price_col, keypoints=len(keypoints) // 2)


def draw(req: dict) -> dict:
    """统一绘图入口：{"cmd":"draw","template":...,"data_path":...,"output":...}。"""
    try:
        _ensure_mpl()
        template = req.get("template") or ""
        if template not in ("kline_volume", "kline_log_volume",
                            "close_mcap_events", "close_line_keypoints"):
            return {"ok": False, "error": f"未知template：{template}"}
        if not req.get("data_path"):
            return {"ok": False, "error": "data_path 不能为空"}
        rows, headers = _read_rows(req["data_path"])
        if template in ("kline_volume", "kline_log_volume"):
            return _kline(req, rows, headers, template)
        if template == "close_mcap_events":
            return _close_mcap_events(req, rows, headers)
        return _close_line_keypoints(req, rows, headers)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
