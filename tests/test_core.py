"""不访问网络的最小核心测试。"""

from ashare_announcements_mcp.cache import merge_items
from ashare_announcements_mcp.server import _keyword_matches, _stock_code


def test_keyword_or_and() -> None:
    item = {"title": "关于回购股份进展的公告", "column_name": "公司治理"}
    assert _keyword_matches(item, "回购 进展")
    assert _keyword_matches(item, "分红 回购")
    assert _keyword_matches(item, "回购 AND 进展")
    assert not _keyword_matches(item, "回购 AND 完成")


def test_merge_prefers_new_item() -> None:
    old = [{"code": "A", "title": "旧", "display_time": "2026-01-01"}]
    new = [{"code": "A", "title": "新", "display_time": "2026-01-02"}]
    assert merge_items(old, new)[0]["title"] == "新"


def test_stock_code_validation() -> None:
    assert _stock_code("002271") == "002271"
    assert _stock_code("SZ002271") == "002271"
    assert _stock_code("002271.SZ") == "002271"
