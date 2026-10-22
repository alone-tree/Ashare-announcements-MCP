"""美股电话会议（earnings call transcript）通道。

数据源：stockanalysis.com（站点级提取器，2026-10-22 起唯一正文源）
- 索引页 /stocks/{ticker}/transcripts/ 直接列出全部电话会（“Earnings Call: Q2 2026”+链接），
  标签就是公司财季（META Q2 2026、NVDA Q2 2027），不需要推算，也不需要 cookie/浏览器：
  纯 requests + 普通 UA 即可 200（Alpha Spread 的 cf_clearance 绑定出口 IP，换节点即 403，
  2026-09 起长期失效；AlphaStreet 整站 CloudFront 403，二者均已退役）。
- 正文页按 turn 分块：div.border-t... 内含 speaker（div.text-lg.font-bold）与段落 <p>，
  站点级规则，不做公司级适配。
- report_date（报告期）只从本地公告缓存里的 10-Q/10-K 反查，有则附上，没有留空——
  是否“有电话会”完全由索引页决定（20-F/6-K 公司 TSM/BABA 等同样可用）。
- 首次同步默认只下载最近 RECENT_QUARTERS 季，更早的按需补下载（target_period）。
- 状态语义：ok=正文已缓存；missing=页面 404（该季未收录）；failed=网络/HTTP 异常（带 http_status），
  不把失败冒充“上游未收录”。
"""

from __future__ import annotations

import html as html_mod
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

from ashare_announcements_mcp.cache import load_cache, stock_cache_dir
from ashare_announcements_mcp.service import normalize_stock_code, resolve_company, sync_edgar_archive

SA_BASE = "https://stockanalysis.com/stocks/{ticker}/transcripts/"
SA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)
# 首次同步默认只下载最近 N 个财季（避免全量下载超时；更早的按需补下载）
RECENT_QUARTERS = 12
REQUEST_DELAY = 1.0  # 串行限速（秒）

_INDEX_ENTRY = re.compile(
    r'href="((?:https://stockanalysis\.com)?/(?:stocks|quote)/[^"]+/transcripts/\d+-q(\d)-(\d{4})/)"'
)
# 美股代码页的 transcripts 链接目标（ADR 常指向主上市代码，如 TSM → TPE-2330）
_LINK_SYMBOL = re.compile(r'transcriptsLinkSymbol:"([A-Za-z0-9.\-]+)"')


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
    path.parent.mkdir(parents=True, exist_ok=True)
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
            from ashare_announcements_mcp import us_edgar

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
            pass  # 补齐失败则跳过该批（报告期只是附注，不影响取正文）
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

    锚定最近一份 10-K：year = reportDate 年份，财年结束日 = reportDate（= 该财年 Q4）。
    财季分配：同一财年内按时间顺序，锚点 10-K 之前的 10-Q 依次为 Q3、Q2、Q1；
    锚点 10-K 之后的 10-Q 属于下一财年 Q1、Q2…
    （Q1→Q2→Q3→Q4→年份+1→Q1 固定循环，纯机械，不读 XBRL）
    仅用于把财季标签对上报告期（report_date），是否存在电话会由 stockanalysis 索引决定。
    """
    if not reports:
        return []
    ordered = sorted(reports, key=lambda r: r["report_date"])

    k10s = [r for r in ordered if r["form"] == "10-K"]
    if k10s:
        anchor = k10s[-1]
        anchor_year = int(anchor["report_date"][:4])
    else:
        anchor_year = int(ordered[-1]["report_date"][:4])

    quarters: list[dict[str, str]] = []
    before = [r for r in ordered if r["report_date"] < anchor["report_date"]] if k10s else ordered[:-1]
    current_fy = anchor_year
    q_next = "Q3"
    for r in reversed(before):
        if r["form"] == "10-K":
            current_fy = int(r["report_date"][:4])
            quarters.append(
                {
                    "fiscal_quarter": f"FY{current_fy}-Q4",
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
            q_next = "Q3"
    if k10s:
        quarters.append(
            {
                "fiscal_quarter": f"FY{anchor_year}-Q4",
                "report_date": anchor["report_date"],
                "form": "10-K",
            }
        )
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
    return quarters


def _report_dates(code: str) -> dict[str, dict[str, str]]:
    """财季标签 → {report_date, form}；只有 10-Q/10-K 公司才有，没有则空表。"""
    return {
        q["fiscal_quarter"]: {"report_date": q["report_date"], "form": q["form"]}
        for q in _derive_quarters(_report_items(code))
    }


def _fetch_html(url: str) -> tuple[int, str]:
    """GET 目标页面，返回 (status_code, text)。

    代理链路偶发断连（RemoteDisconnected/ProxyError），重试两次；仍失败则上抛，
    由调用方标记 failed，不冒充「未收录」。
    """
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers={"User-Agent": SA_UA}, timeout=40)
            return resp.status_code, resp.text
        except Exception as exc:  # noqa: BLE001 - 网络异常统一重试
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败（已重试 3 次）：{type(last_error).__name__}: {last_error}")


def _index_url(ticker: str) -> str:
    return SA_BASE.format(ticker=ticker.lower())


def _cross_listing_index_url(ticker: str) -> str | None:
    """美股代码页没有 transcripts 时的兜底：读个股页的 transcriptsLinkSymbol。

    ADR/外国发行人的电话会常挂在主上市代码下（TSM → TPE-2330、BABA → HKG-9988，
    ASML → AMS-ASML…）；个股页内嵌 transcriptsLinkSymbol，属于站点级规则，
    不写公司特例表。符号形如 "TPE-2330" 走 /quote/{exch}/{code}/transcripts/；
    纯代码（如 META）说明本来就没有其他挂载点，返回 None。
    """
    status, html = _fetch_html(f"https://stockanalysis.com/stocks/{ticker.lower()}/")
    if status != 200:
        return None
    match = _LINK_SYMBOL.search(html)
    if not match or "-" not in match.group(1):
        return None
    exchange, code = match.group(1).split("-", 1)
    return f"https://stockanalysis.com/quote/{exchange.lower()}/{code}/transcripts/"


def _parse_index(html: str) -> dict[tuple[int, int], str]:
    """索引页 → {(财年, 季度号): 相对 URL}；只收 'Earnings Call' 的 qN-YYYY 条目。"""
    entries: dict[tuple[int, int], str] = {}
    for href, q_num, year in _INDEX_ENTRY.findall(html):
        key = (int(year), int(q_num))
        if key not in entries:
            entries[key] = href
    return entries


def _clean(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", fragment)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    return text.strip()


def _parse_transcript(html: str) -> list[dict[str, str]]:
    """正文页 → [{author, text}]；按 turn 分块（div.border-t + div.text-lg.font-bold）。"""
    start = html.find('id="transcript-panel-full"')
    body = html[start:] if start != -1 else html
    end = body.find('id="transcript-panel-')
    if end > 0:
        body = body[:end]

    parts: list[dict[str, str]] = []
    for chunk in re.split(r'<div class="border-t border-sharp pt-5', body)[1:]:
        speaker = re.search(r'<div class="text-lg font-bold[^"]*">(.*?)</div>', chunk, re.S)
        if not speaker:
            continue
        author = _clean(speaker.group(1))
        rest = chunk[speaker.end():]
        paragraphs = [_clean(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", rest, re.S)]
        text = "\n".join(p for p in paragraphs if p)
        if text:
            parts.append({"author": author, "text": text})
    return parts


def _download_body(code: str, url: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """下载单个财季正文；返回 (body|None, meta)。

    meta.status：ok / missing（404）/ failed（其他 HTTP 或解析不出轮次）。
    """
    try:
        status, html = _fetch_html(url)
    except Exception as exc:  # 网络异常：明确报错，不冒充未收录
        return None, {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:200]}
    if status == 404:
        return None, {"status": "missing"}
    if status != 200:
        return None, {"status": "failed", "http_status": status}
    turns = _parse_transcript(html)
    if not turns:
        return None, {"status": "failed", "error": "正文页解析不出发言轮次（站点结构可能改版）"}
    return {
        "meta": {"source": "stockanalysis", "url": url, "fetched_at": date.today().isoformat()},
        "body": turns,
    }, {"status": "ok"}


def sync_transcripts(code: str, ticker: str, force_refresh: bool = False,
                     only_recent: bool = True,
                     target_period: str | None = None) -> dict[str, Any]:
    """维护电话会议索引：拉 stockanalysis 索引页，差集下载正文。

    - 索引页就是“有哪些财季电话会”的唯一依据（不再推算、不再猜 URL）；
    - report_date/form 从本地 10-Q/10-K 反查（没有则留空）；
    - 已缓存 ok 的财季不重下；missing/failed 每次同步重试；force_refresh 重试全部非 ok；
    - only_recent=True（默认）只下载最近 RECENT_QUARTERS 季，更早的按需补（target_period）。
    """
    cik = _company_cik(code)
    if cik:
        sync_edgar_archive(code, cik)  # 仅为 report_date 提供最新 10-Q/10-K

    index_url = _index_url(ticker)
    status, html = _fetch_html(index_url)
    if status == 404:
        # 美股代码页无电话会（ADR/外国发行人常见）→ 走主上市代码
        cross_url = _cross_listing_index_url(ticker)
        if cross_url:
            status, html = _fetch_html(cross_url)
            index_url = cross_url
    if status == 404:
        # 站点确实没有该公司的电话会页面：保留既有缓存，不报错
        cached_items = load_transcripts(code)["items"]
        return {"items": cached_items, "meta": {"source": "stockanalysis", "cache_complete": True},
                "new": 0, "index_available": False}
    if status != 200:
        raise RuntimeError(f"stockanalysis 索引页请求失败：HTTP {status}")
    entries = _parse_index(html)
    if not entries:
        raise RuntimeError("stockanalysis 索引页没有解析到任何电话会（站点结构可能改版）")

    cached = {str(it.get("fiscal_quarter") or ""): it for it in load_transcripts(code)["items"]}
    report_info = _report_dates(code)

    items: list[dict[str, Any]] = []
    for (year, q_num), url in sorted(entries.items(), reverse=True):
        label = f"FY{year}-Q{q_num}"
        info = report_info.get(label) or {}
        old = cached.get(label) or {}
        item: dict[str, Any] = {
            "fiscal_quarter": label,
            "report_date": info.get("report_date") or str(old.get("report_date") or ""),
            "form": info.get("form") or str(old.get("form") or ""),
            "url": url if url.startswith("http") else f"https://stockanalysis.com{url}",
        }
        if (
            not force_refresh
            and old.get("status") == "ok"
            and old.get("body_file")
            and Path(str(old["body_file"])).exists()
        ):
            item["status"] = "ok"
            item["body_file"] = old["body_file"]
            item["source"] = old.get("source", "stockanalysis")
            # 复用旧正文时保留其原始 URL（可能是已退役来源），便于追溯内容出处
            item["url"] = str(old.get("url") or old.get("alpha_url") or item["url"])
        items.append(item)

    # only_recent：只看最近 RECENT_QUARTERS 季（含已缓存），更早的等 period 指定再补
    scope = items[:RECENT_QUARTERS] if only_recent and not target_period else items
    to_fetch = [it for it in scope if it.get("status") != "ok"]
    if target_period:
        to_fetch = [it for it in to_fetch if it["fiscal_quarter"] == target_period]

    changed = 0
    for item in to_fetch:
        fiscal_quarter = str(item["fiscal_quarter"])
        body, meta = _download_body(code, str(item["url"]))
        if body is None:
            item["status"] = meta.get("status", "failed")
            if meta.get("http_status"):
                item["http_status"] = meta["http_status"]
            if meta.get("error"):
                item["error"] = meta["error"]
        else:
            item["status"] = "ok"
            item["source"] = body["meta"]["source"]
            body_path = _body_path(code, fiscal_quarter)
            temporary = body_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(body_path)
            item["body_file"] = str(body_path)
        changed += 1
        time.sleep(REQUEST_DELAY)

    save_transcripts(code, items, {"source": "stockanalysis", "cache_complete": True,
                                   "index_url": index_url})
    return {
        "items": items,
        "meta": {"source": "stockanalysis", "cache_complete": True, "index_url": index_url},
        "new": changed,
    }


def query_transcripts(
    stock_code: str,
    period: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """查询电话会议索引；period 指定财季（如 FY2026-Q3）时返回该季正文。"""
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
    result = sync_transcripts(code, ticker, force_refresh=force_refresh, only_recent=True)
    items = result["items"]
    if result.get("index_available") is False and not items:
        return {
            "stock_code": code,
            "applicable": True,
            "total_transcripts": 0,
            "matched": 0,
            "results": [],
            "note": "stockanalysis 没有该公司的电话会页面（ADR/外国私人发行人常见），暂无数据",
        }

    if period:
        match = [it for it in items if str(it.get("fiscal_quarter") or "") == period]
        if not match:
            return {
                "stock_code": code,
                "applicable": True,
                "fiscal_quarter": period,
                "matched": 0,
                "results": [],
                "note": f"未找到财季 {period} 的电话会议（stockanalysis 索引里没有该季）",
            }
        record = match[0]
        if record.get("status") != "ok":
            # 目标财季未缓存（早期季或首次同步范围外）：按需单独补下载该季
            result = sync_transcripts(code, ticker, force_refresh=force_refresh,
                                      only_recent=False, target_period=period)
            items = result["items"]
            match = [it for it in items if str(it.get("fiscal_quarter") or "") == period]
            record = match[0] if match else record
        if record.get("status") != "ok":
            status = record.get("status")
            if status == "missing":
                note = f"该财季页面 404：上游未收录（尚未开或刚开完，等一两天）"
            else:
                detail = record.get("error") or f"HTTP {record.get('http_status')}"
                note = f"获取失败：{detail}"
            return {
                "stock_code": code,
                "applicable": True,
                "fiscal_quarter": period,
                "matched": 0,
                "results": [record],
                "note": note,
            }
        body = json.loads(Path(record["body_file"]).read_text(encoding="utf-8"))
        return {
            "stock_code": code,
            "applicable": True,
            "fiscal_quarter": period,
            "report_date": record.get("report_date"),
            "matched": 1,
            "source": body.get("meta", {}).get("source", "stockanalysis"),
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
