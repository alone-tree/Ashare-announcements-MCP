"""中文展示与单位必须在共用输出层生效，旧缓存和金额原值不得改写。"""
import copy
import csv
import json

import pytest

from market_data_mcp import financial_items as labels, financial_service as fs, market_help, service
from market_data_mcp.server import _render_financial_markdown


@pytest.mark.parametrize("code,name", [
    ("LONG_RECE", "长期应收款"),
    ("TOTAL_OTHER_PAYABLE", "其他应付款合计"),
    ("TOTAL_OTHER_RECE", "其他应收款合计"),
    ("OTHER_RECE", "其他应收款"),
    ("BEGIN_CCE", "期初现金及现金等价物余额"),
    ("END_CASH", "现金的期末余额"),
    ("DEFER_TAX", "递延所得税"),
    ("ASSET_BALANCE", "资产平衡项目"),
    ("IA_LPE_AMORTIZE", "无形资产及长期待摊费用等摊销"),
    ("COMPENSATE_EXPENSE", "赔付支出"),
])
def test_official_labels_shared_by_mainland_markets(code, name):
    for market in ("A", "BJ"):
        assert labels.display_name(market, code, code) == name
        assert name in labels.match_names(market, code, code)
    assert labels.display_name("HK", code, "上游科目原名") == "上游科目原名"


def test_source_supplement_does_not_overwrite_or_duplicate_verified_names():
    assert not (labels.A_SHARE_SOURCE_LABELS.keys() & labels.A_SHARE_ITEM_NAMES.keys())
    names = [labels.display_name("A", code, code) for code in labels.A_SHARE_SOURCE_LABELS]
    assert len(names) == len(set(names))
    assert not (set(names) & {v[0] for v in labels.A_SHARE_ITEM_NAMES.values()})
    assert labels.display_name("A", "ABLE_OCI_OTHER", "ABLE_OCI_OTHER") == "ABLE_OCI_OTHER"


def test_same_name_raw_codes_preserve_nonempty_and_null_in_mcp_and_csv(tmp_path):
    rows = [{"item_code": code, "item_name": code, "statement": "income", "report_date": period,
             "amount": amount, "unit": "原币基础单位"}
            for period in ("2024-12-31", "2025-12-31")
            for code, amount in (("ASSET_IMPAIRMENT_INCOME", -100.5), ("ASSET_IMPAIRMENT_LOSS", None))]
    localized = service._localize_financial_rows(rows, "A")
    assert {r["item_name"] for r in localized} == {"资产减值损失（同名字段1）", "资产减值损失（同名字段2）"}
    md = _render_financial_markdown({"rows": localized, "statements": ["income"],
                                    "amount_basis": "cumulative"})["markdown"]
    assert "| 资产减值损失（同名字段1） | 原币基础单位 | -100.50 | -100.50 |" in md
    assert "| 资产减值损失（同名字段2） | 原币基础单位 |  |  |" in md
    path = tmp_path / "same-name.csv"
    service._export_financial_csv(str(path), localized)
    exported = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert len(exported) == len(rows)


@pytest.mark.parametrize("code,name,statement,value,unit", [
    ("BASIC_EPS", "BASIC_EPS", "income", 0.0123, "原币/股"),
    ("DILUTED_EPS", "DILUTED_EPS", "income", None, "原币/股"),
    ("DIVIDEND_PER_SHARE", "Dividend per share", "income", 0.5, "原币/股"),
    ("EPS_NATIVE", "基本每股盈利", "income", 0.3, "原币/股"),
    ("WEIGHTED_AVERAGE_SHARES", "Weighted average shares", "income", 12345, "股"),
    ("NATIVE_SHARES", "加权平均股数", "income", 12345, "股"),
    ("SHARE_CAPITAL", "SHARE_CAPITAL", "balance", 12345, "原币基础单位"),
    ("OTHER", "OTHER", "cash_flow", 0, "原币基础单位"),
    ("REPORT_CURRENCY", "币种", "meta", "CNY", "text"),
])
def test_units_do_not_scale_values_or_change_input(code, name, statement, value, unit):
    row = {"item_code": code, "item_name": name, "statement": statement, "amount": value}
    before = copy.deepcopy(row)
    result = service._localize_financial_rows([row], "A")[0]
    assert row == before
    assert result["unit"] == unit
    assert result["amount"] == value
    assert "item_code" not in result


def test_old_cache_chinese_query_csv_and_mcp_units(tmp_path, monkeypatch):
    records = [{"report_date": "2025-12-31", "metadata": {"CURRENCY": "CNY", "REPORT_TYPE": "年报"},
                "items": [{"item_code": c, "item_name": c, "amount": v, "source": "eastmoney"} for c, v in {
                    "BASIC_EPS": 0.123456, "DILUTED_EPS": 0.12, "OPERATE_INCOME": 100.125,
                    "NETCASH_OPERATE": 80, "FBNETCASH_OPERATE": 81, "FB_NETCASH_OPERATE": 82,
                    "NETCASH_OPERATENOTE": 83, "ABLE_OCI_OTHER": 9,
                }.items()]}]
    def fetch(root, mc, statement):
        if statement == "income":
            return records
        return [{"report_date": "2025-12-31", "metadata": records[0]["metadata"],
                 "items": [{"item_code": "LONG_RECE", "item_name": "LONG_RECE", "amount": 0,
                            "source": "eastmoney"}] if statement == "balance" else []}]
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", fetch)
    args = dict(periods=["2025-12-31"], statements=["income", "balance", "cash_flow"], items=["ALL_ITEMS"])
    result = fs.get_financial_data(str(tmp_path), "200725.SZ", "cumulative", **args)
    rows = result["rows"]
    cache = tmp_path / "cache/200725.SZ/financial_data/income.json"
    before = cache.read_bytes()
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", lambda *a: pytest.fail("旧缓存不得重取"))
    selected = fs.get_financial_data(str(tmp_path), "200725.SZ", "cumulative", periods=args["periods"],
                                    statements=["balance"], items=["长期应收款"])
    assert selected["rows"][0]["amount"] == 0
    assert cache.read_bytes() == before
    assert "BASIC_EPS" in {i["item_name"] for i in json.loads(before)["reports"][0]["versions"][0]["items"]}
    eps = next(r for r in rows if r["item_name"] == "基本每股收益")
    assert eps["unit"] == "原币/股" and eps["amount"] == 0.123456
    assert any("ABLE_OCI_OTHER" in note for note in result["notes"])
    path = tmp_path / "out.csv"
    fs.get_financial_data(str(tmp_path), "200725.SZ", "cumulative", **args, export_path=str(path))
    exported = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    csv_eps = next(r for r in exported if r["item_name"] == "基本每股收益")
    assert csv_eps["unit"] == "原币/股" and float(csv_eps["amount"]) == eps["amount"]
    md = _render_financial_markdown(copy.deepcopy(result))["markdown"]
    for name, value in [("经营活动产生的现金流量净额", 80),
                        ("经营活动产生的现金流量净额（补充资料）", 81),
                        ("经营活动产生的现金流量净额（补充资料备用字段）", 82),
                        ("经营活动产生的现金流量净额（补充资料附注）", 83)]:
        assert f"| {name} | 原币基础单位 | {value:.2f} |" in md
    assert "| 基本每股收益 | 原币/股 | 0.12 |" in md


@pytest.mark.parametrize("versions", [False, True])
def test_ratio_and_text_units_in_both_mcp_views(versions):
    rows = [{"report_date": "2025-12-31", "statement": "income", "item_name": "毛利率",
             "amount": 0.25, "unit": "ratio"},
            {"report_date": "2025-12-31", "statement": "meta", "item_name": "币种",
             "amount": "CNY", "unit": "text"}]
    result = {"rows": rows, "statements": ["income", "meta"], "amount_basis": "cumulative",
              "include_versions": versions}
    md = _render_financial_markdown(result)["markdown"]
    assert "ratio | 25.00%" in md
    assert "text | CNY" in md
    assert market_help.get_market_data_help(".", topic="items")["financial_units"]["per_share"] == "原币/股"
