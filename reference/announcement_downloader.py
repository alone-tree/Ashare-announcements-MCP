"""
公告PDF下载器
负责下载和保存公司公告PDF文件
"""
import os
import re
import json
import time
import pathlib
from typing import List, Dict, Optional

import requests
from .trace_utils import trace, summarize


def _sanitize_filename(name: str, max_len: int = 120) -> str:
    """Sanitize title to a safe Windows filename (keep .pdf extension elsewhere)."""
    # Remove invalid chars \ / : * ? " < > | and control chars
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1F]", "_", name).strip()
    # Collapse spaces/underscores
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")
    # Limit length
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "announcement"


def _get_http_client():
    """
    返回一个 HTTP 客户端（优先 cloudscraper，其次 requests.Session）。
    """
    try:
        import cloudscraper  # type: ignore
        scraper = cloudscraper.create_scraper()
        return scraper
    except Exception:
        s = requests.Session()
        return s


def _build_headers(referer: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _is_pdf_bytes(content: bytes) -> bool:
    return content.startswith(b"%PDF-")


def _download_single_pdf(url: str, save_dir: str, title: str, *, referer: Optional[str] = None, session=None) -> Dict[str, str]:
    """
    子函数：下载单个PDF。
    Inputs:
      - url: 公告PDF链接
      - save_dir: 保存目录（已按公司代码划分）
      - title: 公告标题，用作文件名
    Returns: { 'url', 'path', 'status', 'error' }
    """
    os.makedirs(save_dir, exist_ok=True)

    safe_name = _sanitize_filename(title)
    file_path = os.path.join(save_dir, f"{safe_name}.pdf")

    # De-duplicate if exists
    if os.path.exists(file_path):
        base = pathlib.Path(file_path).with_suffix("")
        suffix = 1
        while True:
            candidate = f"{base} ({suffix}).pdf"
            if not os.path.exists(candidate):
                file_path = candidate
                break
            suffix += 1

    client = session or _get_http_client()
    headers = _build_headers(referer=referer or "https://data.eastmoney.com/notices/")

    try:
        # 预热：若有详情页 referer，先请求一次详情页以获取 Cookie
        if referer and referer.startswith("http"):
            try:
                client.get(referer, headers=_build_headers(), timeout=15, allow_redirects=True)
            except Exception:
                pass

        # 尝试 1：原始 URL
        r = client.get(url, headers=headers, timeout=30, allow_redirects=True)
        r.raise_for_status()
        content = r.content
        ct = r.headers.get("Content-Type", "")
        if ("pdf" not in ct.lower()) or not _is_pdf_bytes(content):
            # 尝试 2：添加 download=1
            from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
            parsed = urlparse(url)
            q = dict(parse_qsl(parsed.query, keep_blank_values=True))
            q["download"] = "1"
            new_url = urlunparse(parsed._replace(query=urlencode(q)))
            r2 = client.get(new_url, headers=headers, timeout=30, allow_redirects=True)
            r2.raise_for_status()
            content2 = r2.content
            ct2 = r2.headers.get("Content-Type", "")
            if ("pdf" not in ct2.lower()) or not _is_pdf_bytes(content2):
                # 失败：落盘 .html 以便排查
                html_path = os.path.splitext(file_path)[0] + ".html"
                try:
                    with open(html_path, "wb") as fh:
                        fh.write(content2 or content)
                except Exception:
                    pass
                return {"url": url, "path": "", "status": "fail", "error": f"非PDF响应，已保存HTML以排查: {html_path}"}
            else:
                with open(file_path, "wb") as f:
                    f.write(content2)
                return {"url": new_url, "path": file_path, "status": "ok", "error": ""}
        else:
            with open(file_path, "wb") as f:
                f.write(content)
            return {"url": url, "path": file_path, "status": "ok", "error": ""}
    except Exception as e:
        return {"url": url, "path": "", "status": "fail", "error": str(e)}


def batch_download_company_pdfs(company_code: str, announcements: List[Dict], limit: int = 5, base_dir: str = "data/processed/announcements/pdfs") -> str:
    """
    父函数：批量下载某公司最近若干条公告PDF。
    Inputs:
      - company_code: 六位股票代码，用于创建子目录
      - announcements: 公告列表（需包含至少 'title' 与 'url' 字段）
      - limit: 最多下载数量（默认 5）
    - base_dir: 根目录（默认 data/processed/announcements/pdfs）
    Returns:
      - JSON 字符串：包含每条下载结果 [{url, path, status, error}, ...]

    注意：AI 工具只应调用本函数；单个下载函数为内部使用。
    """
    # 过滤有效项
    items = [a for a in announcements if a and a.get("url") and a.get("title")]
    # 取前 limit 条
    items = items[: max(0, int(limit))]

    company_dir = os.path.join(base_dir, company_code)
    results: List[Dict[str, str]] = []

    client = _get_http_client()

    trace(f"[dl] company={company_code} 计划下载 {len(items)} 条，保存目录={company_dir}")
    for idx, a in enumerate(items, start=1):
        # 解析 art_code 以构造更真实的 Referer
        trace((f"[dl] 开始第{idx}条: title=", a.get('title', ''), 120))
        art_code = a.get("code") or a.get("art_code") or ""
        if not art_code:
            m = re.search(r"H2_([A-Za-z0-9]+)_1\\.pdf", a.get("url", ""))
            if m:
                art_code = m.group(1)
        stock_code = a.get("stock_code") or company_code
        referer = None
        if art_code and stock_code:
            referer = f"https://data.eastmoney.com/notices/detail/{stock_code}/{art_code}.html"
        # 文件名：发布时间-公告标题
        pub = (a.get("display_time") or "").strip()
        if pub:
            # 替换时间中的冒号便于Windows文件名
            pub = pub.replace(":", "-")
            title_for_file = f"{pub} - {a['title']}"
        else:
            title_for_file = a["title"]
        res = _download_single_pdf(
            url=a["url"], save_dir=company_dir, title=title_for_file, referer=referer, session=client
        )
        trace((f"[dl] 结果: status={res.get('status')} path={res.get('path','')} err=", res.get('error',''), 120))
        results.append(res)
        # 轻微间隔，避免触发限流
        time.sleep(1)

    out = json.dumps({
        "company_code": company_code,
        "count": len(results),
        "results": results,
        "save_dir": company_dir,
    }, ensure_ascii=False)
    ok = sum(1 for r in results if r.get('status') == 'ok')
    fail = len(results) - ok
    trace(f"[dl] 完成: 成功{ok} 失败{fail} -> {company_dir}")
    return out


# --- OpenAI 工具描述，仅暴露父函数 ---
BATCH_DOWNLOAD_PDFS_TOOL = {
    "type": "function",
    "function": {
        "name": "batch_download_company_pdfs",
    "description": "批量下载某公司最近若干条公告PDF，保存到 data/processed/announcements/pdfs/{company_code}/ 下。仅在 announcements 列表中每项包含 title 与 url 时可用。",
        "parameters": {
            "type": "object",
            "properties": {
                "company_code": {"type": "string", "description": "六位股票代码，如 '688388'"},
                "announcements": {
                    "type": "array",
                    "description": "公告列表（建议按时间倒序），每项需包含 title、url、display_time 字段（display_time为发布时间，格式如'2025-09-09 20:15:15'）。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "display_time": {"type": "string", "description": "发布时间，格式如'2025-09-09 20:15:15'"},
                        },
                        "required": ["title", "url", "display_time"],
                    },
                },
                "limit": {"type": "integer", "description": "最多下载数量，默认5"},
                "base_dir": {"type": "string", "description": "保存根目录，默认 'data/processed/announcements/pdfs'"},
            },
            "required": ["company_code", "announcements"],
        },
    },
}
