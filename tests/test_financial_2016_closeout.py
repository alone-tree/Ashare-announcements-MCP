"""已核实中文科目、综合收益口径、境外及内控审计来源的业务回归。"""
from copy import deepcopy
import csv

import pytest

from market_data_mcp import data_store, financial_items, financial_service as fs, market_help, service
from market_data_mcp.providers import company_ifind as ci
from market_data_mcp.routing import parse_code
from market_data_mcp.server import _render_financial_markdown


def _reports(statement, period="2022-12-31"):
    return [{"report_date": period, "metadata": {
        "CURRENCY": "CNY", "NOTICE_DATE": "2023-03-31", "OPINION_TYPE": "财报审计原意见",
        **({"OSOPINION_TYPE": "境外审计原意见"} if statement == "balance" else {}),
    }, "items": [{"item_code": "TOTAL_ASSETS" if statement == "balance" else "OPERATE_INCOME",
                  "item_name": "TOTAL_ASSETS" if statement == "balance" else "OPERATE_INCOME",
                  "amount": 100, "source": "eastmoney"}]}]


@pytest.mark.parametrize("code", ["600030.SH", "900901.SH", "200725.SZ", "920002.BJ"])
@pytest.mark.parametrize("statements", [["meta"], ["balance", "meta"], ["balance", "income", "cash_flow", "meta"]])
def test_control_opinion_never_uses_overseas_even_when_request_changes(tmp_path, monkeypatch, code, statements):
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", lambda root, mc, s: _reports(s))
    monkeypatch.setattr(ci, "annual_report_info", lambda *a: {
        "INTERNAL_CONTROL_OPINION": "内控审计实际意见", "AUDITOR": "示例事务所"})
    result = fs.get_financial_data(str(tmp_path), code, "cumulative", periods=["2022-12-31"],
                                   statements=statements, items=["ALL_ITEMS"])
    controls = [r for r in result["rows"] if r["item_name"] == "内控审计意见"]
    assert len(controls) == 1
    assert (controls[0]["amount"], controls[0]["source"]) == ("内控审计实际意见", "ifind")
    assert controls[0]["report_metadata"]["INTERNAL_CONTROL_OPINION"] == "内控审计实际意见"
    if "balance" in statements:
        overseas = next(r for r in result["rows"] if r["item_name"] == "境外审计意见")
        assert (overseas["amount"], overseas["source"]) == ("境外审计原意见", "eastmoney")
        raw = data_store.read(str(tmp_path), code, fs.DOMAIN, "balance", "eastmoney")
        metadata = raw["reports"][0]["versions"][0]["metadata"]
        assert metadata["OSOPINION_TYPE"] == "境外审计原意见"
        assert "INTERNAL_CONTROL_OPINION" not in metadata


@pytest.mark.parametrize("source", ["ifind", "eastmoney"])
def test_legacy_control_key_only_reused_from_ifind_cache(tmp_path, monkeypatch, source):
    code, period = "600030.SH", "2022-12-31"
    payload = {"meta": {"schema_version": 2, "source": source},
               "periods": {period: {"checked_at": fs._now(), "data": {"OSOPINION_TYPE": "旧内控意见"}}}}
    data_store.write(str(tmp_path), code, fs.DOMAIN, "report_info_ifind", payload)
    before = data_store.path(str(tmp_path), code, fs.DOMAIN, "report_info_ifind").read_bytes()
    calls = []
    def fetch(*a):
        calls.append(True)
        return {"INTERNAL_CONTROL_OPINION": "新内控意见"}
    monkeypatch.setattr(ci, "annual_report_info", fetch)
    raw = {"OSOPINION_TYPE": "真实境外意见"}
    meta, origins, failures = fs._supplement_report_info(str(tmp_path), parse_code(code), period, raw,
                                                       {"INTERNAL_CONTROL_OPINION"}, False)
    assert meta["OSOPINION_TYPE"] == raw["OSOPINION_TYPE"]
    assert raw == {"OSOPINION_TYPE": "真实境外意见"}
    assert origins == {"INTERNAL_CONTROL_OPINION": "ifind"} and failures == []
    if source == "ifind":
        assert meta["INTERNAL_CONTROL_OPINION"] == "旧内控意见" and calls == []
        assert data_store.path(str(tmp_path), code, fs.DOMAIN, "report_info_ifind").read_bytes() == before
    else:
        assert meta["INTERNAL_CONTROL_OPINION"] == "新内控意见" and calls == [True]


def test_stale_legacy_control_and_empty_control_do_not_fall_back_to_overseas(tmp_path, monkeypatch):
    code, period = "600030.SH", "2022-12-31"
    old = {"meta": {"schema_version": 2, "source": "ifind"}, "periods": {
        period: {"checked_at": fs._now(), "data": {"OSOPINION_TYPE": "旧内控意见"}}}}
    data_store.write(str(tmp_path), code, fs.DOMAIN, "report_info_ifind", old)
    monkeypatch.setattr(ci, "annual_report_info", lambda *a: (_ for _ in ()).throw(RuntimeError("取数失败")))
    raw = {"OSOPINION_TYPE": "境外意见"}
    meta, origins, failed = fs._supplement_report_info(str(tmp_path), parse_code(code), period, raw,
                                                      {"INTERNAL_CONTROL_OPINION"}, True)
    assert meta["INTERNAL_CONTROL_OPINION"] == "旧内控意见" and failed[0]["stale"]
    assert data_store.read(str(tmp_path), code, fs.DOMAIN, "report_info_ifind") == old
    monkeypatch.setattr(ci, "annual_report_info", lambda *a: {"INTERNAL_CONTROL_OPINION": None})
    empty, _, _ = fs._supplement_report_info(str(tmp_path), parse_code(code), period, raw,
                                            {"INTERNAL_CONTROL_OPINION"}, True)
    assert empty["INTERNAL_CONTROL_OPINION"] is None and empty["OSOPINION_TYPE"] == "境外意见"


def test_overseas_only_midyear_and_ordinary_amount_do_not_request_ifind(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "annual_report_info", lambda *a: pytest.fail("不应请求年报补充"))
    raw = {"OSOPINION_TYPE": "境外意见"}
    for period, requested in [("2022-12-31", {"OSOPINION_TYPE"}), ("2022-06-30", {"INTERNAL_CONTROL_OPINION"})]:
        meta, _, _ = fs._supplement_report_info(str(tmp_path), parse_code("600030.SH"), period, raw, requested, False)
        assert "INTERNAL_CONTROL_OPINION" not in meta
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", lambda root, mc, s: _reports(s))
    result = fs.get_financial_data(str(tmp_path), "600030.SH", "cumulative", periods=["2022-12-31"],
                                   statements=["balance"], items=["资产总计"])
    md = _render_financial_markdown(deepcopy(result))["markdown"]
    assert "| 境外审计意见 | 境外审计原意见 |" in md
    assert "| 内控审计意见 |  |" in md


def test_explicit_overseas_item_reads_balance_metadata_without_ifind(tmp_path, monkeypatch):
    calls = []
    def fetch(root, mc, statement):
        calls.append(statement)
        return _reports(statement)
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", fetch)
    monkeypatch.setattr(ci, "annual_report_info", lambda *a: pytest.fail("境外意见不得用内控补充"))
    result = fs.get_financial_data(str(tmp_path), "600030.SH", "cumulative", periods=["2022-12-31"],
                                   statements=["meta"], items=["境外审计意见"])
    assert calls == ["balance"] and result["status"] == "success"
    assert [(r["item_name"], r["amount"], r["source"]) for r in result["rows"]] == [
        ("境外审计意见", "境外审计原意见", "eastmoney")]
    help_result = market_help.get_market_data_help(".", topic="items")
    assert "境外审计意见" in help_result["meta_items"]
    assert "境外审计意见" not in help_result["default_items"]["meta"]


def test_provider_keeps_exact_existing_formula_but_uses_separate_key(monkeypatch):
    def basic(root, mc, fields, parameters):
        assert fields["INTERNAL_CONTROL_OPINION"] == "ths_ica_opinion_type_stock"
        assert "OSOPINION_TYPE" not in fields
        assert parameters["INTERNAL_CONTROL_OPINION"] == "20221231"
        assert parameters["OPINION_TYPE"] == "20221231,100"
        return {"INTERNAL_CONTROL_OPINION": "实际内控意见"}
    monkeypatch.setattr(ci, "basic", basic)
    assert ci.annual_report_info(".", parse_code("600030.SH"), "2022-12-31")["INTERNAL_CONTROL_OPINION"] == "实际内控意见"


@pytest.mark.parametrize("code,name", [
    ("ACCEPT_DEPOSIT_INTERBANK", "吸收存款及同业存放"),
    ("DIV_HOLDSALE_ASSET", "划分为持有待售的资产"),
    ("DIV_HOLDSALE_LIAB", "划分为持有待售的负债"),
    ("ASSETMANAGE_FEE_NI", "资产管理业务手续费净收入（旧字段）"),
    ("BROKER_FEE_NI", "经纪业务手续费净收入（旧字段）"),
    ("INVESTBANK_FEE_NI", "投资银行业务手续费净收入（旧字段）"),
])
def test_six_verified_names_apply_without_company_or_year_restrictions(code, name):
    for market in ("A", "BJ"):
        assert financial_items.display_name(market, code, code) == name
        assert name in financial_items.match_names(market, code, code)


def test_comprehensive_income_notes_and_distinct_legacy_fees_survive_exports(tmp_path, monkeypatch):
    values = {"ABLE_OCI_OTHER": 86143000000.0, "UNABLE_OCI_OTHER": -34412000000.0,
              "OCI_OTHER": 59000000.0, "RIGHTLAW_ABLE_OCI": 59000000.0,
              "ASSETMANAGE_FEE_NI": 5833853736.42, "ASSET_MANAGE_NI": 5833853736.42}
    records = _reports("income", "2016-09-30")
    records[0]["items"] = [{"item_code": c, "item_name": c, "amount": v, "source": "eastmoney"}
                           for c, v in values.items()]
    before = deepcopy(records)
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", lambda *a: records)
    args = dict(periods=["2016-09-30"], statements=["income"], items=["ALL_ITEMS"])
    result = fs.get_financial_data(str(tmp_path), "601318.SH", "cumulative", **args)
    assert records == before and len(result["rows"]) == len(values)
    for row in result["rows"]:
        code = next(c for c in values if financial_items.display_name("A", c, c) == row["item_name"])
        assert row["amount"] == values[code]
        if code in financial_items.A_SHARE_ITEM_NOTES:
            assert row["note"] == financial_items.item_note("A", code)
            assert row["note"] in result["notes"]
    md = _render_financial_markdown(deepcopy(result))["markdown"]
    assert "东财汇总项" in md and "旧字段" in md
    path = tmp_path / "income.csv"
    service._export_financial_csv(str(path), result["rows"])
    exported = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert len(exported) == len(values)
    assert all(r["note"] for r in exported if "东财" in r["item_name"] or "旧字段" in r["item_name"])
    assert {float(r["amount"]) for r in exported} == set(values.values())
