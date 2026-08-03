"""东方财富接口解析与过滤的无网络测试。"""

from __future__ import annotations

from typing import Any

import pytest

from ashare_announcements_mcp import api


def _ann(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "art_code": "AN1",
        "display_time": "2026-07-30 10:00:00",
        "title": "公告标题",
        "columns": [],
        **item,
    }


def _wrap_jsonp(callback: str, payload: dict[str, Any]) -> str:
    import json

    return f"{callback}({json.dumps(payload)})"


def test_fetch_page_filters_by_inner_code(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: str, params: dict[str, Any], **kwargs: Any) -> Any:
        captured["params"] = params
        assert params["ann_type"] == "H"
        callback = params["cb"]
        items = [
            _ann(
                {
                    "art_code": "H1",
                    "codes": [{"inner_code": "H-INNER", "short_name": "中际旭创"}],
                }
            ),
            _ann(
                {
                    "art_code": "H2",
                    "codes": [{"inner_code": "OLD-INNER", "short_name": "金鹰商贸集团"}],
                }
            ),
        ]
        return _FakeResponse(_wrap_jsonp(callback, {"success": True, "data": {"total_hits": 2, "list": items}}))

    monkeypatch.setattr(api.requests, "get", fake_get)

    items, total = api.fetch_page("03308", page=1, ann_type="H", expected_inner_code="H-INNER")

    assert total == 2
    assert [item["code"] for item in items] == ["H1"]
    assert items[0]["short_name"] == "中际旭创"
    assert items[0]["stock_code"] == "03308"


def test_fetch_page_without_inner_code_keeps_all(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, params: dict[str, Any], **kwargs: Any) -> Any:
        callback = params["cb"]
        items = [
            _ann({"art_code": "A1", "codes": [{"inner_code": "X", "short_name": "甲"}]}),
            _ann({"art_code": "A2", "codes": [{"inner_code": "Y", "short_name": "乙"}]}),
        ]
        return _FakeResponse(_wrap_jsonp(callback, {"success": True, "data": {"total_hits": 2, "list": items}}))

    monkeypatch.setattr(api.requests, "get", fake_get)

    items, total = api.fetch_page("300308", page=1)

    assert total == 2
    assert len(items) == 2


def test_fetch_all_with_inner_code_stops_after_empty_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """港股过滤后 total_hits 含旧公司记录，完成判断依赖连续空页。"""
    pages: dict[int, list[dict[str, Any]]] = {
        1: [
            _ann(
                {
                    "art_code": f"H{i}",
                    "codes": [{"inner_code": "H-INNER", "short_name": "中际旭创"}],
                }
            )
            for i in range(1, 4)
        ],
        2: [
            _ann(
                {
                    "art_code": f"O{i}",
                    "codes": [{"inner_code": "OLD-INNER", "short_name": "金鹰商贸集团"}],
                }
            )
            for i in range(1, 3)
        ],
        3: [],
        4: [],
    }

    def fake_get(url: str, params: dict[str, Any], **kwargs: Any) -> Any:
        callback = params["cb"]
        page = int(params["page_index"])
        items = pages.get(page, [])
        return _FakeResponse(
            _wrap_jsonp(callback, {"success": True, "data": {"total_hits": 919, "list": items}})
        )

    monkeypatch.setattr(api.requests, "get", fake_get)

    items, meta = api.fetch_all_announcements("03308", ann_type="H", expected_inner_code="H-INNER")

    assert [item["code"] for item in items] == ["H1", "H2", "H3"]
    assert meta["cache_complete"] is True
    assert meta["source_total"] == 919


def test_fetch_all_without_inner_code_uses_source_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, params: dict[str, Any], **kwargs: Any) -> Any:
        callback = params["cb"]
        page = int(params["page_index"])
        if page == 1:
            items = [
                _ann({"art_code": f"A{i}", "codes": [{"inner_code": "X", "short_name": "甲"}]})
                for i in range(1, 3)
            ]
        else:
            items = []
        return _FakeResponse(
            _wrap_jsonp(callback, {"success": True, "data": {"total_hits": 2, "list": items}})
        )

    monkeypatch.setattr(api.requests, "get", fake_get)

    items, meta = api.fetch_all_announcements("300308")

    assert len(items) == 2
    assert meta["cache_complete"] is True


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


if __name__ == "__main__":
    pytest.main([__file__])
