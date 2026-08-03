"""A/H 公告合并查询的无网络测试。"""

from __future__ import annotations

from typing import Any

import pytest

from ashare_announcements_mcp import service


def _registry() -> dict[str, Any]:
    return {
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
    }


def _item(code: str, display_time: str, title: str = "公告") -> dict[str, Any]:
    return {
        "short_name": "中际旭创",
        "stock_code": code,
        "display_time": display_time,
        "column_name": "公司治理",
        "title": title,
        "url": f"https://pdf.dfcfw.com/pdf/H2_{code}_1.pdf",
        "code": code,
    }


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    a_items: list[dict[str, Any]],
    h_items: list[dict[str, Any]],
    h_error: str | None = None,
) -> None:
    monkeypatch.setattr(service, "load_companies", lambda: _registry())

    def fake_sync(code: str, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if code == "03308":
            if h_error:
                raise RuntimeError(h_error)
            return h_items, {"update_check_ok": True, "new_announcements": 0, "update_error": None}
        return a_items, {"update_check_ok": True, "new_announcements": 0, "update_error": None}

    monkeypatch.setattr(service, "sync_archive", fake_sync)


def test_query_merges_ah_and_adds_market_field(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(
        monkeypatch,
        a_items=[_item("A1", "2026-07-30 10:00:00")],
        h_items=[_item("H1", "2026-07-31 10:00:00")],
    )

    result = service.query_archive("300308")

    assert result["company_key"] == "300308"
    assert result["total_announcements"] == 2
    markets = {item["code"]: item["market"] for item in result["results"]}
    assert markets == {"A1": "A", "H1": "H"}
    assert result["securities"][0]["update"]["success"] is True


def test_query_accepts_hk_code_input(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(
        monkeypatch,
        a_items=[_item("A1", "2026-07-30 10:00:00")],
        h_items=[_item("H1", "2026-07-31 10:00:00")],
    )

    result = service.query_archive("03308")

    assert result["company_key"] == "300308"
    assert result["total_announcements"] == 2


def test_query_market_filter_applies_to_local_results(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(
        monkeypatch,
        a_items=[_item("A1", "2026-07-30 10:00:00")],
        h_items=[_item("H1", "2026-07-31 10:00:00")],
    )

    result = service.query_archive("300308", market="H")

    assert result["total_announcements"] == 1
    assert [item["code"] for item in result["results"]] == ["H1"]


def test_query_rejects_bad_market(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, a_items=[], h_items=[])
    with pytest.raises(ValueError, match="market 必须是"):
        service.query_archive("300308", market="X")


def test_query_not_established_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "load_companies", lambda: {"companies": {}, "aliases": {}})
    with pytest.raises(ValueError, match="未建档，请先 check → establish → query"):
        service.query_archive("000001")


def test_query_hk_failure_keeps_a_results(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(
        monkeypatch,
        a_items=[_item("A1", "2026-07-30 10:00:00")],
        h_items=[],
        h_error="东方财富请求超时",
    )

    result = service.query_archive("300308")

    assert [item["code"] for item in result["results"]] == ["A1"]
    h_status = next(s for s in result["securities"] if s["market"] == "H")
    assert h_status["update"]["success"] is False
    assert h_status["update"]["error"] == "东方财富请求超时"


def test_query_sorts_merged_by_time_desc(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(
        monkeypatch,
        a_items=[_item("A1", "2026-07-28 10:00:00")],
        h_items=[_item("H1", "2026-07-31 10:00:00")],
    )

    result = service.query_archive("300308")

    assert [item["code"] for item in result["results"]] == ["H1", "A1"]
