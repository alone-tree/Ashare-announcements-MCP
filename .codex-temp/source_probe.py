from __future__ import annotations

import json
import re
import sys
import time
from html import unescape
from urllib.parse import urlencode
from urllib.request import Request, urlopen


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def get(url: str) -> tuple[int, bytes, str]:
    request = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    started = time.perf_counter()
    with urlopen(request, timeout=30) as response:
        body = response.read()
        return response.status, body, f"{time.perf_counter() - started:.2f}s"


def decode(body: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            pass
    return body.decode("utf-8", errors="replace")


def qa(code: str, page: int, page_parameter: str = "page") -> dict:
    query = urlencode(
        {
            "company": code,
            "keyword": "",
            "questioner": "",
            "qatype": 1,
            page_parameter: page,
        }
    )
    url = f"https://guba.eastmoney.com/qa/qa_search.aspx?{query}"
    status, body, elapsed = get(url)
    text = decode(body)
    match = re.search(r"var\s+qa_list\s*=\s*(\{[\s\S]*?\});", text)
    if not match:
        return {"url": url, "http": status, "bytes": len(body), "elapsed": elapsed, "parsed": False}
    payload = json.loads(match.group(1))
    rows = payload.get("re") or []
    return {
        "url": url,
        "http": status,
        "bytes": len(body),
        "elapsed": elapsed,
        "parsed": True,
        "requested_page": page,
        "page_parameter": page_parameter,
        "returned_page": payload.get("PageIndex"),
        "page_size": payload.get("PageSize"),
        "total_pages": payload.get("TotalPage"),
        "count": payload.get("count"),
        "items": len(rows),
        "answered": sum(bool(row.get("ask_answer")) for row in rows),
        "first_time": rows[0].get("post_display_time") if rows else None,
        "last_time": rows[-1].get("post_display_time") if rows else None,
        "first_question": unescape(str(rows[0].get("ask_question") or ""))[:80] if rows else None,
    }


def eastmoney_notice(
    stock_code: str, page: int, market: str | None = None, ann_type: str = "A"
) -> dict:
    params = {
        "sr": -1,
        "page_size": 50,
        "page_index": page,
        "ann_type": ann_type,
        "client_source": "web",
        "f_node": 0,
        "s_node": 0,
        "stock_list": stock_code,
    }
    if market:
        params["market"] = market
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann?" + urlencode(params)
    status, body, elapsed = get(url)
    payload = json.loads(decode(body))
    data = payload.get("data") or {}
    rows = data.get("list") or []
    return {
        "url": url,
        "http": status,
        "bytes": len(body),
        "elapsed": elapsed,
        "total_hits": data.get("total_hits"),
        "items": len(rows),
        "first": {
            "title": (rows[0].get("title") or rows[0].get("title_ch")) if rows else None,
            "time": (rows[0].get("display_time") or rows[0].get("notice_date")) if rows else None,
            "code": rows[0].get("art_code") if rows else None,
            "columns": sorted(rows[0].keys()) if rows else [],
        },
    }


def page_contracts() -> dict:
    _, qa_body, _ = get(
        "https://guba.eastmoney.com/qa/qa_search.aspx?company=300308&keyword=&questioner=&qatype=1&page=1"
    )
    qa_text = decode(qa_body)
    qa_links = sorted(
        set(re.findall(r'href=["\']([^"\']*(?:page|Page|qatype)[^"\']*)["\']', qa_text))
    )
    _, js_body, _ = get("https://data.eastmoney.com/newstatic/js/notices/index.js")
    js_text = decode(js_body)
    contexts = []
    for marker in ("ann_type", "HK", "market", "api/security/ann"):
        for match in list(re.finditer(re.escape(marker), js_text, re.I))[:8]:
            contexts.append(js_text[max(0, match.start() - 180) : match.end() + 240])
    return {
        "probe": "page_contracts",
        "qa_links": qa_links[:30],
        "notice_js_bytes": len(js_body),
        "notice_contexts": contexts,
    }
def main() -> None:
    outputs = []
    for code in ("603083", "300308"):
        first = qa(code, 1)
        outputs.append({"probe": "eastmoney_qa", "code": code, **first})
        total_pages = int(first.get("total_pages") or 1)
        if total_pages > 1:
            for parameter in ("page", "p", "pageIndex", "PageIndex"):
                outputs.append(
                    {"probe": "eastmoney_qa", "code": code, **qa(code, total_pages, parameter)}
                )
    outputs.append({"probe": "eastmoney_notice", "code": "300308", **eastmoney_notice("300308", 1)})
    for code in ("09988", "9988"):
        for market in (None, "HK", "hk", "116"):
            result = eastmoney_notice(code, 1, market, "H")
            result["requested_market"] = market
            outputs.append({"probe": "eastmoney_notice", "code": code, **result})
    outputs.append(page_contracts())
    json.dump(outputs, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
