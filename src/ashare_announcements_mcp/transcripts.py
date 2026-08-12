"""美股电话会议（earnings call transcript）通道。

数据流：公告列表（EDGAR submissions）→ 机械推算报告期序列 → Alpha Spread URL → 下载正文缓存。
- 公告列表复用 sync_edgar_archive（先同步增量，再读 announcements.json）
- 财季推算纯机械：锚定最近一份 10-K（= 财年结束 = Q4，year = 其 reportDate 年份），
  Q1→Q2→Q3→FY→年份+1→Q1 固定循环；不读 XBRL、不下载公告正文
- 历史下限：Alpha Spread 覆盖从 2018 财季起（实测），更早无数据
- 增量：推算集合 − 本地已保存 = 待获取；404 表示该财季电话会议未出（刚披露/未开），
  不保存、下次再试；force_refresh 重试全部 404/missing
- 上游季度标签偶尔与申报财季错位（如部分公司偏移一年），正文第一句注明实际报告期，
  由 AI 结合正文判断，不做代码级容错
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from ashare_announcements_mcp.cache import load_cache, stock_cache_dir
from ashare_announcements_mcp.service import normalize_stock_code, resolve_company, sync_edgar_archive
from ashare_announcements_mcp import us_edgar

ALPHA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
ALPHA_BASE = "https://www.alphaspread.com/security/nasdaq/{ticker}/investor-relations/earnings-call/q{num}-{year}"
MIN_YEAR = 2018  # Alpha Spread 历史覆盖下限（实测 AAPL/LULU 2018 起才有）
# 首次同步默认只下载最近 N 个财季（避免全量下载超时；更早的按需补下载）
RECENT_QUARTERS = 12
REQUEST_DELAY = 1.0  # Alpha 串行限速（秒）


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
        "meta": {**meta, "updated_at": date.today().isoformat()},
        "items": items,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def _company_cik(code: str) -> str | None:
    """从 companies.json 取 US 证券的 CIK。"""
    _key, securities = resolve_company(code)
    for sec in securities:
        if sec.get("market") == "US":
            return sec.get("cik") or ""
    return None


def _report_items(code: str) -> list[dict[str, Any]]:
    """从公告档案中筛出 10-Q/10-K（含 report_date/form/accession）。

    旧版建档缓存可能缺 report_date 字段（早期 _format_us_filing 未写），
    此时从 EDGAR submissions 按 accession 补齐（复用 fetch_submissions，报告期为上游原始字段）。
    """
    cached = load_cache(code)
    items = cached.get("items") or []
    reports: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("form") or "") in ("10-Q", "10-K"):
            if not item.get("accession"):
                continue
            reports.append(
                {
                    "report_date": str(item.get("report_date") or ""),
                    "form": str(item.get("form") or ""),
                    "accession": str(item["accession"]),
                }
            )
    missing = [r for r in reports if not r["report_date"]]
    if missing:
        try:
            cik = _company_cik(code)
            if cik:
                submissions = us_edgar.fetch_submissions(cik)
                by_accession = {
                    str(s.get("accession") or ""): s.get("report_date") or ""
                    for s in submissions.get("items") or []
                }
                for item in reports:
                    if not item["report_date"]:
                        item["report_date"] = by_accession.get(item["accession"], "")
        except Exception:
            pass  # 补齐失败则跳过该批（AI 可重建公告缓存）
    return [item for item in reports if item.get("report_date")]


def _add_months(value: date, months: int) -> date:
    """日期加 N 个月；财季结束日对齐月末（Q2=12-31、Q3=3-31 等）。"""
    import calendar

    month_index = value.year * 12 + (value.month - 1) + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    # 对齐月末：若原日期是该月最后一天，目标月也取最后一天（避免 12-31-3月=9-30 级联成 12-30）
    last_day = calendar.monthrange(value.year, value.month)[1]
    if value.day == last_day:
        day = calendar.monthrange(year, month)[1]
    return date(year, month, day)


def _derive_quarters(reports: list[dict[str, Any]]) -> list[dict[str, str]]:
    """机械推算报告期序列（基于公告列表真实报告期，不推算日期）。

    锚定最近一份 10-K：year = reportDate 年份，财年结束日 = reportDate（= 该财年 Q4/FY）。
    财季分配：同一财年内按时间顺序，锚点 10-K 之前的 10-Q 依次为 Q3、Q2、Q1；
    锚点 10-K 之后的 10-Q 属于下一财年 Q1、Q2…
    （Q1→Q2→Q3→FY→年份+1→Q1 固定循环，纯机械，不读 XBRL）
    范围：[max(MIN_YEAR, 最早报告期财年) , 最新报告期]。
    """
    if not reports:
        return []
    # 按 report_date 升序的真实报告期
    ordered = sorted(reports, key=lambda r: r["report_date"])

    # 锚点：最近一份 10-K
    k10s = [r for r in ordered if r["form"] == "10-K"]
    if k10s:
        anchor = k10s[-1]
        anchor_year = int(anchor["report_date"][:4])
    else:
        # 无 10-K（刚上市）：以最新报告期所在年份为锚
        anchor_year = int(ordered[-1]["report_date"][:4])

    quarters: list[dict[str, str]] = []
    # 从锚点往前倒序处理；每个 10-K 独立确定财年（year = report_date 年份），
    # 其后（时间更早）的 10-Q 按 Q3→Q2→Q1 归入该财年
    before = [r for r in ordered if r["report_date"] < anchor["report_date"]] if k10s else ordered[:-1]
    current_fy = anchor_year
    q_next = "Q3"
    for r in reversed(before):
        if r["form"] == "10-K":
            current_fy = int(r["report_date"][:4])
            quarters.append(
                {
                    "fiscal_quarter": f"FY{current_fy}-FY",
                    "report_date": r["report_date"],
                    "form": "10-K",
                }
            )
            q_next = "Q3"
            continue
        quarters.append(
            {
                "fiscal_quarter": f"FY{current_fy}-{q_next}",
                "report_date": r["report_date"],
                "form": "10-Q",
            }
        )
        q_next = {"Q3": "Q2", "Q2": "Q1", "Q1": None}.get(q_next)
        if q_next is None:
            # 该财年已分完 Q1-Q3，剩余 10-Q 属于更早财年（由下一轮 10-K 重新对齐）
            q_next = "Q3"
    # 锚点本身
    if k10s:
        quarters.append(
            {
                "fiscal_quarter": f"FY{anchor_year}-FY",
                "report_date": anchor["report_date"],
                "form": "10-K",
            }
        )
    # 锚点之后：下一财年 Q1、Q2…
    if k10s:
        after = [r for r in ordered if r["report_date"] > anchor["report_date"]]
    else:
        after = [ordered[-1]]
    y_after = anchor_year + 1
    q_idx = 1
    for r in after:
        quarters.append(
            {
                "fiscal_quarter": f"FY{y_after}-Q{q_idx}",
                "report_date": r["report_date"],
                "form": "10-Q",
            }
        )
        q_idx += 1
        if q_idx == 4:
            q_idx = 1
            y_after += 1
    # 过滤 MIN_YEAR 下限（财年标签年份）
    quarters = [q for q in quarters if int(q["fiscal_quarter"][2:6]) >= MIN_YEAR]
    return quarters


def _build_alpha_url(ticker: str, q_num: str, year: str) -> str:
    return ALPHA_BASE.format(ticker=ticker.lower(), num=q_num, year=year)


def _parse_comments(html: str) -> list[dict[str, str]]:
    """解析 Alpha Spread 正文 comment 块：每块 author + text。"""
    parts: list[dict[str, str]] = []
    # 末尾追加哨兵，保证最后一块 comment 也能匹配（正则依赖块后有分隔符）
    body = html + '<div class="comment">'
    for m in re.finditer(
        r'<div class="author">(.*?)(?=<div class="comment">|<div class="author">)', body, re.S
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
    """下载单个财季的 Alpha 正文；返回 (first_line, meta)。"""
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
    body = {
        "meta": {
            "source": "alphaspread",
            "url": url,
            "fetched_at": date.today().isoformat(),
            "first_line": first,
        },
        "body": comments,
    }
    return first, body


def sync_transcripts(code: str, ticker: str, force_refresh: bool = False,
                     only_recent: bool = True,
                     target_period: str | None = None) -> dict[str, Any]:
    """维护电话会议索引：先同步公告列表，再机械推算报告期，差集下载正文。

    每次调用都同步公告列表增量（复用 sync_edgar_archive，廉价）；
    已保存财季不重试；404 财季保持未保存（下次再试）；
    force_refresh 时重试全部 missing/temporary_failed 财季。
    only_recent=True（默认）：只下载最近 RECENT_QUARTERS 个财季（首次同步防超时），
    更早的财季保持未下载，query_transcripts(period=早期季) 时按需补下载。
    target_period 指定（如 FY2020-Q1）：只下载该财季（按需补下载早期季，避免全量）。
    """
    # 1. 同步公告列表（保证最新）
    cik = _company_cik(code)
    if cik:
        sync_edgar_archive(code, cik)

    cached = load_transcripts(code)
    items = cached.get("items") or []

    # 2. 读公告列表 → 推算报告期集合
    reports = _report_items(code)
    derived = _derive_quarters(reports)
    derived_by_date = {q["report_date"]: q for q in derived}
    reported_dates = {r["report_date"] for r in reports}

    # 3. 差集 = 推算集合 − 已保存集合
    saved_by_date = {str(it.get("report_date") or "") for it in items}
    to_fetch = [
        q for q in derived
        if q["report_date"] not in saved_by_date
        and q["report_date"] in reported_dates  # 财报已披露才请求
    ]
    # only_recent：只下载最近 RECENT_QUARTERS 个财季（按 report_date 倒序取前 N）
    if only_recent and len(to_fetch) > RECENT_QUARTERS:
        to_fetch = sorted(to_fetch, key=lambda q: q["report_date"], reverse=True)[:RECENT_QUARTERS]
    # target_period：只下载指定财季（按需补下载早期季）
    if target_period:
        to_fetch = [q for q in to_fetch if q["fiscal_quarter"] == target_period]
    if force_refresh:
        for it in items:
            if it.get("status") in ("missing", "temporary_failed"):
                q = derived_by_date.get(str(it.get("report_date") or ""))
                if q and q["report_date"] in reported_dates:
                    to_fetch.append(q)

    # 4. 下载差集
    changed = 0
    for q in to_fetch:
        fiscal_quarter = q["fiscal_quarter"]
        q_num = fiscal_quarter.split("-")[-1].lstrip("Q") or "4"
        if q_num == "FY":
            q_num = "4"
        year = fiscal_quarter.split("-")[0][2:]
        first_line, body = _download_body(code, ticker, q_num, year)
        record = {
            "fiscal_quarter": fiscal_quarter,
            "report_date": q["report_date"],
            "form": q["form"],
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
        items = [it for it in items if str(it.get("report_date") or "") != q["report_date"]]
        items.append(record)
        changed += 1
        time.sleep(REQUEST_DELAY)

    items.sort(key=lambda it: str(it.get("report_date") or ""), reverse=True)
    save_transcripts(code, items, {"source": "alphaspread", "cache_complete": True})
    return {
        "items": items,
        "meta": {"source": "alphaspread", "cache_complete": True},
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
    # 无 period：常规同步（仅最近 RECENT_QUARTERS 季）
    result = sync_transcripts(code, ticker, force_refresh=force_refresh,
                              only_recent=True)
    items = result["items"]

    if period:
        match = [it for it in items if str(it.get("fiscal_quarter") or "") == period]
        # 目标财季未下载（早期季或首次同步范围外）：按需单独补下载该季
        if not match or match[0].get("status") not in ("ok", "missing"):
            result = sync_transcripts(code, ticker, force_refresh=force_refresh,
                                      only_recent=False, target_period=period)
            items = result["items"]
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
