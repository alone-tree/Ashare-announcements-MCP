"""公司证券查询的无网络测试。"""

from __future__ import annotations

from typing import Any

import pytest

from ashare_announcements_mcp import company


def _security(code: str, name: str, classify: str, inner_code: str, **overrides: Any) -> dict[str, str]:
    item: dict[str, str] = {
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
    item.update(overrides)
    return item


def test_check_returns_all_candidates_without_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    """衍生品、债券等非普通公司证券也原样返回，不做过滤。"""
    monkeypatch.setattr(
        company,
        "_search",
        lambda _keyword: (
            [
                _security("00700", "腾讯控股", "HK", "H-INNER"),
                _security("13160", "腾讯中银六乙购B", "HK", "D-INNER", TypeUS="6"),
                _security("123456", "腾讯债券", "Bond", "B-INNER"),
            ],
            3,
        ),
    )

    result = company.check_company("腾讯")

    assert [item["code"] for item in result["candidates"]] == ["00700", "13160", "123456"]
    assert result["source_total_count"] == 3
    assert result["returned_count"] == 3
    assert "hint" not in result


def test_check_numeric_code_keeps_fuzzy_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """数字代码也不精确过滤，模糊命中原样返回。"""
    monkeypatch.setattr(
        company,
        "_search",
        lambda _keyword: (
            [
                _security("03308", "中际旭创", "HK", "H-INNER"),
                _security("603308", "应流股份", "AStock", "OTHER-INNER"),
            ],
            2,
        ),
    )

    result = company.check_company("03308")

    assert [item["code"] for item in result["candidates"]] == ["03308", "603308"]


def test_check_does_not_follow_up_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """只调用一次搜索接口，不做同名补查。"""
    calls: list[str] = []

    def fake_search(keyword: str) -> tuple[list[dict[str, Any]], int]:
        calls.append(keyword)
        return [_security("300308", "中际旭创", "AStock", "A-INNER")], 1

    monkeypatch.setattr(company, "_search", fake_search)
    result = company.check_company("300308")

    assert calls == ["300308"]
    assert result["returned_count"] == 1


def test_check_hint_when_source_total_exceeds_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """接口命中数超过返回上限时给出提示。"""
    monkeypatch.setattr(
        company,
        "_search",
        lambda _keyword: (
            [
                _security("00700", "腾讯控股", "HK", "H-INNER"),
                _security("80700", "腾讯控股-R", "HK", "R-INNER"),
            ],
            724,
        ),
    )

    result = company.check_company("腾讯")

    assert result["source_total_count"] == 724
    assert result["returned_count"] == 2
    assert "hint" in result


def test_check_fields_are_snake_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """返回字段使用项目统一 snake_case，不丢失上游字段。"""
    monkeypatch.setattr(
        company,
        "_search",
        lambda _keyword: ([_security("300308", "中际旭创", "AStock", "A-INNER")], 1),
    )

    result = company.check_company("中际")
    candidate = result["candidates"][0]

    assert candidate == {
        "code": "300308",
        "name": "中际旭创",
        "pinyin": "ZJXC",
        "id": "3003082",
        "jys": "80",
        "classify": "AStock",
        "market_type": "2",
        "security_type_name": "深A",
        "security_type": "2",
        "mkt_num": "0",
        "type_us": "80",
        "quote_id": "0.300308",
        "unified_code": "300308",
        "inner_code": "A-INNER",
    }


def test_check_rejects_empty_keyword() -> None:
    with pytest.raises(ValueError, match="keyword 不能为空"):
        company.check_company("  ")
