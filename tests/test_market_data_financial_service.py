# -*- coding: utf-8 -*-
"""get_financial_statements 工具层测试。"""

import csv
import os

from market_data_mcp import service


def _provider_result():
    statements = {}
    for statement in ("balance", "income", "cash_flow"):
        statements[statement] = [
            {
                "report_date": "2025-12-31",
                "metadata": {
                    "REPORT_TYPE": "年报",
                    "CURRENCY": "人民币",
                    "UPDATE_DATE": "2026-04-01",
                },
                "items": [
                    {
                        "item_code": "TOTAL_REVENUE" if statement == "income" else "ITEM",
                        "item_name": "营业总收入" if statement == "income" else "科目",
                        "amount": 100.0,
                        "source": "eastmoney",
                    }
                ],
            }
        ]
    return {
        "ok": True,
        "source": "eastmoney",
        "statements": statements,
        "metadata": {
            "code": "600519.SH",
            "market": "A",
            "sources": {"statements": "eastmoney"},
            "filings": [],
        },
        "error": None,
        "notes": None,
    }


def test_cumulative_refreshes_bundle_then_reuses_cache(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(root, mc, existing_metadata=None):
        calls.append((mc.code, existing_metadata))
        return _provider_result()

    monkeypatch.setattr(service.ifind, "fetch_statements", fake_fetch)

    first = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
    )
    second = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
    )

    assert first["ok"] is True and second["ok"] is True
    assert len(calls) == 1
    assert {path.name for path in (tmp_path / "cache" / "600519.SH" / "financial_statements").iterdir()} == {
        "metadata.json", "balance.json", "income.json", "cash_flow.json"
    }
    assert first["rows"][0]["item_name"] == "营业总收入"
    assert first["rows"][0]["value_basis"] == "cumulative"
    assert first["rows"][0]["version_count"] == 1
    assert first["stale"] is False


def test_single_subtracts_continuous_periods_and_omits_non_additive(tmp_path, monkeypatch):
    result = _provider_result()
    result["statements"]["income"] = [
        {
            "report_date": "2024-12-31",
            "metadata": {"REPORT_DATE_NAME": "年报", "CURRENCY": "人民币"},
            "items": [
                {"item_code": "TOTAL_REVENUE", "item_name": "营业总收入", "amount": 50.0, "source": "eastmoney"},
            ],
        },
        {
            "report_date": "2025-03-31",
            "metadata": {"REPORT_DATE_NAME": "一季报", "CURRENCY": "人民币"},
            "items": [
                {"item_code": "TOTAL_REVENUE", "item_name": "营业总收入", "amount": 100.0, "source": "eastmoney"},
                {"item_code": "BASIC_EPS", "item_name": "基本每股收益", "amount": 1.0, "source": "eastmoney"},
                {"item_code": "WEIGHTED_AVERAGE_SHARES", "item_name": "加权平均股数", "amount": 100.0, "source": "eastmoney"},
            ],
        },
        {
            "report_date": "2025-06-30",
            "metadata": {"REPORT_DATE_NAME": "半年报", "CURRENCY": "人民币"},
            "items": [
                {"item_code": "TOTAL_REVENUE", "item_name": "营业总收入", "amount": 260.0, "source": "eastmoney"},
                {"item_code": "BASIC_EPS", "item_name": "基本每股收益", "amount": 2.0, "source": "eastmoney"},
                {"item_code": "WEIGHTED_AVERAGE_SHARES", "item_name": "加权平均股数", "amount": 105.0, "source": "eastmoney"},
            ],
        },
    ]
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: result)

    response = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="single",
        statements=["income"],
        include_versions=True,
    )

    assert response["ok"] is True
    assert [(row["report_date"], row["amount"]) for row in response["rows"]] == [
        ("2025-03-31", 100.0),
        ("2025-06-30", 160.0),
    ]
    assert all(row["item_name"] == "营业总收入" and "item_code" not in row for row in response["rows"])
    assert response["rows"][1]["value_basis"] == "single"
    assert len(response["rows"][1]["derived_from_version_ids"]) == 2
    assert any("非加总科目" in note for note in response["notes"])
    assert any("include_versions" in note for note in response["notes"])

    q2_only = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="single",
        statements=["income"],
        start_date="2025-06-30",
        end_date="2025-06-30",
    )
    assert [(row["report_date"], row["amount"]) for row in q2_only["rows"]] == [
        ("2025-06-30", 160.0),
    ]
    assert not any("无法确认累计区间连续性" in note for note in (q2_only["notes"] or []))


def test_refresh_failure_returns_stale_bundle_but_no_cache_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: _provider_result())
    initial = service.get_financial_statements(
        str(tmp_path), "600519.SH", amount_basis="cumulative", statements=["income"]
    )
    assert initial["ok"] is True

    failure = {
        "ok": False,
        "source": "eastmoney",
        "statements": None,
        "metadata": None,
        "error": "上游超时",
        "notes": None,
    }
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: failure)
    stale = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
        force_refresh=True,
    )
    no_cache = service.get_financial_statements(
        str(tmp_path / "empty"),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
    )

    assert stale["ok"] is True and stale["stale"] is True
    assert stale["refresh_error"] == "上游超时"
    assert stale["rows"] == initial["rows"]
    assert no_cache == {"ok": False, "code": "600519.SH", "market": "A", "error": "上游超时"}


def test_financial_export_path_returns_metadata_only(tmp_path, monkeypatch):
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: _provider_result())
    target = tmp_path / "out" / "financial.csv"

    response = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
        export_path=str(target),
    )

    assert response["ok"] is True and response["path"] == str(target)
    assert response["total_items"] == 1 and "rows" not in response
    with target.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["item_name"] == "营业总收入"
    assert "item_code" not in rows[0]
    assert rows[0]["source_update_date"] == "2026-04-01"
    assert rows[0]["change_summary"] == "null"
    assert '"REPORT_TYPE": "年报"' in rows[0]["report_metadata"]

    monkeypatch.chdir(tmp_path)
    bare = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
        export_path="financial.csv",
    )
    assert bare["ok"] is True and (tmp_path / "financial.csv").exists()


def test_versions_default_latest_and_include_versions_returns_history(tmp_path, monkeypatch):
    first_provider = _provider_result()
    second_provider = _provider_result()
    second_provider["statements"]["income"][0]["items"][0]["amount"] = 120.0
    responses = iter([first_provider, second_provider])
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: next(responses))

    service.get_financial_statements(
        str(tmp_path), "600519.SH", amount_basis="cumulative", statements=["income"]
    )
    latest = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
        force_refresh=True,
    )
    history = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
        include_versions=True,
    )

    assert [row["amount"] for row in latest["rows"]] == [120.0]
    assert latest["rows"][0]["version_count"] == 2 and latest["rows"][0]["has_revisions"] is True
    assert latest["rows"][0]["source_update_date"] == "2026-04-01"
    assert latest["rows"][0]["change_summary"]["changed_item_codes"] == ["TOTAL_REVENUE"]
    assert sorted(row["amount"] for row in history["rows"]) == [100.0, 120.0]
    assert sum(row["is_latest"] for row in history["rows"]) == 1


def test_us_source_includes_eastmoney_and_sec(tmp_path, monkeypatch):
    provider = _provider_result()
    provider["metadata"].update({
        "code": "AAPL.US",
        "market": "US",
        "sources": {"statements": "eastmoney", "filings": "sec"},
        "cik": "0000320193",
        "sec_history_complete": True,
    })
    # 美股仍走东财 provider（A/BJ 才切 iFinD）
    monkeypatch.setattr(service.financial_statements, "fetch", lambda *args, **kwargs: provider)

    response = service.get_financial_statements(
        str(tmp_path), "AAPL.US", amount_basis="cumulative", statements=["income"]
    )

    assert response["source"] == "eastmoney,sec"


def test_financial_auto_exports_over_200_rows(tmp_path, monkeypatch):
    provider = _provider_result()
    provider["statements"]["income"][0]["items"] = [
        {
            "item_code": f"ITEM_{index:03d}",
            "item_name": f"科目{index:03d}",
            "amount": float(index),
            "source": "eastmoney",
        }
        for index in range(201)
    ]
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: provider)

    response = service.get_financial_statements(
        str(tmp_path), "600519.SH", amount_basis="cumulative", statements=["income"]
    )

    assert response["auto_exported"] is True and response["total_items"] == 201
    assert "rows" not in response and os.path.exists(response["path"])


def test_financial_parameter_validation(tmp_path):
    root = str(tmp_path)
    assert service.get_financial_statements(root, "600519", amount_basis="cumulative")["ok"] is False
    assert service.get_financial_statements(root, "600519.SH", amount_basis="both")["ok"] is False
    assert service.get_financial_statements(
        root, "600519.SH", amount_basis="cumulative", statements=["ratios"]
    )["ok"] is False
    assert service.get_financial_statements(
        root,
        "600519.SH",
        amount_basis="cumulative",
        start_date="2025-12-31",
        end_date="2025-01-01",
    )["ok"] is False


def test_data_catalog_reads_cached_non_null_items_across_versions_without_network(tmp_path, monkeypatch):
    first = _provider_result()
    first["statements"]["income"][0]["items"] = [
        {"item_code": "OPERATE_INCOME", "item_name": "OPERATE_INCOME", "amount": 100.0, "source": "eastmoney"},
        {"item_code": "ALWAYS_EMPTY", "item_name": "ALWAYS_EMPTY", "amount": None, "source": "eastmoney"},
    ]
    second = _provider_result()
    second["statements"]["income"][0]["report_date"] = "2024-12-31"
    second["statements"]["income"][0]["items"] = [
        {"item_code": "OPERATE_INCOME", "item_name": "OPERATE_INCOME", "amount": 80.0, "source": "eastmoney"},
        {"item_code": "OLD_ITEM", "item_name": "OLD_ITEM", "amount": 1.0, "source": "eastmoney"},
    ]
    responses = iter([first, second])
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: next(responses))
    service.get_financial_statements(
        str(tmp_path), "600519.SH", amount_basis="cumulative", statements=["income"]
    )
    service.get_financial_statements(
        str(tmp_path), "600519.SH", amount_basis="cumulative", statements=["income"], force_refresh=True
    )
    monkeypatch.setattr(
        service.ifind,
        "fetch_statements",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("目录工具不得联网")),
    )

    response = service.get_data_catalog(str(tmp_path), "600519.SH", statements=["income"])

    assert response["ok"] is True
    assert response["statements"] == ["income"]
    assert response["items"] == [
        {
            "statement": "income",
            "item_name": "OLD_ITEM",
            "first_report_date": "2024-12-31",
            "last_report_date": "2024-12-31",
        },
        {
            "statement": "income",
            "item_name": "营业收入",
            "first_report_date": "2024-12-31",
            "last_report_date": "2025-12-31",
        },
    ]


def test_financial_query_accepts_exact_chinese_item_and_hides_english_code(tmp_path, monkeypatch):
    provider = _provider_result()
    provider["statements"]["income"][0]["items"] = [
        {"item_code": "OPERATE_INCOME", "item_name": "OPERATE_INCOME", "amount": 100.0, "source": "eastmoney"},
        {"item_code": "PARENT_NETPROFIT", "item_name": "PARENT_NETPROFIT", "amount": 20.0, "source": "eastmoney"},
    ]
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: provider)

    response = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
        items=["营业收入"],
    )

    assert response["ok"] is True
    assert response["status"] == "success"
    assert response["failed_items"] == []
    assert [(row["item_name"], row["amount"]) for row in response["rows"]] == [("营业收入", 100.0)]
    assert "item_code" not in response["rows"][0]


def test_financial_query_returns_ambiguous_keyword_candidates_and_failed_items(tmp_path, monkeypatch):
    provider = _provider_result()
    provider["statements"]["income"][0]["items"] = [
        {"item_code": "OPERATE_INCOME", "item_name": "OPERATE_INCOME", "amount": 100.0, "source": "eastmoney"},
        {"item_code": "PARENT_NETPROFIT", "item_name": "PARENT_NETPROFIT", "amount": 20.0, "source": "eastmoney"},
        {"item_code": "DEDUCT_PARENT_NETPROFIT", "item_name": "DEDUCT_PARENT_NETPROFIT", "amount": 18.0, "source": "eastmoney"},
    ]
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: provider)

    response = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
        items=["营业收入", "归母净利", "毛利"],
    )

    assert response["ok"] is True
    assert response["status"] == "partial_success"
    assert [(row["item_name"], row["amount"]) for row in response["rows"]] == [("营业收入", 100.0)]
    assert response["failed_items"][0] == {
        "requested_name": "归母净利",
        "reason": "multiple_candidates",
        "match_type": "keyword_candidates",
        "candidates": [
            {
                "item_name": "归属于母公司股东的净利润",
                "latest_report_date": "2025-12-31",
                "latest_amount": 20.0,
                "currency": "人民币",
            },
            {
                "item_name": "归属于母公司股东的扣除非经常性损益的净利润",
                "latest_report_date": "2025-12-31",
                "latest_amount": 18.0,
                "currency": "人民币",
            },
        ],
    }
    assert response["failed_items"][1]["requested_name"] == "毛利"
    assert response["failed_items"][1]["reason"] == "not_found"
    assert "不计算衍生指标" in response["failed_items"][1]["hint"]


def test_financial_report_types_support_annual_cumulative_and_q4_single(tmp_path, monkeypatch):
    provider = _provider_result()
    provider["statements"]["income"] = [
        {
            "report_date": report_date,
            "metadata": {"REPORT_DATE_NAME": report_name, "REPORT_TYPE": report_name, "CURRENCY": "人民币"},
            "items": [
                {"item_code": "OPERATE_INCOME", "item_name": "OPERATE_INCOME", "amount": amount, "source": "eastmoney"}
            ],
        }
        for report_date, report_name, amount in (
            ("2025-03-31", "一季报", 100.0),
            ("2025-06-30", "半年报", 200.0),
            ("2025-09-30", "三季报", 250.0),
            ("2025-12-31", "年报", 400.0),
        )
    ]
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: provider)

    cumulative = service.get_financial_statements(
        str(tmp_path), "600519.SH", amount_basis="cumulative",
        statements=["income"], report_types=["annual"], items=["营业收入"],
    )
    single = service.get_financial_statements(
        str(tmp_path), "600519.SH", amount_basis="single",
        statements=["income"], report_types=["annual"], items=["营业收入"],
    )

    assert [(row["report_date"], row["amount"]) for row in cumulative["rows"]] == [("2025-12-31", 400.0)]
    assert [(row["report_date"], row["amount"]) for row in single["rows"]] == [("2025-12-31", 150.0)]


def test_financial_query_accepts_alias_and_notes_substitute(tmp_path, monkeypatch):
    provider = _provider_result()
    provider["statements"]["income"][0]["items"] = [
        {"item_code": "TOTAL_OPERATE_INCOME", "item_name": "TOTAL_OPERATE_INCOME", "amount": 100.0, "source": "eastmoney"},
        {"item_code": "OPERATE_INCOME", "item_name": "OPERATE_INCOME", "amount": 90.0, "source": "eastmoney"},
        {"item_code": "OPERATE_COST", "item_name": "OPERATE_COST", "amount": 60.0, "source": "eastmoney"},
        {"item_code": "DEDUCT_PARENT_NETPROFIT", "item_name": "DEDUCT_PARENT_NETPROFIT", "amount": 18.0, "source": "eastmoney"},
    ]
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: provider)

    response = service.get_financial_statements(
        str(tmp_path),
        "600519.SH",
        amount_basis="cumulative",
        statements=["income"],
        items=["营业成本", "扣非净利润", "营收"],
    )

    assert response["ok"] is True
    assert response["status"] == "success"
    assert response["failed_items"] == []
    assert [(row["item_name"], row["amount"]) for row in response["rows"]] == [
        ("归属于母公司股东的扣除非经常性损益的净利润", 18.0),
        ("营业成本", 60.0),
        ("营业收入", 90.0),
    ]
    assert response["notes"] == [
        "科目“扣非净利润”按简称匹配为“归属于母公司股东的扣除非经常性损益的净利润”，并非精确名称匹配",
        "科目“营收”按简称匹配为“营业收入”，并非精确名称匹配",
        "科目名称等价：归属于母公司股东的扣除非经常性损益的净利润=扣非净利润=扣非归母净利润；营业收入=营收",
    ]


def test_financial_items_mapping_invariants():
    from market_data_mcp import financial_items

    table = financial_items.A_SHARE_ITEM_NAMES
    full_names = [names[0] for names in table.values()]
    aliases = [alias for names in table.values() for alias in names[1:]]
    assert all(names for names in table.values())
    assert len(aliases) == len(set(aliases))
    duplicated = {name for name in full_names if full_names.count(name) > 1}
    assert duplicated == {"利息收入", "信用减值损失", "资产减值损失"}
    # 简称与全名重复的唯一例外：CASH_DEPOSIT_PBC（银行=现金及存放中央银行款项 /
    # 金租=货币资金），显示名取银行口径，等价关系随返回 notes 说明
    assert set(aliases) & set(full_names) == {"货币资金"}


def test_financial_query_supports_template_alias_and_relation_note(tmp_path, monkeypatch):
    provider = _provider_result()
    provider["statements"]["balance"][0]["items"] = [
        {"item_code": "CASH_DEPOSIT_PBC", "item_name": "CASH_DEPOSIT_PBC", "amount": 100.0, "source": "eastmoney"},
    ]
    monkeypatch.setattr(service.ifind, "fetch_statements", lambda *args, **kwargs: provider)

    by_full = service.get_financial_statements(
        str(tmp_path), "600519.SH", amount_basis="cumulative",
        statements=["balance"], items=["现金及存放中央银行款项"],
    )
    by_alias = service.get_financial_statements(
        str(tmp_path), "600519.SH", amount_basis="cumulative",
        statements=["balance"], items=["货币资金"],
    )

    assert [(row["item_name"], row["amount"]) for row in by_full["rows"]] == [
        ("现金及存放中央银行款项", 100.0),
    ]
    assert by_full["failed_items"] == []
    assert "科目名称等价：现金及存放中央银行款项=货币资金" in by_full["notes"]
    assert [(row["item_name"], row["amount"]) for row in by_alias["rows"]] == [
        ("现金及存放中央银行款项", 100.0),
    ]
    assert "科目“货币资金”按简称匹配为“现金及存放中央银行款项”，并非精确名称匹配" in by_alias["notes"]
    assert "科目名称等价：现金及存放中央银行款项=货币资金" in by_alias["notes"]
