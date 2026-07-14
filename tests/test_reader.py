"""公告阅读核心逻辑的无网络测试。"""

from ashare_announcements_mcp.reader import _page_ranges, _query_terms


def test_page_ranges() -> None:
    assert _page_ranges([]) == ""
    assert _page_ranges([1, 2, 4, 6, 7]) == "1-2, 4, 6-7"


def test_query_terms() -> None:
    assert _query_terms("收入 利润") == (["收入", "利润"], False)
    assert _query_terms("收入 AND 利润") == (["收入", "利润"], True)
