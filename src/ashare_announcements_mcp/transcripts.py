"""美股电话会议（earnings call transcript）通道。

数据流：EDGAR 10-Q/10-K（XBRL 财季字段）→ Alpha Spread URL → 下载正文缓存。
- 报告列表复用公告档案（query_announcements 已有 10-Q/10-K items）
- 10-Q/10-K HTML 复用 us_edgar.cache_filing_html（下载/缓存，重复调用零成本）
- 只新增 Alpha Spread 特有逻辑：URL 构造、正文抓取解析、索引缓存

财季标签：以公司申报为准（DocumentFiscalYearFocus + DocumentFiscalPeriodFocus），
不推算、不做偏移试探。上游（Alpha Spread）季度标签偶尔与申报财季错位
（正文第一句会注明实际报告期，由 AI 结合正文判断）。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from ashare_announcements_mcp.cache import load_cache, stock_cache_dir
from ashare_announcements_mcp.service import normalize_stock_code, resolve_company
from ashare_announcements_mcp.us_edgar import cache_filing_html
from ashare_announcements_mcp import us_edgar

ALPHA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
ALPHA_BASE = "https://www.alphaspread.com/security/nasdaq/{ticker}/investor-relations/earnings-call/q{num}-{year}"
TRANSCRIPTS_TTL = timedelta(days=30)
REQUEST_DELAY = 1.0  # Alpha 串行限速（秒）

# 10-K/10-Q 的 XBRL 财季字段
FISCAL_PATTERNS = {
    "period": re.compile(r"dei:DocumentFiscalPeriodFocus[^>]*>([^<]*)<"),
    "year": re.compile(r"dei:DocumentFiscalYearFocus[^>]*>([^<]*)<"),
    "end": re.compile(r"dei:DocumentPeriodEndDate[^>]*>([^<]*)<"),
}
# 10-K（年报）的 PeriodFocus=FY → Q4 电话会议
PERIOD_TO_Q = {"Q1": "1", "Q2": "2", "Q3": "3", "FY": "4"}


def _transcripts_path(code: str) -> Path:
    return stock_cache_dir(code) / "transcripts.json"


def _body_dir(code: str) -> Path:
    path = stock_cache_dir(code) / "transcripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _body_path(code: str, fiscal_quarter: str) -> Path:
    return _body_dir(code) / f"{fiscal_quarter}.json"


def load_transcripts(code: str) -> dict[str, Any]:
    path = _transcripts_path(code)
    if not path.exists():
        return {"items": [], "meta": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": [], "meta": {}}
    return data if isinstance(data, dict) else {"items": [], "meta": {}}


def save_transcripts(code: str, items: list[dict[str, Any]], meta: dict[str, Any]) -> Path:
    path = _transcripts_path(code)
    payload = {
        "meta": {**meta, "updated_at": datetime.now().astimezone().isoformat(timespec="seconds")},
        "items": items,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def _fiscal_fields(code: str, accession: str, url: str) -> dict[str, str]:
    """从 10-Q/10-K HTML 提取 XBRL 财季字段；HTML 复用 us_edgar 下载/缓存。"""
    path = cache_filing_html(code, accession, url)
    html = path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    for key, pattern in FISCAL_PATTERNS.items():
        m = pattern.search(html)
        if m:
            out[key] = m.group(1).strip()
    return out


def _build_alpha_url(ticker: str, q_num: str, year: str) -> str:
    return ALPHA_BASE.format(ticker=ticker.lower(), num=q_num, year=year)


def _parse_comments(html: str) -> list[dict[str, str]]:
    """解析 Alpha Spread 正文 comment 块：每块 author + text。"""
    parts: list[dict[str, str]] = []
    for m in re.finditer(
        r'<div class="author">(.*?)(?=<div class="comment">|<div class="author">)', html, re.S
    ):
        block = m.group(1)
        am = re.match(r"\s*(.*?)(?:\s*<!--|\s*<div)", block, re.S)
        author = re.sub(r"<[^>]+>", "", am.group(1)).strip() if am else ""
        tm = re.search(r'<div class="text">(.*?)</div>', block, re.S)
        if not tm:
            continue
        text = re.sub(r"<br\s*/?>", "\n", tm.group(1))
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"[ \t]+\n", "\n", text)  # 行尾缩进噪声
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        parts.append({"author": author, "text": text})
    return parts


def _first_line(comments: list[dict[str, str]]) -> str:
    """正文第一句（开场白），用于确认实际报告期。"""
    for c in comments:
        text = c.get("text", "")
        if text:
            return text[:200]
    return ""


def _fetch_alpha(url: str) -> tuple[int, str]:
    """GET Alpha Spread 页面；裸 UA（完整浏览器指纹反而 403）。"""
    resp = requests.get(url, headers={"User-Agent": ALPHA_UA}, timeout=30)
    return resp.status_code, resp.text


def _download_body(
    code: str, ticker: str, q_num: str, year: str
) -> tuple[str | None, dict[str, Any]]:
    """下载单个财季的 Alpha 正文；返回 (fiscal_quarter, meta)。"""
    url = _build_alpha_url(ticker, q_num, year)
    status, html = _fetch_alpha(url)
    if status == 404:
        return None, {"status": "missing"}
    if status != 200:
        return None, {"status": "temporary_failed", "http_status": status}
    comments = _parse_comments(html)
    if not comments:
        return None, {"status": "missing"}
    first = _first_line(comments)
    # 开场白提取电话会日期：Last updated / 页内日期不在 HTML 里，用报告期作 call_date 的近似——不推算，留空
    body = {
        "meta": {
            "source": "alphaspread",
            "url": url,
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "first_line": first,
        },
        "body": comments,
    }
    return first, body


def _report_items(code: str) -> list[dict[str, Any]]:
    """从公告档案中筛出 10-Q/10-K（含 report_date/accession/url）。

    旧版建档缓存可能缺 report_date 字段（早期 _format_us_filing 未写），
    此时从 EDGAR submissions 按 accession 补齐（复用 fetch_submissions，报告期为上游原始字段）。
    """
    cached = load_cache(code)
    items = cached.get("items") or []
    reports = [item for item in items if str(item.get("form") or "") in ("10-Q", "10-K")]
    missing = [item for item in reports if not item.get("report_date")]
    if missing:
        try:
            cik = _company_cik(code)
            if cik:
                submissions = us_edgar.fetch_submissions(cik)
                by_accession = {
                    str(s.get("accession") or ""): s.get("report_date") or ""
                    for s in submissions.get("items") or []
                }
                for item in missing:
                    item["report_date"] = by_accession.get(str(item.get("accession") or ""), "")
        except Exception:
            pass  # 补齐失败则跳过该批（AI 可重建公告缓存）
    return [item for item in reports if item.get("report_date")]


def _company_cik(code: str) -> str | None:
    """从 companies.json 取 US 证券的 CIK。"""
    _key, securities = resolve_company(code)
    for sec in securities:
        if sec.get("market") == "US":
            return sec.get("cik") or ""
    return None


def sync_transcripts(code: str, ticker: str, force_refresh: bool = False) -> dict[str, Any]:
    """维护电话会议索引：以 10-Q/10-K 报告期为锚，构造 Alpha URL 下载正文。

    新鲜期 30 天；增量只处理本地没有的新报告期，已有且未过期不重试。
    force_refresh 时全量重探（404 的季度不重试——Alpha 明确没有的不重复请求）。
    """
    cached = load_transcripts(code)
    items = cached.get("items") or []
    meta = cached.get("meta") or {}

    fresh = False
    if not force_refresh and items:
        updated = meta.get("updated_at", "")
        if updated:
            try:
                updated_dt = datetime.fromisoformat(updated)
                fresh = datetime.now().astimezone() - updated_dt < TRANSCRIPTS_TTL
            except ValueError:
                fresh = False

    if fresh:
        return {"items": items, "meta": meta, "cache_hit": True, "new": 0}

    known = {str(item.get("report_date") or "") for item in items}
    reports = _report_items(code)

    changed = 0
    for item in reports:
        report_date = str(item.get("report_date") or "")
        form = str(item.get("form") or "")
        if not report_date or not item.get("accession"):
            continue
        if report_date in known and not force_refresh:
            continue  # 已有记录，增量跳过
        fields = _fiscal_fields(code, str(item["accession"]), str(item["url"]))
        period = fields.get("period", "")
        year = fields.get("year", "")
        if period not in PERIOD_TO_Q or not year:
            continue  # XBRL 字段缺失，跳过（AI 可从公告列表自行理解）
        q_num = PERIOD_TO_Q[period]
        fiscal_quarter = f"FY{year}-{period}"
        first_line, body = _download_body(code, ticker, q_num, year)
        record = {
            "fiscal_quarter": fiscal_quarter,
            "report_date": report_date,
            "form": form,
            "period_focus": period,
            "fiscal_year": year,
            "alpha_url": _build_alpha_url(ticker, q_num, year),
        }
        if first_line is None:
            record["status"] = body.get("status", "missing")
            if body.get("http_status"):
                record["http_status"] = body["http_status"]
        else:
            record["status"] = "ok"
            record["first_line"] = first_line
            body_path = _body_path(code, fiscal_quarter)
            temporary = body_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(body_path)
            record["body_file"] = str(body_path)
        # 替换同 report_date 的旧记录，追加新记录
        items = [it for it in items if str(it.get("report_date") or "") != report_date]
        items.append(record)
        changed += 1
        time.sleep(REQUEST_DELAY)

    items.sort(key=lambda it: str(it.get("report_date") or ""), reverse=True)
    save_transcripts(code, items, {"source": "alphaspread", "cache_complete": True})
    return {
        "items": items,
        "meta": {"source": "alphaspread", "cache_complete": True},
        "cache_hit": False,
        "new": changed,
    }


def query_transcripts(
    stock_code: str,
    period: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """查询电话会议索引；period 指定财季（如 FY2025-Q1）时返回该季正文。"""
    code = normalize_stock_code(stock_code)
    _company_key, securities = resolve_company(code)
    us = [s for s in securities if s.get("market") == "US"]
    if not us:
        return {
            "stock_code": code,
            "applicable": False,
            "reason": "该公司无电话会议（仅美股适用），不适用",
            "total_transcripts": 0,
            "results": [],
        }
    ticker = us[0]["code"]
    result = sync_transcripts(code, ticker, force_refresh=force_refresh)
    items = result["items"]

    if period:
        match = [it for it in items if str(it.get("fiscal_quarter") or "") == period]
        if not match:
            return {
                "stock_code": code,
                "applicable": True,
                "fiscal_quarter": period,
                "matched": 0,
                "results": [],
                "note": f"未找到财季 {period} 的电话会议（可能上游无收录或未开电话会）",
            }
        record = match[0]
        if record.get("status") != "ok":
            return {
                "stock_code": code,
                "applicable": True,
                "fiscal_quarter": period,
                "matched": 0,
                "results": [record],
                "note": f"该财季电话会议状态为 {record.get('status')}（上游未收录）",
            }
        body = json.loads(Path(record["body_file"]).read_text(encoding="utf-8"))
        return {
            "stock_code": code,
            "applicable": True,
            "fiscal_quarter": period,
            "report_date": record.get("report_date"),
            "matched": 1,
            "source": "alphaspread",
            "first_line": body["meta"].get("first_line", ""),
            "body": body["body"],
        }

    return {
        "stock_code": code,
        "applicable": True,
        "total_transcripts": len(items),
        "matched": len(items),
        "new_synced": result.get("new", 0),
        "cache_hit": result.get("cache_hit", False),
        "results": [
            {
                "fiscal_quarter": it.get("fiscal_quarter"),
                "report_date": it.get("report_date"),
                "form": it.get("form"),
                "status": it.get("status"),
                "first_line": it.get("first_line"),
            }
            for it in items
        ],
    }


def search_transcripts(stock_code: str, query: str) -> dict[str, Any]:
    """在全部已缓存电话会议正文中检索关键词，返回命中财季与片段。"""
    code = normalize_stock_code(stock_code)
    _company_key, securities = resolve_company(code)
    us = [s for s in securities if s.get("market") == "US"]
    if not us:
        return {
            "stock_code": code,
            "applicable": False,
            "reason": "该公司无电话会议（仅美股适用），不适用",
            "matched": 0,
            "results": [],
        }
    if not query or not query.strip():
        raise ValueError("query 不能为空")

    cached = load_transcripts(code)
    items = cached.get("items") or []
    keywords = [k for k in query.strip().lower().split() if k]

    hits = []
    for it in items:
        if it.get("status") != "ok" or not it.get("body_file"):
            continue
        try:
            body = json.loads(Path(it["body_file"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        segments = []
        for comment in body.get("body") or []:
            author = comment.get("author", "")
            text = comment.get("text", "")
            lower = text.lower()
            if all(k in lower for k in keywords):
                i = lower.find(keywords[0])
                snippet = text[max(0, i - 60): i + 180].replace("\n", " ")
                segments.append({"author": author, "snippet": snippet})
        if segments:
            hits.append(
                {
                    "fiscal_quarter": it.get("fiscal_quarter"),
                    "report_date": it.get("report_date"),
                    "matched_segments": len(segments),
                    "segments": segments[:5],
                }
            )

    return {
        "stock_code": code,
        "applicable": True,
        "query": query,
        "matched": len(hits),
        "results": hits,
    }
