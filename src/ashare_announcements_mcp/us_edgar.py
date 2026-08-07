"""SEC EDGAR 通道：美股公司的建档、提交列表与文档处理。

对外语义与东财通道一致（列公告→读公告→搜公告），内部数据源为 SEC EDGAR：
- 建档：company_tickers.json 做 ticker→CIK 精确映射（本地缓存 24h）
- 列表：submissions/CIK.json 返回最近 1000 条提交 + 历史分片
- 文档：下载 HTML 正文，按 page-break 切虚拟页（无分页时按结构切块），转 Markdown
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from ashare_announcements_mcp.cache import app_root, extraction_dir

EDGAR_HEADERS = {"User-Agent": "A-share-announcements-MCP research contact@example.com"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"

TICKERS_CACHE_TTL = timedelta(hours=24)
PAGE_BREAK_RE = re.compile(
    r'style="[^"]*page-break-(?:after|before)\s*:\s*(?:always|left|right)[^"]*"',
    re.IGNORECASE,
)
FALLBACK_BLOCK_TARGET = 4_000


def _tickers_cache_path() -> Path:
    return app_root() / "cache" / "edgar" / "company_tickers.json"


def _tickers_cache_fresh() -> bool:
    path = _tickers_cache_path()
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - mtime < TICKERS_CACHE_TTL


def _load_tickers(force: bool = False) -> dict[str, dict[str, Any]]:
    """读取 ticker→CIK 全量映射；本地缓存 24 小时，缺失或过期时重新下载。"""
    path = _tickers_cache_path()
    if not force and _tickers_cache_fresh():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {str(v["ticker"]).upper(): v for v in raw.values()}
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    response = requests.get(TICKERS_URL, headers=EDGAR_HEADERS, timeout=30)
    response.raise_for_status()
    raw = response.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(response.text, encoding="utf-8")
    temporary.replace(path)
    return {str(v["ticker"]).upper(): v for v in raw.values()}


def ticker_to_cik(ticker: str) -> str:
    """ticker→CIK 精确匹配；缓存查不到时强制刷新一次（应对刚上市公司）。"""
    text = str(ticker).strip().upper()
    tickers = _load_tickers()
    info = tickers.get(text)
    if not info:
        tickers = _load_tickers(force=True)
        info = tickers.get(text)
    if not info:
        raise ValueError(f"SEC 未找到该美股代码：{ticker}")
    return str(info["cik_str"]).zfill(10)


def cik_to_ticker(cik: str) -> str | None:
    tickers = _load_tickers()
    for info in tickers.values():
        if str(info["cik_str"]).zfill(10) == str(cik).zfill(10):
            return str(info["ticker"]).upper()
    return None


def fetch_submissions(cik: str) -> dict[str, Any]:
    """拉取提交列表：recent 1000 条 + 历史分片文件全部展开。"""
    response = requests.get(
        SUBMISSIONS_URL.format(cik=cik), headers=EDGAR_HEADERS, timeout=30
    )
    response.raise_for_status()
    data = response.json()
    return _expand_submissions(data)


def _expand_submissions(data: dict[str, Any]) -> dict[str, Any]:
    """把 submissions 的 recent 与历史分片合并为按时间倒序的完整列表。

    主文件结构：{"filings": {"recent": {...}, "files": [...]}}
    历史分片结构：顶层直接就是 recent 数组字段（无 filings 包装）。
    """
    recent = data.get("filings", {}).get("recent", {}) or data
    merged: list[dict[str, str]] = []

    for i in range(len(recent.get("form") or [])):
        merged.append(
            {
                "accession": str(recent["accessionNumber"][i]),
                "filing_date": str(recent["filingDate"][i]),
                "form": str(recent["form"][i]),
                "document": str(recent["primaryDocument"][i]),
                "description": str(recent["primaryDocDescription"][i] or ""),
                "items": str(recent.get("items", [None] * len(recent["form"]))[i] or ""),
                "report_date": str(recent.get("reportDate", [None] * len(recent["form"]))[i] or ""),
            }
        )

    files = data.get("filings", {}).get("files") or []
    for file_info in files:
        name = file_info.get("name")
        if not name:
            continue
        url = f"https://data.sec.gov/submissions/{name}"
        response = requests.get(url, headers=EDGAR_HEADERS, timeout=30)
        response.raise_for_status()
        chunk = response.json()
        older = chunk.get("filings", {}).get("recent", {}) or chunk
        for i in range(len(older.get("form") or [])):
            merged.append(
                {
                    "accession": str(older["accessionNumber"][i]),
                    "filing_date": str(older["filingDate"][i]),
                    "form": str(older["form"][i]),
                    "document": str(older["primaryDocument"][i]),
                    "description": str(older["primaryDocDescription"][i] or ""),
                    "items": str(older.get("items", [None] * len(older["form"]))[i] or ""),
                    "report_date": str(older.get("reportDate", [None] * len(older["form"]))[i] or ""),
                }
            )

    merged.sort(key=lambda item: item["filing_date"], reverse=True)
    return {"items": merged, "cache_complete": True, "source": "edgar"}


def filing_url(cik: str, accession: str, document: str) -> str:
    return ARCHIVE_URL.format(cik=cik.lstrip("0"), accession=accession.replace("-", ""), doc=document)


def fetch_filing_html(url: str) -> str:
    response = requests.get(url, headers=EDGAR_HEADERS, timeout=60)
    response.raise_for_status()
    return response.text


# 8-K 披露条款编号 → 中文含义（Regulation SK Item）
FORM8K_ITEMS: dict[str, str] = {
    "1.01": "重大协议",
    "1.02": "协议终止",
    "1.03": "破产或接管",
    "1.04": "重大债务违约",
    "2.01": "重大资产收购/处置",
    "2.02": "经营业绩",
    "2.03": "重大债务",
    "2.04": "触发加速偿债",
    "2.05": "资产减值",
    "2.06": "实质性减值",
    "3.01": "退市或未达上市标准",
    "3.02": "未登记股权出售",
    "3.03": "优先股条款修改",
    "4.01": "会计师变更",
    "4.02": "不再信赖此前财报",
    "5.01": "控制权变更",
    "5.02": "高管离职/任命",
    "5.03": "章程或注册地变更",
    "5.04": "员工福利计划",
    "5.05": "道德准则修订",
    "5.06": "董事会变更",
    "5.07": "股东投票结果",
    "5.08": "股东大会",
    "6.01": "ABS资产支持证券",
    "7.01": "FD监管披露",
    "8.01": "其他重大事件",
    "9.01": "财务报表和附件",
}


# 常见 SEC 表单类型 → 中文含义（不覆盖的类型保持原样）
FORM_MEANINGS: dict[str, str] = {
    "10-K": "年报",
    "10-Q": "季报",
    "8-K": "重大事件公告",
    "20-F": "外国公司年报",
    "6-K": "外国公司报告",
    "4": "内部人士交易",
    "4/A": "内部人士交易(修正)",
    "3": "内部人士初始持股",
    "144": "拟出售股份",
    "SC 13D": "大股东持股披露(主动)",
    "SC 13D/A": "大股东持股披露(主动,修正)",
    "SC 13G": "大股东持股披露",
    "SC 13G/A": "大股东持股披露(修正)",
    "SCHEDULE 13D": "大股东持股披露(主动)",
    "SCHEDULE 13D/A": "大股东持股披露(主动,修正)",
    "SCHEDULE 13G": "大股东持股披露",
    "SCHEDULE 13G/A": "大股东持股披露(修正)",
    "DEF 14A": "股东委托书",
    "DEFA14A": "委托书补充材料",
    "DEF 14C": "股东信息声明",
    "S-1": "IPO招股书",
    "S-1/A": "IPO招股书(修正)",
    "S-4": "并购注册声明",
    "S-8": "股权激励注册",
    "424B1": "招股书补充",
    "424B2": "债券/票据发行说明书",
    "424B3": "招股书补充",
    "424B4": "招股书",
    "F-1": "外国公司IPO招股书",
    "SD": "冲突矿产披露",
    "ARS": "致股东年度报告",
    "8-K/A": "重大事件公告(修正)",
    "10-K/A": "年报(修正)",
    "10-Q/A": "季报(修正)",
    "425": "并购相关披露",
    "CORRESP": "SEC问询函回复",
    "UPLOAD": "SEC问询函",
}


def _translate_items(items: str) -> str:
    """把 8-K 条款编号翻译为中文含义，如 '2.02,9.01' → '2.02经营业绩, 9.01财务报表和附件'。"""
    parts = [p.strip() for p in str(items or "").split(",") if p.strip()]
    translated = []
    for part in parts:
        meaning = FORM8K_ITEMS.get(part)
        translated.append(f"{part}{meaning}" if meaning else part)
    return ", ".join(translated)


def _clean_html(html: str) -> str:
    """清理 XBRL 元数据区、脚本和样式。"""
    html = re.sub(r"<\?xml[^>]*\?>", "", html)
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    html = re.sub(r"<ix:header.*?</ix:header>", "", html, flags=re.S | re.I)
    html = re.sub(r"<ix:[a-zA-Z]+[^>]*>", "", html)
    html = re.sub(r"</ix:[a-zA-Z]+>", "", html)
    return html


def split_html_pages(html: str) -> list[str]:
    """按 page-break 切虚拟页；无分页标记时按 div/p 结构切块（兜底）。"""
    cleaned = _clean_html(html)
    parts = PAGE_BREAK_RE.split(cleaned)
    pages = [p for p in parts if re.sub(r"<[^>]+>", "", p).strip()]
    if len(pages) > 1:
        return pages
    return _split_blocks(cleaned)


def _split_blocks(html: str, target: int = FALLBACK_BLOCK_TARGET) -> list[str]:
    """兜底：按 div/p 文本块累积，达到目标字符数切一块。"""
    blocks = re.findall(r"<div[^>]*>(.*?)</div>|<p[^>]*>(.*?)</p>", html, flags=re.S)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for a, b in blocks:
        block = a or b
        text = re.sub(r"<[^>]+>", " ", block)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if current_len + len(text) > target and current:
            chunks.append(" ".join(current))
            current = []
            current_len = 0
        current.append(text)
        current_len += len(text)
    if current:
        chunks.append(" ".join(current))
    return chunks or [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()]


def html_to_markdown(html: str) -> str:
    """HTML 转 Markdown（markdownify），保留标题/段落/表格。"""
    from markdownify import markdownify as md

    cleaned = _clean_html(html)
    markdown = md(cleaned, heading_style="ATX")
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def build_html_index(stock_code: str, accession: str, html: str) -> dict[str, Any]:
    """把 HTML 转成与 PDF 索引同构的虚拟页索引，供 reader 复用。

    每页: {page, native_text, native_chars, needs_ocr: False, heading}
    """
    pages_html = split_html_pages(html)
    pages = []
    for page_number, page_html in enumerate(pages_html, start=1):
        text = html_to_markdown(page_html)
        heading = ""
        for line in text.splitlines():
            if line.strip().startswith("#"):
                heading = line.strip().lstrip("#").strip()[:60]
                break
        pages.append(
            {
                "page": page_number,
                "native_text": text,
                "native_chars": len(text),
                "image_count": 0,
                "needs_ocr": False,
                "heading": heading,
            }
        )
    return {
        "version": 1,
        "source_size": len(html),
        "source_mtime_ns": 0,
        "toc": [],
        "pages": pages,
        "us_edgar": {"accession": accession},
    }


def save_html_index(stock_code: str, html_path: Path, index: dict[str, Any]) -> Path:
    path = extraction_dir(stock_code) / f"{html_path.stem}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return path


def cache_filing_html(stock_code: str, accession: str, url: str) -> Path:
    """下载并缓存 EDGAR HTML 到 cache/{code}/us_filings/{accession}.html。"""
    target_dir = app_root() / "cache" / stock_code / "us_filings"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{accession.replace('-', '')}.html"
    if target.exists():
        return target
    html = fetch_filing_html(url)
    temporary = target.with_suffix(".html.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(target)
    return target
