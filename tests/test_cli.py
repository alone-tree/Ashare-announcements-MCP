"""公告批处理 CLI 与共享查询服务的无网络测试。"""

import io
import json

import pytest

from ashare_announcements_mcp import cli, service


def test_query_archive_filters_before_cli_batch(monkeypatch) -> None:
    items = [
        {
            "short_name": "测试公司",
            "stock_code": "000001",
            "display_time": "2026-07-30 10:00:00",
            "column_name": "公司治理",
            "title": "关于回购股份的公告",
            "url": "https://pdf.dfcfw.com/pdf/H2_A_1.pdf",
            "code": "A",
        },
        {
            "short_name": "测试公司",
            "stock_code": "000001",
            "display_time": "2026-07-20 10:00:00",
            "column_name": "公司治理",
            "title": "关于召开股东大会的公告",
            "url": "https://pdf.dfcfw.com/pdf/H2_B_1.pdf",
            "code": "B",
        },
    ]
    monkeypatch.setattr(
        service,
        "load_companies",
        lambda: {
            "companies": {
                "000001": {
                    "securities": [
                        {
                            "code": "000001",
                            "market": "A",
                            "name": "测试公司",
                            "classify": "AStock",
                            "inner_code": "A-INNER",
                        }
                    ]
                }
            },
            "aliases": {"000001": "000001"},
        },
    )
    monkeypatch.setattr(
        service,
        "sync_archive",
        lambda _code, **_kwargs: (
            items,
            {"update_check_ok": True, "new_announcements": 0, "update_error": None},
        ),
    )

    result = service.query_archive(
        "SZ000001",
        start_date="2026-07-29",
        end_date="2026-07-30",
        keyword="回购",
    )

    assert result["stock_code"] == "000001"
    assert result["company_key"] == "000001"
    assert result["total_announcements"] == 2
    assert result["matched"] == 1
    assert result["results"][0]["code"] == "A"


def test_paginate_query_preserves_metadata() -> None:
    result = {
        "stock_code": "000001",
        "matched": 3,
        "results": [{"code": "A"}, {"code": "B"}, {"code": "C"}],
    }

    page = service.paginate_query(result, page=2, page_size=2)

    assert page["stock_code"] == "000001"
    assert page["page"] == 2
    assert page["total_pages"] == 2
    assert page["has_more"] is False
    assert page["results"] == [{"code": "C"}]


def test_query_batch_flattens_all_company_results(monkeypatch) -> None:
    def fake_query(stock_code, **_kwargs):
        if stock_code == "999999":
            raise RuntimeError("测试失败")
        return {
            "stock_code": stock_code,
            "stock_name": "测试公司",
            "total_announcements": 1,
            "matched": 1,
            "update_check_ok": True,
            "new_announcements": 0,
            "update_error": None,
            "results": [{"stock_code": stock_code, "code": f"A-{stock_code}"}],
        }

    monkeypatch.setattr(cli, "query_archive", fake_query)

    result = cli.dispatch(
        {
            "action": "query_batch",
            "stock_codes": ["000001", "000002", "999999"],
            "start_date": "2026-07-30",
        }
    )

    assert result["status"] == "partial_success"
    assert result["requested"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert [item["code"] for item in result["announcements"]] == ["A-000001", "A-000002"]


def test_inspect_batch_keeps_identity_on_failure(monkeypatch) -> None:
    def fake_inspect(item):
        if item["code"] == "B":
            raise RuntimeError("PDF 无法下载")
        return {
            "stock_code": item["stock_code"],
            "url": item["url"],
            "code": item["code"],
            "title": item["title"],
            "total_pages": 2,
            "profile": "short",
        }

    monkeypatch.setattr(cli, "_inspect_item", fake_inspect)
    announcements = [
        {"stock_code": "000001", "url": "https://example.com/A.pdf", "code": "A", "title": "A公告"},
        {"stock_code": "000001", "url": "https://example.com/B.pdf", "code": "B", "title": "B公告"},
    ]

    result = cli.dispatch({"action": "inspect_batch", "announcements": announcements})

    assert result["status"] == "partial_success"
    assert result["inspections"][0]["total_pages"] == 2
    assert result["inspections"][1]["code"] == "B"
    assert result["inspections"][1]["error"] == "PDF 无法下载"


def test_read_batch_passes_request_options_and_returns_text(monkeypatch) -> None:
    captured = {}

    def fake_read(item, request):
        captured.update(request)
        return {
            "stock_code": item["stock_code"],
            "url": item["url"],
            "code": item["code"],
            "title": item["title"],
            "text": "公告正文",
            "chars_returned": 4,
            "pages_returned": [1],
            "next_page": None,
            "is_last_chunk": True,
        }

    monkeypatch.setattr(cli, "_read_item", fake_read)
    result = cli.dispatch(
        {
            "action": "read_batch",
            "announcements": [
                {
                    "stock_code": "000001",
                    "url": "https://example.com/A.pdf",
                    "code": "A",
                    "title": "A公告",
                }
            ],
            "max_chars": 20_000,
            "ocr": False,
        }
    )

    assert result["status"] == "success"
    assert result["readings"][0]["text"] == "公告正文"
    assert captured["max_chars"] == 20_000
    assert captured["ocr"] is False


def test_search_batch_passes_keywords_and_returns_hits(monkeypatch) -> None:
    captured = {}

    def fake_search(item, request):
        captured.update(request)
        return {
            "stock_code": item["stock_code"],
            "url": item["url"],
            "code": item["code"],
            "title": item["title"],
            "query": request["query"],
            "matched_pages": 1,
            "search_complete": True,
            "results": [{"page": 7, "score": 2, "snippet": "交易价格"}],
        }

    monkeypatch.setattr(cli, "_search_item", fake_search)
    result = cli.dispatch(
        {
            "action": "search_batch",
            "announcements": [
                {
                    "stock_code": "000001",
                    "url": "https://example.com/A.pdf",
                    "code": "A",
                    "title": "重大资产重组报告书",
                }
            ],
            "query": "交易价格 业绩承诺",
            "max_results": 10,
            "ocr_scanned": False,
        }
    )

    assert result["status"] == "success"
    assert result["searches"][0]["results"][0]["page"] == 7
    assert captured["query"] == "交易价格 业绩承诺"
    assert captured["ocr_scanned"] is False


def test_search_batch_rejects_null_query() -> None:
    result = cli.dispatch(
        {
            "action": "search_batch",
            "announcements": [
                {
                    "stock_code": "000001",
                    "url": "https://example.com/A.pdf",
                    "query": None,
                }
            ],
        }
    )

    assert result["status"] == "failed"
    assert result["searches"][0]["error"] == "每条公告必须包含 query，或在请求顶层提供 query"


def test_main_reads_stdin_and_writes_one_json_response(monkeypatch) -> None:
    monkeypatch.setattr(cli, "dispatch", lambda request: {"ok": True, "action": request["action"]})
    stdin = io.StringIO('{"action":"query_batch"}')
    stdout = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)

    cli.main()

    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"ok": True, "action": "query_batch"}


def test_main_returns_top_level_error_for_non_object(monkeypatch) -> None:
    stdin = io.StringIO("[]")
    stdout = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)

    cli.main()

    result = json.loads(stdout.getvalue())
    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["error"] == "请求必须是 JSON 对象"


def test_cli_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="未知 action"):
        cli.dispatch({"action": "unknown"})
