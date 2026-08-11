"""互动问答同步与查询的无网络测试。"""

from __future__ import annotations

from typing import Any

import pytest

from ashare_announcements_mcp import api, service


def _qa(post_id: str, question: str = "问题", answer: str = "回答") -> dict[str, Any]:
    return {
        "post_id": post_id,
        "stockbar_code": "300308",
        "stockbar_name": "中际旭创",
        "post_publish_time": "2026-06-01 10:00:00",
        "post_display_time": "2026-07-01 10:00:00",
        "ask_question": question,
        "ask_answer": answer,
    }


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def test_fetch_qa_page_formats_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, data: dict[str, Any], **kwargs: Any) -> _FakeResponse:
        captured["data"] = data
        payload = {
            "count": 30,
            "TotalPage": 2,
            "PageIndex": 1,
            "rc": 1,
            "re": [
                {
                    "post_id": 123,
                    "stockbar_code": "300308",
                    "stockbar_name": "中际旭创",
                    "post_publish_time": "2026-06-01 10:00:00",
                    "post_display_time": "2026-07-01 10:00:00",
                    "ask_question": "公司三季度业绩如何？",
                    "ask_answer": "感谢关注。",
                }
            ],
        }
        return _FakeResponse(payload)

    monkeypatch.setattr(api.requests, "post", fake_post)

    items, meta = api.fetch_qa_page("300308", 1)

    assert captured["data"]["path"] == "question/api/Info/Search"
    assert "code=300308" in captured["data"]["param"]
    assert meta["total"] == 30
    assert meta["total_pages"] == 2
    assert items[0]["post_id"] == "123"
    assert items[0]["ask_question"] == "公司三季度业绩如何？"


def test_fetch_all_interactions_stops_at_total_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages: dict[int, list[dict[str, Any]]] = {
        1: [_qa("1"), _qa("2")],
        2: [_qa("3")],
    }

    def fake_post(url: str, data: dict[str, Any], **kwargs: Any) -> _FakeResponse:
        page = int(dict(pair.split("=") for pair in data["param"].split("&"))["p"])
        return _FakeResponse(
            {
                "count": 3,
                "TotalPage": 2,
                "PageIndex": page,
                "rc": 1,
                "re": pages.get(page, []),
            }
        )

    monkeypatch.setattr(api.requests, "post", fake_post)

    items, meta = api.fetch_all_interactions("300308")

    assert [item["post_id"] for item in items] == ["1", "2", "3"]
    assert meta["cache_complete"] is True


def test_fetch_interaction_updates_stops_at_known_id(monkeypatch: pytest.MonkeyPatch) -> None:
    pages: dict[int, list[dict[str, Any]]] = {
        1: [_qa("NEW"), _qa("OLD")],
        2: [_qa("OLD2")],
    }

    def fake_post(url: str, data: dict[str, Any], **kwargs: Any) -> _FakeResponse:
        page = int(dict(pair.split("=") for pair in data["param"].split("&"))["p"])
        return _FakeResponse(
            {
                "count": 3,
                "TotalPage": 2,
                "PageIndex": page,
                "rc": 1,
                "re": pages.get(page, []),
            }
        )

    monkeypatch.setattr(api.requests, "post", fake_post)

    items, meta = api.fetch_interaction_updates("300308", {"OLD", "OLD2"})

    assert [item["post_id"] for item in items] == ["NEW"]
    assert meta["cache_complete"] is True


def test_query_a_share_interactions_filters_and_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        _qa("1", question="回购进展如何", answer="正在推进", ),
        _qa("2", question="分红计划", answer="暂无计划"),
        _qa("3", question="订单情况", answer="产能利用率高"),
    ]
    monkeypatch.setattr(
        service,
        "load_companies",
        lambda: {
            "companies": {
                "300308": {
                    "securities": [
                        {
                            "code": "300308",
                            "market": "A",
                            "name": "中际旭创",
                            "classify": "AStock",
                            "inner_code": "A-INNER",
                        }
                    ]
                }
            },
            "aliases": {"300308": "300308"},
        },
    )
    monkeypatch.setattr(
        service,
        "sync_interactions",
        lambda _code: (
            items,
            {"update_check_ok": True, "new_interactions": 0, "update_error": None},
        ),
    )

    result = service.query_a_share_interactions("300308", keyword="回购", end_date="2026-07-02")

    assert result["total_interactions"] == 3
    assert result["matched"] == 1
    assert result["results"][0]["post_id"] == "1"


def test_query_a_share_interactions_accepts_hk_code_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """输入关联 H 股代码也能定位 A 股互动问答。"""
    monkeypatch.setattr(
        service,
        "load_companies",
        lambda: {
            "companies": {
                "300308": {
                    "securities": [
                        {
                            "code": "300308",
                            "market": "A",
                            "name": "中际旭创",
                            "classify": "AStock",
                            "inner_code": "A-INNER",
                        },
                        {
                            "code": "03308",
                            "market": "H",
                            "name": "中际旭创",
                            "classify": "HK",
                            "inner_code": "H-INNER",
                        },
                    ]
                }
            },
            "aliases": {"300308": "300308", "03308": "300308"},
        },
    )
    monkeypatch.setattr(
        service,
        "sync_interactions",
        lambda _code: (
            [_qa("1")],
            {"update_check_ok": True, "new_interactions": 0, "update_error": None},
        ),
    )

    result = service.query_a_share_interactions("03308")

    assert result["stock_code"] == "300308"
    assert result["total_interactions"] == 1


def test_query_a_share_interactions_pure_hk_returns_not_applicable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service,
        "load_companies",
        lambda: {
            "companies": {
                "00700": {
                    "securities": [
                        {
                            "code": "00700",
                            "market": "H",
                            "name": "腾讯控股",
                            "classify": "HK",
                            "inner_code": "T-INNER",
                        }
                    ]
                }
            },
            "aliases": {"00700": "00700"},
        },
    )

    result = service.query_a_share_interactions("00700")

    assert result["stock_code"] == "00700"
    assert result["company_key"] == "00700"
    assert result["stock_name"] == "腾讯控股"
    assert result["applicable"] is False
    assert result["reason"] == "该公司无互动问答（纯港股/B 股/本地公司），不适用"
    assert result["matched"] == 0
    assert result["results"] == []


def test_sync_interactions_incremental_prepends_new(monkeypatch: pytest.MonkeyPatch) -> None:
    cached = {
        "items": [_qa("OLD")],
        "meta": {"cache_complete": True, "total": 1},
    }
    monkeypatch.setattr(service, "load_interactions", lambda _code: cached)
    saved: dict[str, Any] = {}
    monkeypatch.setattr(
        service, "save_interactions", lambda _code, items, meta: saved.update(items=items, meta=meta)
    )
    monkeypatch.setattr(
        service,
        "fetch_interaction_updates",
        lambda _code, _known: (
            [_qa("NEW")],
            {"total": 2, "total_pages": 1, "cache_complete": True},
        ),
    )

    items, status = service.sync_interactions("300308")

    assert [item["post_id"] for item in items] == ["NEW", "OLD"]
    assert status["new_interactions"] == 1
