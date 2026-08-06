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
    """
    local = Path(url)
    if local.is_file() and local.read_bytes()[:5] == b"%PDF-":
        return local, True
    path = pdf_dir(stock_code) / f"{_art_code(url)}.pdf"
    if path.exists() and path.read_bytes()[:5] == b"%PDF-":
        return path, True
    content = _request(url)
    temporary = path.with_suffix(".pdf.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return path, False
