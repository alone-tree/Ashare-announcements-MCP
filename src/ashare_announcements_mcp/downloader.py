"""公告 PDF 下载。"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from ashare_announcements_mcp.api import HEADERS
from ashare_announcements_mcp.cache import pdf_dir


def _art_code(url: str) -> str:
    match = re.search(r"H2_([A-Za-z0-9]+)_1\.pdf", url)
    return match.group(1) if match else str(abs(hash(url)))


def _request(url: str) -> bytes:
    headers = {**HEADERS, "Accept": "application/pdf,application/octet-stream,*/*"}
    response = requests.get(url, headers=headers, timeout=45, allow_redirects=True)
    response.raise_for_status()
    if response.content.startswith(b"%PDF-"):
        return response.content

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["download"] = "1"
    fallback_url = urlunparse(parsed._replace(query=urlencode(query)))
    response = requests.get(fallback_url, headers=headers, timeout=45, allow_redirects=True)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF-"):
        raise RuntimeError("公告链接未返回 PDF 文件")
    return response.content


def download_pdf(stock_code: str, url: str) -> tuple[Path, bool]:
    """下载并按公告代码稳定命名；返回路径及是否命中缓存。

    本地路径（未上市公司的本地申报材料等）直接返回，不发起网络请求。
    SEC EDGAR 链接（美股）下载 HTML 到 us_filings/，供虚拟页阅读。
    """
    local = Path(url)
    if local.is_file() and local.read_bytes()[:5] == b"%PDF-":
        return local, True
    if url.startswith("https://www.sec.gov/Archives/edgar/"):
        from ashare_announcements_mcp import us_edgar
        from ashare_announcements_mcp.cache import stock_cache_dir

        target_dir = stock_cache_dir(stock_code) / "us_filings"
        target_dir.mkdir(parents=True, exist_ok=True)
        # 从 URL 提取 accession + 文档名作为文件名：主文档与附件共享 accession，
        # 若只按 accession 命名，附件会命中主文档缓存（读附件返回主文档封面）。
        # 示例：edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm
        #   → accession=000162828026055726, doc=lite_ex991xq4fy26.htm
        match = re.search(r"edgar/data/\d+/(\d+)/([^/]+)$", url)
        if match:
            doc = match.group(2)
            if doc.lower().endswith((".htm", ".html")):
                doc = doc.rsplit(".", 1)[0]
            stem = f"{match.group(1)}_{doc}"
        else:
            stem = str(abs(hash(url)))
        target = target_dir / f"{stem}.html"
        if target.exists():
            return target, True
        html = us_edgar.fetch_filing_html(url)
        temporary = target.with_suffix(".html.tmp")
        temporary.write_text(html, encoding="utf-8")
        temporary.replace(target)
        return target, False
    path = pdf_dir(stock_code) / f"{_art_code(url)}.pdf"
    if path.exists() and path.read_bytes()[:5] == b"%PDF-":
        return path, True
    content = _request(url)
    temporary = path.with_suffix(".pdf.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return path, False
