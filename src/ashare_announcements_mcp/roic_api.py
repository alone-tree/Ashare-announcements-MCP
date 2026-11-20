"""ROIC.ai 电话会议 API 来源适配（电话会第二来源；免费档：每公司最近 2 场、5 次/分钟）。

官方文档：https://www.roic.ai/api/docs/earnings-calls/list（列表）与
https://www.roic.ai/api/docs/earnings-calls/transcript（raw 正文）。2026-11-20 实测：

- 列表：GET /v3.0.0/company-events?identifier=&content=transcript&order=desc，
  identifier 必须带交易所前缀（如 NASDAQ:ROST、HKEX:700），纯代码返回 400。
- 正文：GET /v3.0.0/documents/transcripts/{trraw_id}/raw，无发言人标注的纯文本；
  校订稿（edited）需付费档，不使用。
- 限额：有效 key 的每个请求都计数（200/400/404 同样扣减），429 本身不计数；
  429 带 retry-after（秒）与 x-ratelimit-reset（窗口纪元秒）。本模块不自动等待重试，
  抛 RoicRateLimited 把等待秒数交给调用方。
- 免费窗口：每公司最近 2 场，超出返回 402（RoicOutOfWindow）。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

from ashare_announcements_mcp.cache import app_root
from ashare_announcements_mcp.us_edgar import EDGAR_HEADERS

API_BASE = "https://api.roic.ai/v3.0.0"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)
FREE_RECENT_QUARTERS = 2  # 免费档每公司可见的最近场数（402 窗口）


class RoicRateLimited(RuntimeError):
    """429 限流：带 retry_after_seconds 与 reset_epoch，调用方自行决定等待重试。"""

    def __init__(self, retry_after_seconds: int, reset_epoch: int | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        self.reset_epoch = reset_epoch
        reset = ""
        if reset_epoch:
            reset_at = datetime.fromtimestamp(reset_epoch, tz=timezone.utc)
            reset = f"，{reset_at.strftime('%H:%M:%S')} UTC 后窗口恢复"
        super().__init__(f"ROIC 限流：{retry_after_seconds} 秒后可重试{reset}")


class RoicAuthError(RuntimeError):
    """401：API key 无效。"""


class RoicOutOfWindow(RuntimeError):
    """402：超出免费档窗口（每公司最近 2 场）。"""


def load_api_key() -> str:
    """API key：环境变量 ROIC_API_KEY 优先，其次 config.yaml 的 roic.api_key。"""
    env = os.environ.get("ROIC_API_KEY", "").strip()
    if env:
        return env
    path = app_root() / "config.yaml"
    if not path.exists():
        return ""
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - 配置缺失/损坏时视为未配置
        return ""
    return str((data.get("roic") or {}).get("api_key") or "").strip()


def _request(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """GET 一次 ROIC 请求（自动附 apikey）；连接异常重试，429/401/402 抛结构化异常，404 返回 None。"""
    api_key = load_api_key()
    if not api_key:
        raise RuntimeError("ROIC API key 未配置（config.yaml roic.api_key 或环境变量 ROIC_API_KEY）")
    last: Exception | None = None
    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{API_BASE}{path}",
                params={**params, "apikey": api_key},
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            break
        except Exception as exc:  # noqa: BLE001 - 代理/网络抖动统一重试
            last = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    if resp is None:
        raise RuntimeError(f"ROIC 请求失败（已重试 3 次）：{type(last).__name__}: {last}")
    if resp.status_code == 429:
        raise RoicRateLimited(
            int(resp.headers.get("retry-after") or 0),
            int(resp.headers.get("x-ratelimit-reset") or 0) or None,
        )
    if resp.status_code == 401:
        raise RoicAuthError("ROIC API key 无效（401 authentication_error，请检查 roic.api_key）")
    if resp.status_code == 402:
        raise RoicOutOfWindow("超出 ROIC 免费档窗口（402：每公司最近 2 场）")
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise RuntimeError(f"ROIC HTTP {resp.status_code}：{resp.text[:200]}")
    return resp.json()


def _symbols_cache_path() -> Path:
    return app_root() / "cache" / "roic_symbols.json"


def resolve_identifier(ticker: str, market: str, cik: str = "") -> str:
    """内部代码 → ROIC identifier；解析结果永久缓存（交易所不会变）。

    US：交易所前缀从 EDGAR submissions 元数据 exchanges 解析（免费、不耗 ROIC 额度）；
    HK：HKEX: + 五位代码去前导零（00700 → HKEX:700，2026-11-20 实测）。
    """
    ticker = str(ticker).upper()
    if market == "H":
        return "HKEX:" + ticker.lstrip("0")
    cache_path = _symbols_cache_path()
    cached: dict[str, str] = {}
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = {}
    if ticker in cached:
        return cached[ticker]
    if not cik:
        raise RuntimeError(f"解析 {ticker} 的 ROIC identifier 需要 CIK（US 证券建档时保存）")
    resp = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        headers=EDGAR_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    exchanges = resp.json().get("exchanges") or []
    if not exchanges:
        raise RuntimeError(f"EDGAR 元数据没有 {ticker} 的交易所字段，无法构造 ROIC identifier")
    identifier = f"{str(exchanges[0]).upper().replace(' ', '')}:{ticker}"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cached[ticker] = identifier
    temporary = cache_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(cache_path)
    return identifier


def list_recent(identifier: str, limit: int = FREE_RECENT_QUARTERS) -> list[dict[str, Any]]:
    """最近财季事件列表（含 trraw_ id）；每场一个 reporting period，无内容的不列出。"""
    data = _request(
        "/company-events",
        {"identifier": identifier, "content": "transcript", "order": "desc", "limit": limit},
    )
    return (data or {}).get("data") or []


def fetch_raw(transcript_id: str) -> str:
    """取 raw 正文（无发言人标注纯文本）。"""
    data = _request(f"/documents/transcripts/{transcript_id}/raw", {})
    text = (data or {}).get("text") or ""
    if not text:
        raise RuntimeError(f"ROIC raw 正文为空：{transcript_id}")
    return text
