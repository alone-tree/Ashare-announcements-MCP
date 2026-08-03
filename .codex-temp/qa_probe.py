"""互动问答接口真实探针：确认 GetData.aspx 响应结构与字段。"""

from __future__ import annotations

import json
import sys
from urllib.parse import urlencode

import requests

sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://guba.eastmoney.com/qa/qa_search.aspx?company=300308&qatype=1",
}

URL = "https://guba.eastmoney.com/interface/GetData.aspx"


def fetch_page(code: str, page: int) -> dict:
    param = urlencode({"code": code, "ps": 15, "p": page, "qatype": 1})
    response = requests.post(
        URL,
        data={"path": "question/api/Info/Search", "param": param, "env": "2"},
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    page1 = fetch_page("300308", 1)
    print("=== page 1 top-level keys ===")
    print(json.dumps({k: v for k, v in page1.items() if k != "re"}, ensure_ascii=False, indent=2))
    rows = page1.get("re") or []
    print(f"=== re count: {len(rows)} ===")
    if rows:
        print("=== first row full ===")
        print(json.dumps(rows[0], ensure_ascii=False, indent=2))
        print("=== last row keys ===")
        print(sorted(rows[-1].keys()))
