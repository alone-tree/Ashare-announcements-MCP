# -*- coding: utf-8 -*-
"""财报四文件缓存与版本合并测试。"""

from market_data_mcp import financial_cache


def _report(amount):
    return {
        "report_date": "2025-12-31",
        "metadata": {"REPORT_TYPE": "年报", "CURRENCY": "CNY"},
        "items": [
            {"item_code": "REVENUE", "item_name": "REVENUE", "amount": amount, "source": "eastmoney"},
            {"item_code": "EMPTY_ITEM", "item_name": "EMPTY_ITEM", "amount": None, "source": "eastmoney"},
        ],
    }


def test_merge_statement_preserves_versions_and_nulls():
    first = financial_cache.merge_statement(
        None,
        [_report(100.0)],
        code="600519.SH",
        market="A",
        statement="income",
        source="eastmoney",
        observed_at="2026-08-09T10:00:00",
        batch_id="batch-1",
    )
    second = financial_cache.merge_statement(
        first,
        [_report(120.0)],
        code="600519.SH",
        market="A",
        statement="income",
        source="eastmoney",
        observed_at="2026-09-09T10:00:00",
        batch_id="batch-2",
    )

    report = second["reports"][0]
    assert len(report["versions"]) == 2
    assert report["current_version_id"] == report["versions"][1]["version_id"]
    assert report["versions"][0]["items"][1]["amount"] is None
    assert report["versions"][0]["items"][0]["amount"] == 100.0
    assert report["versions"][1]["items"][0]["amount"] == 120.0
    assert second["item_catalog"] == [
        {"item_code": "EMPTY_ITEM", "item_name": "EMPTY_ITEM"},
        {"item_code": "REVENUE", "item_name": "REVENUE"},
    ]


def test_bundle_has_five_files_and_shared_batch(tmp_path):
    batch_id = "batch-1"
    statements = {
        name: financial_cache.merge_statement(
            None,
            [_report(100.0)],
            code="600519.SH",
            market="A",
            statement=name,
            source="eastmoney",
            observed_at="2026-08-09T10:00:00",
            batch_id=batch_id,
        )
        for name in ("balance", "income", "cash_flow", "meta")
    }
    metadata = {
        "meta": {
            "schema_version": 1,
            "code": "600519.SH",
            "market": "A",
            "source": "eastmoney",
            "last_successful_update": "2026-08-09T10:00:00",
            "update_batch_id": batch_id,
        },
        "filings": [],
    }

    financial_cache.commit_bundle(str(tmp_path), "600519.SH", metadata, statements)
    bundle = financial_cache.read_bundle(str(tmp_path), "600519.SH")

    assert bundle is not None
    assert set(path.name for path in (tmp_path / "cache" / "600519.SH" / "financial_statements").iterdir()) == {
        "metadata.json", "balance.json", "income.json", "cash_flow.json", "meta.json"
    }
    assert {bundle[name]["meta"]["update_batch_id"] for name in ("metadata", "balance", "income", "cash_flow", "meta")} == {batch_id}
    assert "present_in_latest_refresh" not in bundle["income"]["reports"][0]
    assert bundle["income"]["meta"]["date_range"] == {"start": "2025-12-31", "end": "2025-12-31"}
    assert bundle["income"]["meta"]["shape"] == {"reports": 1}


def test_period_by_period_commit_keeps_earlier_periods(tmp_path):
    """惰性拉取逐期提交：每期单独一批，早先的期原样保留。"""
    def commit(period, amount, batch_id, existing):
        report = {
            "report_date": period,
            "metadata": {"REPORT_DATE_NAME": "年报", "CURRENCY": "CNY"},
            "items": [{"item_code": "REVENUE", "item_name": "REVENUE", "amount": amount, "source": "ifind"}],
        }
        statements = {
            name: financial_cache.empty_statement("600519.SH", "A", name, "ifind", batch_id)
            for name in ("balance", "cash_flow", "meta")
        }
        statements["income"] = financial_cache.merge_statement(
            (existing or {}).get("income"), [report], code="600519.SH", market="A",
            statement="income", source="ifind", observed_at="2026-10-21T10:00:00", batch_id=batch_id,
        )
        metadata = financial_cache.empty_metadata("600519.SH", "A", "ifind", batch_id)
        metadata["meta"]["last_successful_update"] = "2026-10-21T10:00:00"
        financial_cache.commit_bundle(str(tmp_path), "600519.SH", metadata, statements)
        return financial_cache.read_bundle(str(tmp_path), "600519.SH")

    bundle = commit("2025-09-30", 90.0, "batch-a", None)
    bundle = commit("2025-12-31", 120.0, "batch-b", bundle)

    assert [report["report_date"] for report in bundle["income"]["reports"]] == ["2025-09-30", "2025-12-31"]
    assert bundle["income"]["meta"]["shape"] == {"reports": 2}
    assert bundle["income"]["meta"]["update_batch_id"] == "batch-b"
