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

    monkeypatch.setattr(service.financial_statements, "fetch", fake_fetch)

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
    monkeypatch.setattr(service.financial_statements, "fetch", lambda *args, **kwargs: result)

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
    assert all(row["item_code"] == "TOTAL_REVENUE" for row in response["rows"])
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
    monkeypatch.setattr(service.financial_statements, "fetch", lambda *args, **kwargs: _provider_result())
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
    monkeypatch.setattr(service.financial_statements, "fetch", lambda *args, **kwargs: failure)
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
    monkeypatch.setattr(service.financial_statements, "fetch", lambda *args, **kwargs: _provider_result())
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
    monkeypatch.setattr(service.financial_statements, "fetch", lambda *args, **kwargs: next(responses))

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
    monkeypatch.setattr(service.financial_statements, "fetch", lambda *args, **kwargs: provider)

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
