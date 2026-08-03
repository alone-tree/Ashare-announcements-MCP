"""公司证券查询的无网络测试。"""

from __future__ import annotations

from typing import Any

import pytest

from ashare_announcements_mcp import company


def _security(code: str, name: str, classify: str, inner_code: str) -> dict[str, str]:
    return {
        "Code": code,
        "Name": name,
        "PinYin": "ZJXC",
        "ID": f"{code}2",
        "JYS": "80",
        "Classify": classify,
        "MarketType": "2",
        "SecurityTypeName": "深A" if classify == "AStock" else "港股",
        "SecurityType": "2",
        "MktNum": "0" if classify == "AStock" else "116",
        "TypeUS": "80" if classify == "AStock" else "3",
        "QuoteID": f"{'0' if classify == 'AStock' else '116'}.{code}",
        "UnifiedCode": code,
        "InnerCode": inner_code,
    }


def test_check_code_follows_returned_name_for_ah_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_search(keyword: str) -> tuple[list[dict[str, Any]], int]:
        calls.append(keyword)
        if keyword == "300308":
            return [_security("300308", "中际旭创", "AStock", "A-INNER")], 1
        return [
            _security("300308", "中际旭创", "AStock", "A-INNER"),
            _security("03308", "中际旭创", "HK", "H-INNER"),
        ], 2

    monkeypatch.setattr(company, "_search", fake_search)
    result = company.check_company("300308")

    assert calls == ["300308", "中际旭创"]
    assert [(item["classify"], item["code"]) for item in result["candidates"]] == [
        ("AStock", "300308"),
        ("HK", "03308"),
    ]


def test_check_excludes_non_company_securities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        company,
        "_search",
        lambda _keyword: (
            [
                _security("00700", "腾讯控股", "HK", "H-INNER"),
                _security("123456", "腾讯债券", "Bond", "B-INNER"),
            ],
            2,
        ),
    )

    result = company.check_company("腾讯")
    assert [item["code"] for item in result["candidates"]] == ["00700"]


def test_check_exact_numeric_code_excludes_fuzzy_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(keyword: str) -> tuple[list[dict[str, Any]], int]:
        if keyword == "03308":
            return [
                _security("03308", "中际旭创", "HK", "H-INNER"),
                _security("603308", "应流股份", "AStock", "OTHER-INNER"),
            ], 2
        return [_security("03308", "中际旭创", "HK", "H-INNER")], 1

    monkeypatch.setattr(company, "_search", fake_search)
    result = company.check_company("03308")
    assert [item["code"] for item in result["candidates"]] == ["03308"]


def test_check_excludes_hk_derivatives(monkeypatch: pytest.MonkeyPatch) -> None:
    stock = _security("00700", "腾讯控股", "HK", "H-INNER")
    derivative = _security("13160", "腾讯中银六乙购B", "HK", "D-INNER")
    derivative["TypeUS"] = "6"
    monkeypatch.setattr(company, "_search", lambda _keyword: ([stock, derivative], 2))

    result = company.check_company("腾讯")
    assert [item["code"] for item in result["candidates"]] == ["00700"]


def test_check_rejects_empty_keyword() -> None:
    with pytest.raises(ValueError, match="keyword 不能为空"):
        company.check_company("  ")
