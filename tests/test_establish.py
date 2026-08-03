"""建档 establish_company 的无网络测试。"""

from __future__ import annotations

from typing import Any

import pytest

from ashare_announcements_mcp import company


def _security(
    code: str,
    name: str,
    classify: str,
    inner_code: str,
    type_us: str = "3",
) -> dict[str, str]:
    return {
        "Code": code,
        "Name": name,
        "PinYin": "TEST",
        "ID": f"{code}2",
        "JYS": "80" if classify == "AStock" else "116",
        "Classify": classify,
        "MarketType": "2",
        "SecurityTypeName": "深A" if classify == "AStock" else "港股",
        "SecurityType": "2",
        "MktNum": "0" if classify == "AStock" else "116",
        "TypeUS": "80" if classify == "AStock" else type_us,
        "QuoteID": f"{code}",
        "UnifiedCode": code,
        "InnerCode": inner_code,
    }


def _empty_registry() -> dict[str, Any]:
    return {"companies": {}, "aliases": {}}


def _ok_sync(_code: str, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return (
        [{"code": "AN1", "title": "公告", "display_time": "2026-07-30"}],
        {"update_check_ok": True, "new_announcements": 1, "update_error": None},
    )


def _ok_qa(_code: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return (
        [{"post_id": "Q1", "ask_question": "问题", "ask_answer": "回答"}],
        {"update_check_ok": True, "new_interactions": 1, "update_error": None},
    )


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    securities: list[dict[str, str]],
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """mock 搜索、公司注册表和公告同步，返回捕获的保存结果。"""
    monkeypatch.setattr(company, "_search", lambda _keyword: (securities, len(securities)))
    monkeypatch.setattr(company, "load_companies", lambda: registry if registry is not None else _empty_registry())
    saved: dict[str, Any] = {}

    def fake_save(data: dict[str, Any]) -> Any:
        saved["data"] = data
        return None

    monkeypatch.setattr(company, "save_companies", fake_save)
    monkeypatch.setattr(company, "sync_archive", _ok_sync)
    monkeypatch.setattr(company, "sync_interactions", _ok_qa)
    return saved


def test_establish_single_a_stock(monkeypatch: pytest.MonkeyPatch) -> None:
    saved = _setup(
        monkeypatch,
        securities=[_security("300308", "中际旭创", "AStock", "A-INNER")],
    )
    result = company.establish_company(["300308"])

    assert result["company_key"] == "300308"
    assert result["securities"] == [
        {
            "code": "300308",
            "market": "A",
            "name": "中际旭创",
            "success": True,
            "total": 1,
            "new": 1,
            "error": None,
        }
    ]
    saved_data = saved["data"]
    assert list(saved_data["aliases"].items()) == [("300308", "300308")]
    assert saved_data["companies"]["300308"]["securities"][0]["inner_code"] == "A-INNER"
    assert result["interactions"]["applicable"] is True
    assert result["interactions"]["success"] is True
    assert result["interactions"]["total"] == 1


def test_establish_ah_pair_uses_a_code_as_key(monkeypatch: pytest.MonkeyPatch) -> None:
    saved = _setup(
        monkeypatch,
        securities=[
            _security("300308", "中际旭创", "AStock", "A-INNER"),
            _security("03308", "中际旭创", "HK", "H-INNER"),
        ],
    )
    result = company.establish_company(["300308", "03308"])

    assert result["company_key"] == "300308"
    assert {s["code"] for s in result["securities"]} == {"300308", "03308"}
    assert saved["data"]["aliases"] == {"300308": "300308", "03308": "300308"}
    # 港股同步带 inner_code 过滤
    assert len(result["securities"]) == 2


def test_establish_pure_hk_uses_h_code_as_key(monkeypatch: pytest.MonkeyPatch) -> None:
    saved = _setup(
        monkeypatch,
        securities=[_security("00700", "腾讯控股", "HK", "H-INNER")],
    )
    result = company.establish_company(["00700"])

    assert result["company_key"] == "00700"
    assert saved["data"]["aliases"] == {"00700": "00700"}
    assert result["interactions"] == {
        "applicable": False,
        "message": "港股无互动问答，不适用",
    }


def test_establish_rejects_two_a_stocks(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(
        monkeypatch,
        securities=[
            _security("300308", "中际旭创", "AStock", "A-INNER"),
            _security("600519", "贵州茅台", "AStock", "A-INNER2"),
        ],
    )
    with pytest.raises(ValueError, match="同市场"):
        company.establish_company(["300308", "600519"])


def test_establish_rejects_three_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, securities=[])
    with pytest.raises(ValueError, match="最多接受"):
        company.establish_company(["300308", "03308", "00700"])


def test_establish_rejects_empty_codes() -> None:
    with pytest.raises(ValueError, match="非空数组"):
        company.establish_company([])


def test_establish_rejects_non_numeric_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, securities=[])
    with pytest.raises(ValueError, match="必须是数字"):
        company.establish_company(["ABC"])


def test_establish_rejects_derivative(monkeypatch: pytest.MonkeyPatch) -> None:
    derivative = _security("13160", "腾讯中银六乙购B", "HK", "D-INNER", type_us="6")
    _setup(monkeypatch, securities=[derivative])
    with pytest.raises(ValueError, match="不是普通 A/H 公司证券"):
        company.establish_company(["13160"])


def test_establish_exact_code_match_ignores_fuzzy(monkeypatch: pytest.MonkeyPatch) -> None:
    """03308 搜索会同时命中 603308，必须按 Code 精确匹配。"""
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
    monkeypatch.setattr(company, "load_companies", lambda: _empty_registry())
    saved: dict[str, Any] = {}
    monkeypatch.setattr(company, "save_companies", lambda data: saved.update(data=data))
    monkeypatch.setattr(company, "sync_archive", _ok_sync)

    result = company.establish_company(["03308"])

    assert result["company_key"] == "03308"
    assert result["securities"][0]["market"] == "H"


def test_establish_conflict_with_another_company(monkeypatch: pytest.MonkeyPatch) -> None:
    """新代码已属于另一公司映射时拒绝合并。"""
    registry = {
        "companies": {
            "600519": {
                "securities": [
                    {
                        "code": "600519",
                        "market": "A",
                        "name": "贵州茅台",
                        "classify": "AStock",
                        "inner_code": "A-INNER2",
                    }
                ]
            },
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
            },
        },
        "aliases": {"600519": "600519", "00700": "00700"},
    }
    _setup(
        monkeypatch,
        securities=[
            _security("600519", "贵州茅台", "AStock", "A-INNER2"),
            _security("00700", "腾讯控股", "HK", "T-INNER"),
        ],
        registry=registry,
    )
    with pytest.raises(RuntimeError, match="分属不同公司"):
        company.establish_company(["600519", "00700"])


def test_establish_adds_new_security_to_existing_company(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已有 A 股建档，再补 H 股：不删除已有证券，新代码加入同一公司。"""
    registry = {
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
    }
    saved = _setup(
        monkeypatch,
        securities=[
            _security("300308", "中际旭创", "AStock", "A-INNER"),
            _security("03308", "中际旭创", "HK", "H-INNER"),
        ],
        registry=registry,
    )
    result = company.establish_company(["300308", "03308"])

    assert result["company_key"] == "300308"
    assert saved["data"]["aliases"] == {"300308": "300308", "03308": "300308"}
    codes = [s["code"] for s in saved["data"]["companies"]["300308"]["securities"]]
    assert codes == ["300308", "03308"]


def test_establish_rejects_second_hk_for_existing_company(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公司已有 H 股时，再加另一个 H 股代码报冲突。"""
    registry = {
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
    _setup(
        monkeypatch,
        securities=[
            _security("300308", "中际旭创", "AStock", "A-INNER"),
            _security("00700", "腾讯控股", "HK", "T-INNER"),
        ],
        registry=registry,
    )
    with pytest.raises(RuntimeError, match="现有 H 股代码冲突"):
        company.establish_company(["300308", "00700"])


def test_establish_partial_failure_keeps_saved_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H 股同步失败不影响公司映射保存和 A 股结果。"""
    saved = _setup(
        monkeypatch,
        securities=[
            _security("300308", "中际旭创", "AStock", "A-INNER"),
            _security("03308", "中际旭创", "HK", "H-INNER"),
        ],
    )

    def fake_sync(code: str, **_kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if code == "03308":
            raise RuntimeError("东方财富请求超时")
        return _ok_sync(code)

    monkeypatch.setattr(company, "sync_archive", fake_sync)
    result = company.establish_company(["300308", "03308"])

    assert saved["data"]["aliases"]["03308"] == "300308"
    by_code = {s["code"]: s for s in result["securities"]}
    assert by_code["300308"]["success"] is True
    assert by_code["03308"]["success"] is False
    assert by_code["03308"]["error"] == "东方财富请求超时"
