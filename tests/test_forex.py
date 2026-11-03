# -*- coding: utf-8 -*-
"""汇率get_quote回归：本地历史、HQ增量、双入口及临时导出；不调用真实SDK。"""

import asyncio
import csv
import importlib.util
import json
import math
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_data_mcp import aggregator, cache, cli, company_service, financial_service
from market_data_mcp import forex, market_help, server, service
from market_data_mcp.providers import ifind, sina, yfinance
from market_data_mcp.routing import MarketCode, parse_code


CODES = ("HKDCNY.FX", "USDHKD.FX", "USDCNY.IN")
HISTORY_START = "1995-01-01"
HISTORY_END = "2026-09-30"
LIVE_START = "2026-10-01"
REPO = Path(__file__).resolve().parents[1]


def _blocked(*args, **kwargs):
    pytest.fail("汇率测试禁止真实SDK、股票provider或联网调用")


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKET_DATA_ROOT", str(tmp_path))
    for name in ("request_ifind", "_sdk_call", "_ensure_login", "_detect_suffix", "_trade_days"):
        monkeypatch.setattr(ifind, name, _blocked)
    for name in ("fetch_raw", "fetch_hfq"):
        monkeypatch.setattr(sina, name, _blocked)
    monkeypatch.setattr(yfinance, "fetch_shares", _blocked)
    monkeypatch.setattr("requests.sessions.Session.request", _blocked)


def _mc(code):
    bare, suffix = code.rsplit(".", 1)
    return MarketCode("FX", bare, suffix)


def _sdk(monkeypatch, dates=(LIVE_START, "2026-10-02"), values=(7.1, 7.2), error=None):
    calls = []

    def request(root, api, *args, **kwargs):
        calls.append((root, api, args, kwargs))
        if error:
            return SimpleNamespace(errorcode=-1, errmsg=error, data=None)
        return SimpleNamespace(errorcode=0, errmsg="", data=pd.DataFrame({
            "time": list(dates), "thscode": [args[0]] * len(dates), "close": list(values),
        }))

    monkeypatch.setattr(ifind, "request_ifind", request)
    return calls


def _assert_quote(result):
    assert result["ok"] is True, result
    assert result["market"] == "FX"
    assert result["vars"] == ["close"]
    assert result["adjust"] == "raw"
    for row in result.get("rows", []):
        assert set(row) == {"date", "close"}
        assert row["close"] is None or math.isfinite(row["close"])
    json.dumps(result, allow_nan=False)


def _read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def _assert_close_cache(root, code, start, end, rows=None, dates=None):
    folder = Path(root) / "cache" / code
    assert sorted(path.name for path in folder.iterdir()) == ["close.json"]
    saved = cache.read_cache(str(root), code, "close")
    assert saved["meta"]["market"] == "FX"
    assert saved["meta"]["field"] == "close"
    assert saved["meta"]["source"] == "ifind"
    assert saved["meta"]["date_range"] == {"start": start, "end": end}
    expected_dates = dates if dates is not None else pd.date_range(start, end).strftime("%Y-%m-%d").tolist()
    assert [row["date"] for row in saved["items"]] == expected_dates
    assert all(set(row) == {"date", "value", "source"} and row["source"] == "ifind"
               for row in saved["items"])
    if rows is not None:
        assert saved["items"] == [
            {"date": row["date"], "value": row["close"], "source": "ifind"} for row in rows
        ]
    json.dumps(saved, allow_nan=False)
    return saved


def test_history_csv_shape_continuity_and_only_leading_nulls():
    path = Path(forex.HISTORY_PATH)
    assert path == REPO / "src" / "market_data_mcp" / "data" / "fx_history.csv"
    assert tuple(forex.CODES) == CODES
    assert forex.HISTORY_START == HISTORY_START
    assert forex.HISTORY_END == HISTORY_END
    assert forex.LIVE_START == LIVE_START
    columns, rows = _read_csv(path)
    assert columns == ["date", *CODES]
    expected_dates = [(date(1995, 1, 1) + timedelta(days=i)).isoformat() for i in range(11596)]
    assert [row["date"] for row in rows] == expected_dates
    assert rows[-1]["date"] == HISTORY_END
    history = forex.read_history()
    assert list(history) == expected_dates
    for index, row in enumerate(rows):
        assert set(history[row["date"]]) == set(CODES)
        for code in CODES:
            value = history[row["date"]][code]
            if code == "USDHKD.FX" and index < 543:
                assert row[code] == "" and value is None
            else:
                assert row[code] != ""
                assert isinstance(value, (float, int)) and math.isfinite(value)
                assert value == float(row[code])
    assert expected_dates[543] == "1996-06-27"
    assert history["2018-06-18"]["HKDCNY.FX"] == 0.8174


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("start,end", [
    ("1994-12-29", "1995-01-03"),
    ("1989-12-30", "1990-01-02"),
    ("1996-06-26", "1996-06-28"),
    ("2018-06-17", "2018-06-19"),
    ("2026-09-28", HISTORY_END),
])
def test_historical_and_pre_history_requests_use_aggregator_and_close_cache(tmp_path, monkeypatch, code, start, end):
    ensured = []
    original = aggregator.ensure

    def ensure(root, mc, field, chain, start=None, end=None):
        ensured.append((mc, field, start, end))
        return original(root, mc, field, chain, start, end)

    monkeypatch.setattr(aggregator, "ensure", ensure)
    result = service.get_quote(str(tmp_path), code, start_date=start, end_date=end)
    _assert_quote(result)
    assert ensured == [(_mc(code), "close", start, end)]
    history = forex.read_history()
    dates = pd.date_range(start, end).strftime("%Y-%m-%d").tolist()
    assert result["rows"] == [
        {"date": day, "close": history.get(day, {}).get(code)} for day in dates
    ]
    _assert_close_cache(tmp_path, code, start, end, result["rows"])


@pytest.mark.parametrize("code,start,end", [
    ("USDHKD.FX", HISTORY_START, "1995-01-03"),
    ("HKDCNY.FX", "2018-06-17", "2018-06-19"),
    ("USDCNY.IN", "1989-12-30", "1990-01-02"),
])
def test_repeated_history_including_all_null_skips_source_read(tmp_path, monkeypatch, code, start, end):
    root = str(tmp_path)
    first = service.get_quote(root, code, start_date=start, end_date=end)
    _assert_quote(first)
    saved = _assert_close_cache(root, code, start, end, first["rows"])
    if code != "HKDCNY.FX":
        assert all(row["value"] is None for row in saved["items"])
    monkeypatch.setattr(forex, "read_history", _blocked)
    monkeypatch.setattr(ifind, "fetch_fx", _blocked)
    second = service.get_quote(root, code, start_date=start, end_date=end)
    _assert_quote(second)
    assert second["rows"] == first["rows"]
    assert cache.read_cache(root, code, "close") == saved


def test_all_starts_at_history_start_without_network(tmp_path):
    result = service.get_quote(str(tmp_path), "USDHKD.FX", start_date="all", end_date="1995-01-03")
    _assert_quote(result)
    assert result["rows"] == [
        {"date": "1995-01-01", "close": None},
        {"date": "1995-01-02", "close": None},
        {"date": "1995-01-03", "close": None},
    ]
    _assert_close_cache(tmp_path, "USDHKD.FX", HISTORY_START, "1995-01-03", result["rows"])


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("start,end", [
    ("1989-12-30", "1990-01-02"),
    (HISTORY_START, "1995-01-03"),
    ("2018-06-17", "2018-06-19"),
])
def test_provider_history_returns_raw_batch_without_writing_cache(tmp_path, code, start, end):
    history = forex.read_history()
    result = ifind.fetch_fx(str(tmp_path), _mc(code), start, end)
    assert result["ok"] is True, result
    assert result["source"] == "ifind"
    assert result["data"] == {"close": [
        {"date": day, "value": history.get(day, {}).get(code), "source": "ifind"}
        for day in pd.date_range(start, end).strftime("%Y-%m-%d")
    ]}
    assert not (tmp_path / "cache").exists()
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("code", CODES)
def test_provider_hq_original_code_close_empty_parameter_and_no_cache(tmp_path, monkeypatch, code):
    calls = _sdk(monkeypatch, values=(7.1, float("nan")))
    root = str(tmp_path)
    result = ifind.fetch_fx(root, _mc(code), LIVE_START, "2026-10-02")
    assert result["ok"] is True, result
    assert result["source"] == "ifind"
    assert result["data"] == {"close": [
        {"date": LIVE_START, "value": 7.1, "source": "ifind"},
        {"date": "2026-10-02", "value": None, "source": "ifind"},
    ]}
    assert len(calls) == 1
    assert calls[0][:3] == (root, "THS_HQ", (code, "close", "", LIVE_START, "2026-10-02"))
    assert set(calls[0][3]) <= {"required_columns"}
    assert not (tmp_path / "cache").exists()
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("code", CODES)
def test_provider_cross_boundary_returns_one_raw_batch_without_cache(tmp_path, monkeypatch, code):
    calls = _sdk(monkeypatch)
    result = ifind.fetch_fx(str(tmp_path), _mc(code), "2026-09-29", "2026-10-02")
    assert result["ok"] is True and result["source"] == "ifind", result
    expected = [
        {"date": day, "value": forex.read_history()[day][code], "source": "ifind"}
        for day in ("2026-09-29", HISTORY_END)
    ] + [
        {"date": LIVE_START, "value": 7.1, "source": "ifind"},
        {"date": "2026-10-02", "value": 7.2, "source": "ifind"},
    ]
    assert result["data"] == {"close": expected}
    assert len(calls) == 1
    assert calls[0][2] == (code, "close", "", LIVE_START, "2026-10-02")
    assert not (tmp_path / "cache").exists()


def test_history_keeps_service_provider_commit_and_cache_pipeline(tmp_path, monkeypatch):
    events = []

    def track(module, name):
        original = getattr(module, name)

        def wrapped(*args, **kwargs):
            events.append(name)
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapped)

    for module, name in ((service, "_ensure_fields"), (aggregator, "ensure"),
                         (ifind, "fetch_fx"), (aggregator, "commit_quote_batch"),
                         (cache, "read_cache"), (cache, "write_cache")):
        track(module, name)
    result = service.get_quote(str(tmp_path), "HKDCNY.FX", start_date="2018-06-18", end_date="2018-06-18")
    _assert_quote(result)
    assert result["rows"] == [{"date": "2018-06-18", "close": 0.8174}]
    assert events.index("_ensure_fields") < events.index("ensure") < events.index("fetch_fx")
    assert events.index("fetch_fx") < events.index("commit_quote_batch") < events.index("write_cache")
    assert "read_cache" in events[:events.index("fetch_fx")]
    assert "read_cache" in events[events.index("write_cache") + 1:]
    _assert_close_cache(tmp_path, "HKDCNY.FX", "2018-06-18", "2018-06-18", result["rows"])


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("start", ["2026-09-29", LIVE_START])
def test_full_request_uses_aggregator_and_provider_split_in_one_close_cache(tmp_path, monkeypatch, code, start):
    calls = _sdk(monkeypatch)
    ensured = []
    original = aggregator.ensure

    def ensure(root, mc, field, chain, start=None, end=None):
        ensured.append((mc, field, start, end))
        return original(root, mc, field, chain, start, end)

    monkeypatch.setattr(aggregator, "ensure", ensure)
    root = str(tmp_path)
    first = service.get_quote(root, code, start_date=start, end_date="2026-10-02")
    _assert_quote(first)
    assert ensured == [(_mc(code), "close", start, "2026-10-02")]
    assert calls[0][:3] == (root, "THS_HQ", (code, "close", "", LIVE_START, "2026-10-02"))
    assert first["rows"][-2:] == [
        {"date": LIVE_START, "close": 7.1}, {"date": "2026-10-02", "close": 7.2},
    ]
    if start < LIVE_START:
        assert first["rows"][:2] == [
            {"date": day, "close": forex.read_history()[day][code]}
            for day in ("2026-09-29", HISTORY_END)
        ]
    _assert_close_cache(root, code, start, "2026-10-02", first["rows"])
    monkeypatch.setattr(forex, "read_history", _blocked)
    second = service.get_quote(root, code, start_date=start, end_date="2026-10-02")
    assert second["rows"] == first["rows"]
    assert ensured == [(_mc(code), "close", start, "2026-10-02")] * 2
    assert len(calls) == 1


def test_incomplete_new_end_reuses_ten_minute_cache(tmp_path, monkeypatch):
    calls = _sdk(monkeypatch, dates=(LIVE_START,), values=(7.1,))
    kwargs = {"start_date": LIVE_START, "end_date": "2026-10-02"}
    first = service.get_quote(str(tmp_path), "USDCNY.IN", **kwargs)
    second = service.get_quote(str(tmp_path), "USDCNY.IN", **kwargs)
    _assert_quote(first)
    _assert_quote(second)
    assert second["rows"] == first["rows"] == [{"date": LIVE_START, "close": 7.1}]
    assert len(calls) == 1


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("start", [HISTORY_END, LIVE_START])
def test_sdk_failure_never_fills_new_dates_from_history(tmp_path, monkeypatch, code, start):
    calls = _sdk(monkeypatch, error="测试SDK故障")
    result = service.get_quote(str(tmp_path), code, start_date=start, end_date="2026-10-02")
    assert len(calls) == 1 and calls[0][2][3] == LIVE_START
    if start == HISTORY_END:
        _assert_quote(result)
        historical = {"date": HISTORY_END, "close": forex.read_history()[HISTORY_END][code]}
        assert result["rows"] == [historical]
        assert "测试SDK故障" in json.dumps(result.get("notes"), ensure_ascii=False)
        _assert_close_cache(tmp_path, code, HISTORY_END, HISTORY_END, [historical])
    else:
        assert result["ok"] is False, result
        assert "测试SDK故障" in json.dumps(result, ensure_ascii=False)
        assert not result.get("rows")
        assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("start", [HISTORY_END, LIVE_START])
def test_empty_sdk_response_caches_history_only_or_errors_without_history(tmp_path, monkeypatch, start):
    calls = _sdk(monkeypatch, dates=(), values=())
    result = service.get_quote(str(tmp_path), "HKDCNY.FX", start_date=start, end_date=LIVE_START)
    assert len(calls) == 1 and calls[0][2][3] == LIVE_START
    if start == HISTORY_END:
        _assert_quote(result)
        historical = {"date": HISTORY_END, "close": forex.read_history()[HISTORY_END]["HKDCNY.FX"]}
        assert result["rows"] == [historical]
        assert result["notes"]
        _assert_close_cache(tmp_path, "HKDCNY.FX", HISTORY_END, HISTORY_END, [historical])
    else:
        assert result["ok"] is False, result
        assert result.get("error") or result.get("notes")
        assert not result.get("rows")
        assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("fields", [None, [], ["close"], ["open", "volume", "total_market_cap"], ["unknown", "date", "pe"]])
@pytest.mark.parametrize("adjust", ["raw", "hfq", "qfq", "anything"])
@pytest.mark.parametrize("period", ["daily", "weekly", "monthly"])
def test_any_vars_and_adjust_normalize_to_raw_close_only(tmp_path, fields, adjust, period):
    result = service.get_quote(str(tmp_path), "HKDCNY.FX", vars=fields, adjust=adjust,
                               period=period, start_date="2018-06-15", end_date="2018-07-03")
    _assert_quote(result)
    daily = [{"date": day, "close": values["HKDCNY.FX"]}
             for day, values in forex.read_history().items() if "2018-06-15" <= day <= "2018-07-03"]
    expected = service._resample(daily, period)
    assert result["rows"] == [{"date": row["date"], "close": row["close"]} for row in expected]
    _assert_close_cache(tmp_path, "HKDCNY.FX", "2018-06-15", "2018-07-03", daily)


@pytest.mark.parametrize("period", ["daily", "weekly", "monthly"])
def test_explicit_csv_export_has_only_date_close(tmp_path, period):
    target = tmp_path / "exports" / f"{period}.csv"
    result = service.get_quote(str(tmp_path), "USDHKD.FX", vars=["open", "unknown"], adjust="hfq",
                               period=period, start_date="1996-06-25", end_date="1996-06-28",
                               export_path=str(target))
    _assert_quote(result)
    assert result["path"] == str(target) and "rows" not in result
    columns, rows = _read_csv(target)
    assert columns == ["date", "close"] and len(rows) == result["total_items"]
    assert rows[-1]["close"] != ""
    if period == "daily":
        assert [row["close"] for row in rows[:2]] == ["", ""]
    saved = _assert_close_cache(tmp_path, "USDHKD.FX", "1996-06-25", "1996-06-28")
    assert [row["value"] for row in saved["items"][:2]] == [None, None]


def test_automatic_csv_export_uses_history_start_and_close_only(tmp_path):
    result = service.get_quote(str(tmp_path), "USDHKD.FX", vars=["unknown"], adjust="anything",
                               start_date="all", end_date=HISTORY_END)
    _assert_quote(result)
    assert result["auto_exported"] is True and result["total_items"] == 11596
    target = Path(result["path"])
    assert target.is_relative_to(tmp_path)
    columns, rows = _read_csv(target)
    assert columns == ["date", "close"]
    assert rows[0] == {"date": HISTORY_START, "close": ""}
    assert rows[-1]["date"] == HISTORY_END
    assert sum(row["close"] == "" for row in rows) == 543
    saved = _assert_close_cache(tmp_path, "USDHKD.FX", HISTORY_START, HISTORY_END)
    assert sum(row["value"] is None for row in saved["items"]) == 543


def test_cli_batch_and_mcp_tool_read_same_offline_history(tmp_path):
    request = {"vars": ["unknown"], "adjust": "qfq", "start_date": "2018-06-18", "end_date": "2018-06-18"}
    batch = cli.dispatch({"tool": "get_quote_batch", "codes": list(CODES), **request})
    assert batch["ok"] is True and batch["succeeded"] == 3 and batch["failed"] == 0
    mcp = server.create_server()
    quote = mcp._tool_manager.get_tool("get_quote")
    assert quote.parameters["additionalProperties"] is False
    for code, result in zip(CODES, batch["results"]):
        _assert_quote(result)
        response = asyncio.run(quote.run({"code": code, **request}))
        _assert_quote(response)
        assert response["rows"] == result["rows"] == [
            {"date": "2018-06-18", "close": forex.read_history()["2018-06-18"][code]},
        ]
        assert code in quote.description
        _assert_close_cache(tmp_path, code, "2018-06-18", "2018-06-18", result["rows"])
    assert sorted(path.name for path in (tmp_path / "cache").iterdir()) == sorted(CODES)


@pytest.mark.parametrize("code", CODES)
def test_help_separates_raw_source_metadata_from_actual_runtime_cache(tmp_path, code):
    root = str(tmp_path)
    direct = market_help.get_market_data_help(root, tool="get_quote", code=code)
    assert direct["ok"] is True and direct["read_only"] is True, direct
    text = json.dumps(direct, ensure_ascii=False)
    assert HISTORY_START in text and HISTORY_END in text
    assert "close" in text and "CSV" in text
    null_count = 543 if code == "USDHKD.FX" else 0
    assert direct["source_data"] == {
        "kind": "ifind_raw_history", "path": str(forex.HISTORY_PATH),
        "date_range": {"start": HISTORY_START, "end": HISTORY_END},
        "nonempty_count": 11596 - null_count, "null_count": null_count,
        "first_valid_date": "1996-06-27" if code == "USDHKD.FX" else HISTORY_START,
    }
    assert direct["cache"] == []
    assert not (tmp_path / "cache").exists()
    arguments = {"tool": "get_quote", "code": code}
    cli_help = cli.dispatch({"tool": "get_market_data_help", "arguments": arguments})
    assert {key: value for key, value in cli_help.items() if key != "tool"} == direct
    mcp_help = server.create_server()._tool_manager.get_tool("get_market_data_help")
    assert asyncio.run(mcp_help.run(arguments)) == direct
    assert not (tmp_path / "cache").exists()

    quote = service.get_quote(root, code, start_date=HISTORY_START, end_date="1995-01-03")
    _assert_quote(quote)
    saved = _assert_close_cache(root, code, HISTORY_START, "1995-01-03", quote["rows"])
    before_help = (tmp_path / "cache" / code / "close.json").read_bytes()
    after = market_help.get_market_data_help(root, **arguments)
    assert after["source_data"] == direct["source_data"]
    assert after["cache"] == [{
        "domain": "quote", "module": "close", "meta": saved["meta"],
        "nonempty_count": 0 if code == "USDHKD.FX" else 3,
    }]
    assert "bundled_csv" not in json.dumps(after["cache"])
    assert "fx_history.csv" not in json.dumps(after["cache"])
    cli_after = cli.dispatch({"tool": "get_market_data_help", "arguments": arguments})
    assert {key: value for key, value in cli_after.items() if key != "tool"} == after
    assert asyncio.run(mcp_help.run(arguments)) == after
    assert (tmp_path / "cache" / code / "close.json").read_bytes() == before_help


@pytest.mark.parametrize("code", [*CODES, "USDCNY.FX", "USDHKD.IN", "HKDCNY.IN"])
def test_stock_parse_code_rejects_fx_and_in_suffixes(code):
    with pytest.raises(ValueError, match="不支持的市场后缀"):
        parse_code(code)


@pytest.mark.parametrize("code,market", [("600519.SH", "A"), ("200725.SZ", "A"), ("900901.SH", "A"),
                                         ("920002.BJ", "BJ"), ("00700.HK", "HK"), ("AAPL.US", "US")])
def test_stock_routing_keeps_existing_markets(code, market):
    assert parse_code(code).market == market


@pytest.mark.parametrize("code", CODES)
def test_financial_and_company_tools_reject_forex(tmp_path, code):
    financial = financial_service.get_financial_data(str(tmp_path), code, amount_basis="cumulative")
    company = company_service.get_company_profile(str(tmp_path), code, information_type="profile")
    for result in (financial, company):
        assert result["ok"] is False, result
        assert "不支持的市场后缀" in result["error"]
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("code", ["USDCNY.FX", "USDHKD.IN", "HKDCNY.IN", "EURCNY.FX"])
def test_quote_rejects_unapproved_forex_codes(tmp_path, code):
    result = service.get_quote(str(tmp_path), code, start_date=HISTORY_END, end_date=HISTORY_END)
    assert result["ok"] is False, result
    assert not (tmp_path / "cache").exists()


def test_export_tmp_package_reads_history_in_independent_subprocess(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("forex_test_export", REPO / "scripts" / "export.py")
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    target = tmp_path / "exported"
    exporter.export(target)
    asset = target / "market_data_mcp" / "data" / "fx_history.csv"
    assert asset.is_file()
    original_asset = Path(forex.HISTORY_PATH).read_bytes()
    assert asset.read_bytes() == original_asset
    asset_mtime = asset.stat().st_mtime_ns
    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(target), PYTHONNOUSERSITE="1", PYTHONUTF8="1",
                       MARKET_DATA_ROOT=str(tmp_path / "isolated-data"))
    probe = """
import json, socket
from pathlib import Path

def blocked(*args, **kwargs):
    raise AssertionError('network or SDK must not be used')

socket.socket.connect = blocked
from market_data_mcp import forex, service
from market_data_mcp.providers import ifind
ifind.request_ifind = blocked
ifind._sdk_call = blocked
root = Path.cwd()
assert Path(forex.__file__).resolve().is_relative_to(root / 'exported')
asset = Path(forex.HISTORY_PATH).resolve()
assert asset == root / 'exported' / 'market_data_mcp' / 'data' / 'fx_history.csv'
original_asset = asset.read_bytes()
asset_mtime = asset.stat().st_mtime_ns
history = forex.read_history()
assert len(history) == 11596
assert history['2018-06-18']['HKDCNY.FX'] == 0.8174
assert history['1995-01-01']['USDHKD.FX'] is None
result = service.get_quote(str(root / 'isolated-data'), 'HKDCNY.FX',
                           start_date='2018-06-18', end_date='2018-06-18')
assert result['ok'], result
assert result['rows'] == [{'date': '2018-06-18', 'close': 0.8174}]
data_root = root / 'isolated-data'
cache_file = data_root / 'cache' / 'HKDCNY.FX' / 'close.json'
assert cache_file.is_file()
assert sorted(path.name for path in cache_file.parent.iterdir()) == ['close.json']
saved = json.loads(cache_file.read_text(encoding='utf-8'))
assert saved['meta']['market'] == 'FX' and saved['meta']['field'] == 'close'
assert saved['meta']['date_range'] == {'start': '2018-06-18', 'end': '2018-06-18'}
assert saved['items'] == [{'date': '2018-06-18', 'value': 0.8174, 'source': 'ifind'}]
forex.read_history = blocked
again = service.get_quote(str(data_root), 'HKDCNY.FX',
                          start_date='2018-06-18', end_date='2018-06-18')
assert again['ok'] and again['rows'] == result['rows']
assert list(data_root.rglob('*.csv')) == []
assert list((root / 'exported' / 'cache').iterdir()) == []
assert asset.read_bytes() == original_asset and asset.stat().st_mtime_ns == asset_mtime
print(json.dumps({'history_rows': len(history), 'rows': result['rows'], 'cache_path': str(cache_file)}))
"""
    completed = subprocess.run([sys.executable, "-B", "-c", probe], cwd=tmp_path, env=environment,
                               capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["history_rows"] == 11596
    assert Path(payload["cache_path"]) == tmp_path / "isolated-data" / "cache" / "HKDCNY.FX" / "close.json"
    _assert_close_cache(tmp_path / "isolated-data", "HKDCNY.FX", "2018-06-18", "2018-06-18", payload["rows"])
    assert list((tmp_path / "isolated-data").rglob("*.csv")) == []
    assert asset.read_bytes() == original_asset and asset.stat().st_mtime_ns == asset_mtime
    assert Path(forex.HISTORY_PATH).read_bytes() == original_asset


def test_stale_end_refetch_bridges_from_cache_end_instead_of_request_start(tmp_path, monkeypatch):
    """终点不足补拉必须从缓存末日衔接（2026-11-03 用户版实测发现的跳段缺口）。"""
    calls = _sdk(monkeypatch, dates=("2026-10-08", "2026-10-09"), values=(7.79, 7.78))
    root = str(tmp_path)
    first = service.get_quote(root, "USDHKD.FX", start_date="2026-09-25", end_date="2026-09-30")
    _assert_quote(first)
    assert calls == []
    _assert_close_cache(root, "USDHKD.FX", "2026-09-25", "2026-09-30", first["rows"])
    monkeypatch.setattr(cache, "INCOMPLETE_RETRY_INTERVAL", timedelta(0))
    first_rows_dates = [row["date"] for row in first["rows"]]
    second = service.get_quote(root, "USDHKD.FX", start_date="2026-10-08", end_date="2026-10-09")
    _assert_quote(second)
    assert len(calls) == 1
    # 聚合器 fetch_start=缓存末日 2026-09-30；provider 实际请求 clamp 到 2026-10-01
    assert calls[0][2] == ("USDHKD.FX", "close", "", "2026-10-01", "2026-10-09")
    saved = _assert_close_cache(root, "USDHKD.FX", "2026-09-25", "2026-10-09",
                                dates=first_rows_dates + ["2026-10-08", "2026-10-09"],
                                rows=first["rows"] + [{"date": "2026-10-08", "close": 7.79},
                                                      {"date": "2026-10-09", "close": 7.78}])
    assert second["rows"] == [{"date": "2026-10-08", "close": 7.79}, {"date": "2026-10-09", "close": 7.78}]
    assert [row["date"] for row in saved["items"] if row["date"] >= "2026-10-01"] == ["2026-10-08", "2026-10-09"]
