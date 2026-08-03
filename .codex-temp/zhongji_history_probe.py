from __future__ import annotations

import json
import re
import time
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def request(url: str, referer: str | None = None) -> tuple[int, bytes, dict[str, str]]:
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        return response.status, response.read(), dict(response.headers.items())


def qa_page(page: int) -> dict:
    inner = urlencode({"code": "300308", "ps": 15, "p": page, "qatype": 1})
    form = urlencode({"param": inner, "path": "question/api/Info/Search", "env": 2}).encode()
    url = "https://guba.eastmoney.com/interface/GetData.aspx"
    headers = {
        "User-Agent": UA,
        "Referer": "https://guba.eastmoney.com/qa/qa_search.aspx?company=300308&qatype=1",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
    }
    last_error = None
    for attempt in range(3):
        try:
            with urlopen(Request(url, data=form, headers=headers), timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"QA page {page} failed: {last_error}")


def all_qa() -> dict:
    started = time.perf_counter()
    first = qa_page(1)
    pages = int(first["TotalPage"])
    batches = {1: first}
    errors = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(qa_page, page): page for page in range(2, pages + 1)}
        for future in as_completed(futures):
            page = futures[future]
            try:
                batches[page] = future.result()
            except Exception as exc:
                errors.append({"page": page, "error": str(exc)})
    rows = [row for page in sorted(batches) for row in (batches[page].get("re") or [])]
    unique = {row.get("post_id"): row for row in rows if row.get("post_id") is not None}
    ordered = sorted(unique.values(), key=lambda x: x.get("post_publish_time") or "", reverse=True)
    cutoff = "2021-08-03"
    recent = [row for row in ordered if (row.get("post_publish_time") or "")[:10] >= cutoff]
    def compact(row: dict) -> dict:
        return {
            "post_id": row.get("post_id"),
            "question_time": row.get("post_publish_time") or row.get("post_display_time"),
            "answer_time": row.get("answer_publish_time") or row.get("answer_display_time"),
            "question": row.get("post_title") or row.get("ask_question"),
        }
    return {
        "api_count": first.get("count"),
        "pages": pages,
        "page_size": first.get("PageSize"),
        "successful_pages": len(batches),
        "errors": errors,
        "received": len(rows),
        "unique_post_ids": len(unique),
        "recent_5y_since_2021_08_03": len(recent),
        "newest": compact(ordered[0]) if ordered else None,
        "oldest": compact(ordered[-1]) if ordered else None,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def notice_page(code: str, ann_type: str, page: int) -> tuple[int, list[dict]]:
    params = {
        "sr": -1,
        "page_size": 50,
        "page_index": page,
        "ann_type": ann_type,
        "client_source": "web",
        "f_node": 0,
        "s_node": 0,
        "stock_list": code,
    }
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann?" + urlencode(params)
    _, body, _ = request(url, "https://data.eastmoney.com/notices/")
    data = json.loads(body.decode("utf-8"))["data"]
    return int(data["total_hits"]), data.get("list") or []


def all_notices(code: str, ann_type: str) -> dict:
    started = time.perf_counter()
    total, first = notice_page(code, ann_type, 1)
    rows = list(first)
    pages = (total + 49) // 50
    for page in range(2, pages + 1):
        _, batch = notice_page(code, ann_type, page)
        rows.extend(batch)
        time.sleep(0.08)
    unique = {row.get("art_code"): row for row in rows if row.get("art_code")}
    ordered = sorted(
        unique.values(), key=lambda x: x.get("display_time") or x.get("notice_date") or "", reverse=True
    )
    cutoff = "2021-08-03"
    recent = [r for r in ordered if (r.get("display_time") or r.get("notice_date") or "")[:10] >= cutoff]
    first_row = ordered[0] if ordered else {}
    pdf_url = f"https://pdf.dfcfw.com/pdf/H2_{first_row.get('art_code')}_1.pdf" if first_row else None
    pdf = None
    if pdf_url:
        status, body, headers = request(pdf_url, "https://data.eastmoney.com/notices/")
        pdf = {
            "url": pdf_url,
            "http": status,
            "content_type": headers.get("Content-Type"),
            "bytes": len(body),
            "magic": body[:5].decode("ascii", errors="replace"),
        }
    return {
        "code": code,
        "ann_type": ann_type,
        "api_total_hits": total,
        "pages": pages,
        "received": len(rows),
        "unique_art_codes": len(unique),
        "recent_5y_since_2021_08_03": len(recent),
        "newest": {
            "time": (first_row.get("display_time") or first_row.get("notice_date") or "")[:19],
            "title": first_row.get("title") or first_row.get("title_ch"),
            "art_code": first_row.get("art_code"),
        } if first_row else None,
        "oldest": {
            "time": (ordered[-1].get("display_time") or ordered[-1].get("notice_date") or "")[:19],
            "title": ordered[-1].get("title") or ordered[-1].get("title_ch"),
            "art_code": ordered[-1].get("art_code"),
        } if ordered else None,
        "pdf": pdf,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def js_contract() -> dict:
    js_url = "https://gbfek.dfcfw.com/deploy/guba_web_qa/work/qa_search.js?r=262"
    _, body, _ = request(js_url, "https://guba.eastmoney.com/qa/qa_search.aspx?company=300308&qatype=1")
    text = body.decode("utf-8", errors="replace")
    markers = {}
    for needle in ("question/api/Info/Search", "sendGubawebapi", "sendNewGubaapi", "send:function"):
        pos = text.find(needle)
        markers[needle] = text[max(0, pos - 500):pos + 1000] if pos >= 0 else None
    # Capture the compact module exporting network methods, if identifiable.
    module = re.search(r"7:function\(t,e,n\)\{([\s\S]*?)\},8:function\(t,e,n\)\{", text)
    return {"js_url": js_url, "bytes": len(body), "markers": markers, "module7": module.group(1) if module else None}


def main() -> None:
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "qa": all_qa(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
