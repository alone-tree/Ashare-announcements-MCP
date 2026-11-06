"""市场MCP独立证券搜索；行为见docs/market-data架构设计.md的证券搜索章节。"""

import requests

from market_data_mcp.routing import parse_code


_SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
_SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
_FIELDS = {
    "code": "Code", "name": "Name", "pinyin": "PinYin", "id": "ID", "jys": "JYS",
    "classify": "Classify", "market_type": "MarketType", "security_type_name": "SecurityTypeName",
    "security_type": "SecurityType", "mkt_num": "MktNum", "type_us": "TypeUS",
    "quote_id": "QuoteID", "unified_code": "UnifiedCode", "inner_code": "InnerCode",
}
_STOCK_SUFFIXES = {
    "沪A": "SH", "沪B": "SH", "科创板": "SH", "深A": "SZ", "深B": "SZ", "京A": "BJ",
}


def _standard_code(candidate: dict) -> str | None:
    kind = candidate["security_type_name"]
    suffix = _STOCK_SUFFIXES.get(kind)
    if kind == "港股" and candidate["type_us"] not in ("1", "6"):
        suffix = "HK"
    elif kind == "美股" and candidate["type_us"] not in ("5", "6"):
        suffix = "US"
    if not suffix:
        return None
    code = candidate["code"]
    if suffix == "HK":
        code = code.zfill(5)
    try:
        parsed = parse_code(f"{code}.{suffix}")
    except ValueError:
        return None
    return f"{parsed.code}.{parsed.suffix}"


def search_securities(keyword: str) -> dict:
    """仅搜索本次关键词，保留原始候选；不建档、不补查、不读取业务缓存。"""
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("keyword必须为非空字符串")
    text = keyword.strip()
    # 国内公开源直连；仅关闭本次会话的环境代理，不改动进程代理或付费账号配置。
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(
            _SEARCH_URL,
            params={"input": text, "type": "14", "count": "20", "token": _SEARCH_TOKEN},
            timeout=20,
        )
        response.raise_for_status()
        table = response.json()["QuotationCodeTable"]
    if int(table["Status"]) != 0:
        raise RuntimeError(f"东方财富证券搜索失败：{table.get('Message') or '未知错误'}")
    candidates = []
    for item in table["Data"] or []:
        candidate = {key: str(item.get(field) or "") for key, field in _FIELDS.items()}
        candidate["standard_code"] = _standard_code(candidate)
        candidates.append(candidate)
    total = int(table["TotalCount"])
    result = {"ok": True, "keyword": text, "source_total_count": total,
              "returned_count": len(candidates), "candidates": candidates}
    if total > len(candidates):
        result["hint"] = "命中数超过返回上限，请使用更精确的关键词重新查询"
    return result
