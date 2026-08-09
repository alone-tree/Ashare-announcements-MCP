# -*- coding: utf-8 -*-
"""统一适配层：标准代码 → 市场 → 各数据源代码格式。

入口只认标准代码（300476.SZ / 00700.HK / AAPL.US），程序按后缀路由市场，
**禁止按数字位数/开头猜测市场**（历史教训：B 股 900xxx 曾被按"6 开头=沪"误判为深）。
请求模块只接收已转换好的源格式字符串，内部不再做任何格式处理；
新增数据源 = 写请求模块 + 本文件转换表加一行。

各源代码格式（客观事实见 字段与数据源支持情况.md §1/§8，2026-08 实测）：
- 新浪：A/B 股 sh600519/sz000001（B 股同通道：900901→sh900901、200725→sz200725）、
  北交所 bj920002、港股 5 位裸码 00700、美股字母 AAPL
- iFinD：A/B 股原样 600519.SH、北交所 920002.BJ、港股 4 位带前导零 0700.HK、
  美股需 THS_HQ 探测 .O/.N（见 providers/ifind.py，此处返回 code.US 占位）
- 东财：A/B 股裸码、港股 5 位裸码、美股 105.AAPL
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

# 后缀 → 市场通道（B 股与 A 股同通道，不细分）
_SUFFIX_MARKET = {"SH": "A", "SZ": "A", "BJ": "BJ", "HK": "HK", "US": "US"}

MARKET_NAMES = {"A": "A股", "BJ": "北交所", "HK": "港股", "US": "美股"}

# 各市场标准代码位数（用于校验）
_CODE_LEN = {"A": 6, "BJ": 6, "HK": 5}

# 市场收盘时间（A/BJ/HK 按北京时间判断；US 按美东时间判断）
MARKET_CLOSE = {"A": time(15, 0), "BJ": time(15, 0), "HK": time(16, 0), "US": time(16, 0)}


def _us_dst(d: date) -> bool:
    """美东夏令时（EDT = UTC-4）：3 月第二个周日 02:00 ~ 11 月第一个周日 02:00。"""
    march = date(d.year, 3, 1)
    dst_start = march + timedelta(days=(6 - march.weekday()) % 7 + 7)
    nov = date(d.year, 11, 1)
    dst_end = nov + timedelta(days=(6 - nov.weekday()) % 7)
    return dst_start <= d < dst_end


def _beijing_time(now: datetime) -> time:
    """北京时间（UTC+8 固定，无夏令时），不依赖本机时区。"""
    return (now.astimezone(timezone.utc) + timedelta(hours=8)).time()


def _us_eastern_time(now: datetime) -> time:
    """美东时间（EDT=UTC-4 / EST=UTC-5）。"""
    offset = 4 if _us_dst(now.date()) else 5
    return (now.astimezone(timezone.utc) - timedelta(hours=offset)).time()


def is_market_closed(market: str, now: datetime | None = None) -> bool:
    """当前时刻该市场是否已收盘（决定"探测无数据"可否写 verified_until）。

    - 周六/周日：视为已收盘（周末不交易，数据不会再有）
    - 工作日：A/BJ 北京时间 ≥15:00；HK 北京时间 ≥16:00；US 美东时间 ≥16:00
    """
    now = now or datetime.now()
    if now.date().weekday() >= 5:
        return True
    if market in ("A", "BJ", "HK"):
        return _beijing_time(now) >= MARKET_CLOSE[market]
    if market == "US":
        return _us_eastern_time(now) >= MARKET_CLOSE["US"]
    return True  # 未知市场保守视为已收盘


@dataclass(frozen=True)
class MarketCode:
    market: str  # A / BJ / HK / US
    code: str    # 裸码（去后缀、大写）：600519 / 00700 / AAPL
    suffix: str  # 原始后缀（大写）：SH / SZ / BJ / HK / US


def parse_code(raw: str) -> MarketCode:
    """解析标准代码（强制后缀）。后缀大小写不敏感。"""
    s = (raw or "").strip().upper()
    if "." not in s:
        raise ValueError(
            f"代码必须带市场后缀（如 600519.SH / 920002.BJ / 00700.HK / AAPL.US），收到：{raw!r}"
        )
    code, _, suffix = s.rpartition(".")
    if suffix not in _SUFFIX_MARKET:
        raise ValueError(
            f"不支持的市场后缀 {suffix}（支持 SH/SZ/BJ/HK/US），收到：{raw!r}"
        )
    market = _SUFFIX_MARKET[suffix]
    if market in ("A", "BJ"):
        if not (code.isdigit() and len(code) == _CODE_LEN[market]):
            raise ValueError(
                f"{suffix} 市场需要 {_CODE_LEN[market]} 位数字代码（如 600519.SH / 920002.BJ），收到：{raw!r}"
            )
    elif market == "HK":
        if not (code.isdigit() and len(code) == _CODE_LEN["HK"]):
            raise ValueError(f"港股需要 5 位数字代码（如 00700.HK），收到：{raw!r}")
    else:  # US
        if not code.isalpha():
            raise ValueError(f"美股需要字母代码（如 AAPL.US），收到：{raw!r}")
    return MarketCode(market=market, code=code, suffix=suffix)


def to_sina(mc: MarketCode) -> str:
    """新浪接口代码。A/B 股带 sh/sz 前缀（900 沪B 归 sh、200 深B 归 sz，同通道），
    北交所 bj 前缀，港美股裸码/字母。"""
    if mc.market == "A":
        return ("sh" if mc.suffix == "SH" else "sz") + mc.code
    if mc.market == "BJ":
        return "bj" + mc.code
    return mc.code  # HK 5 位裸码 / US 字母


def to_ifind(mc: MarketCode) -> str:
    """iFinD 代码。A/B/北交所原样；港股 4 位带前导零（00700 → 0700.HK）；
    美股返回 code.US 占位，实际 .O/.N 后缀由 iFinD provider 用 THS_HQ 探测。"""
    if mc.market == "HK":
        bare = mc.code.lstrip("0") or "0"
        return bare.zfill(4) + ".HK"
    if mc.market == "US":
        return mc.code + ".US"
    return mc.code + "." + mc.suffix


def to_eastmoney(mc: MarketCode) -> str:
    """东财接口代码。A/B/港股裸码；美股 105. 前缀（105.AAPL）。"""
    if mc.market == "US":
        return "105." + mc.code
    return mc.code
