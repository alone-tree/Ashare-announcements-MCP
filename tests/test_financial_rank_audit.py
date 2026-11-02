"""主营排名覆盖、年报补充及IPO原式的业务回归，不联网。"""
from copy import deepcopy

import pytest

from market_data_mcp import company_ifind_service, company_service, data_store, financial_service as fs
from market_data_mcp.providers import company_ifind as ci
from market_data_mcp.routing import parse_code


@pytest.fixture
def income(monkeypatch):
    def fetch(root, mc, statement):
        return [{"report_date": period, "metadata": {"CURRENCY": "CNY", "NOTICE_DATE": "东财公告日"},
                 "items": [{"item_code": "OPERATE_INCOME", "item_name": "营业收入", "amount": 100,
                            "source": "eastmoney"}]} for period in ("2025-12-31", "2025-06-30")]
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", fetch)
    monkeypatch.setattr(ci, "latest_report", lambda *a: "2025-12-31")


@pytest.mark.parametrize("value", [0, 100, True, False, 5.0, "9", None])
def test_top_n_rejects_invalid_before_fetch(tmp_path, monkeypatch, value):
    monkeypatch.setattr(fs.financial_statements, "fetch_batch", lambda *a: pytest.fail("参数错误不得请求"))
    result = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", top_n=value)
    assert not result["ok"] and "top_n" in result["error"]


def test_provider_rank_upper_bound_zero_and_blank_termination(monkeypatch):
    calls = []
    def basic(root, mc, fields, parameters):
        rank = int(parameters.split(",")[-1])
        calls.append(rank)
        if rank <= 9:
            return {"name": f"产品{rank}", "income": 0 if rank == 1 else rank, "gross_profit": -1}
        return {"name": "", "income": None, "gross_profit": ""}
    monkeypatch.setattr(ci, "basic", basic)
    rows = ci.segments(".", parse_code("002586.SZ"), "2025-12-31", "product", 99)
    assert calls == list(range(1, 11))
    assert rows[0]["income"] == 0 and rows[0]["gross_profit"] == -1
    assert rows[-1]["rank"] == 10  # 缓存可据此识别已到末项，输出层不展示此空行。


@pytest.mark.parametrize("limit", [1, 99])
def test_provider_supports_top_n_boundaries(monkeypatch, limit):
    calls = []
    monkeypatch.setattr(ci, "basic", lambda root, mc, fields, p: calls.append(p) or
                        {"name": "有值", "income": 1, "gross_profit": 0})
    rows = ci.segments(".", parse_code("002586.SZ"), "2025-12-31", "product", limit)
    assert len(rows) == len(calls) == limit


def test_rank_cache_grows_shrinks_and_reuses_end(tmp_path, monkeypatch, income):
    calls = []
    def segments(root, mc, period, dimension, top_n=5, start_rank=1):
        calls.append((start_rank, top_n))
        return [{"rank": n, "name": f"产品{n}" if n <= 9 else "",
                 "income": n if n <= 9 else "", "gross_profit": 0 if n <= 9 else ""}
                for n in range(start_rank, min(top_n, 10) + 1)]
    monkeypatch.setattr(ci, "segments", segments)
    args = dict(periods=["2025-12-31"], statements=["segments"], items=["income by product"])
    first = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args)
    assert len(first["segments"]) == 5
    nine = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args, top_n=9)
    assert len(nine["segments"]) == 9 and calls == [(1, 5), (6, 9)]
    before = deepcopy(data_store.read(str(tmp_path), "002586.SZ", fs.DOMAIN, "segments_product"))
    small = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args, top_n=1)
    assert len(small["segments"]) == 1
    assert data_store.read(str(tmp_path), "002586.SZ", fs.DOMAIN, "segments_product") == before
    for _ in range(2):
        all_rows = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args, top_n=99)
        assert len(all_rows["segments"]) == 9
    assert calls == [(1, 5), (6, 9), (10, 99)]


def test_forced_smaller_rank_range_does_not_refresh_unrequested_tail(tmp_path, monkeypatch, income):
    calls = []
    def segments(root, mc, period, dimension, top_n=5, start_rank=1):
        calls.append((start_rank, top_n))
        return [{"rank": n, "name": f"产品{n}", "income": len(calls), "gross_profit": 0}
                for n in range(start_rank, top_n + 1)]
    monkeypatch.setattr(ci, "segments", segments)
    args = dict(periods=["2025-12-31"], statements=["segments"], items=["income by product"])
    fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args, top_n=9)
    fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args, top_n=3, force_refresh=True)
    result = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args, top_n=9)
    assert calls == [(1, 9), (1, 3), (4, 9)]
    assert [r["income"] for r in result["segments"]] == [2] * 3 + [3] * 6


def test_old_rank_cache_is_only_five_and_failure_does_not_advance(tmp_path, monkeypatch, income):
    payload = {"meta": {"schema_version": 2, "source": "ifind"}, "periods": {"2025-12-31": {
        "checked_at": fs._now(), "rows": [{"rank": n, "name": f"原{n}", "income": n, "gross_profit": 0}
                                         for n in range(1, 6)]}}}
    data_store.write(str(tmp_path), "002586.SZ", fs.DOMAIN, "segments_product", payload)
    calls = []
    def fail(*args):
        calls.append(args[-2:])
        raise RuntimeError("扩容失败")
    monkeypatch.setattr(ci, "segments", fail)
    result = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", periods=["2025-12-31"],
                                   statements=["segments"], items=["income by product"], top_n=9)
    assert calls == [(9, 6)]
    assert result["ok"] and result["status"] == "partial_success" and result["stale"]
    assert len(result["segments"]) == 5
    assert data_store.read(str(tmp_path), "002586.SZ", fs.DOMAIN, "segments_product") == payload


def test_default_segment_rows_follow_n_and_keep_concentration_totals(tmp_path, monkeypatch, income):
    def segments(root, mc, period, dimension, top_n=5, start_rank=1):
        if dimension in ("customer", "supplier"):
            return [{"rank": n, "name": f"明细{n}", "ratio": 0} for n in range(1, 6)] + [{"rank": "top5", "ratio": 0.5}]
        return [{"rank": n, "name": f"项目{n}", "income": 0, "gross_profit": 0}
                for n in range(start_rank, top_n + 1)]
    monkeypatch.setattr(ci, "segments", segments)
    result = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", periods=["2025-12-31"],
                                   statements=["segments"], top_n=2)
    product = [r for r in result["segments"] if r["dimension"] == "income by product"]
    assert len(product) == 2 and all("gross_profit" not in r for r in product)
    customers = [r for r in result["segments"] if r["dimension"] == "income by customer"]
    assert len(customers) == 6 and customers[-1]["rank"] == "top5"


@pytest.mark.parametrize("code", ["002586.SZ", "900901.SH", "200725.SZ", "920002.BJ"])
def test_annual_info_cached_separately_and_source_preserved(tmp_path, monkeypatch, income, code):
    calls = []
    def report_info(root, mc, period):
        calls.append(period)
        return {"AUDITOR": "示例事务所", "OPINION_TYPE": "无法表示意见",
                "INTERNAL_CONTROL_OPINION": "带强调事项段的无保留意见", "NOTICE_DATE": "20260421"}
    monkeypatch.setattr(ci, "annual_report_info", report_info, raising=False)
    args = dict(periods=["2025-12-31"], statements=["meta"], items=["公告日", "审计单位", "审计意见", "内控审计意见"])
    for _ in range(2):
        result = fs.get_financial_data(str(tmp_path), code, "cumulative", **args)
        values = {r["item_name"]: r for r in result["rows"]}
        assert values["审计单位"]["amount"] == "示例事务所"
        assert values["审计意见"]["amount"] != values["内控审计意见"]["amount"]
        assert values["审计单位"]["source"] == "ifind"
        assert values["公告日"]["amount"] == "东财公告日" and values["公告日"]["source"] == "eastmoney"
        assert result["source"] == "eastmoney,ifind"
    assert calls == ["2025-12-31"]
    raw = data_store.read(str(tmp_path), code, fs.DOMAIN, "income")
    assert "AUDITOR" not in raw["reports"][0]["versions"][0]["metadata"]


def test_annual_info_failure_keeps_old_data_and_midyear_skips(tmp_path, monkeypatch, income):
    monkeypatch.setattr(ci, "annual_report_info", lambda *a: {"AUDITOR": "原值", "OPINION_TYPE": "原意见"}, raising=False)
    args = dict(periods=["2025-12-31"], statements=["meta"], items=["审计单位"])
    fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args)
    before = deepcopy(data_store.read(str(tmp_path), "002586.SZ", fs.DOMAIN, "report_info_ifind"))
    monkeypatch.setattr(ci, "annual_report_info", lambda *a: (_ for _ in ()).throw(RuntimeError("失败")))
    stale = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args, force_refresh=True)
    assert stale["ok"] and stale["stale"] and stale["status"] == "partial_success"
    assert stale["rows"][0]["amount"] == "原值"
    assert data_store.read(str(tmp_path), "002586.SZ", fs.DOMAIN, "report_info_ifind") == before
    monkeypatch.setattr(ci, "annual_report_info", lambda *a: pytest.fail("中报不调用年报补充"))
    midyear = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", periods=["2025-06-30"],
                                   statements=["meta"], items=["审计单位"])
    assert midyear["rows"][0]["amount"] is None
    fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", periods=["2025-12-31"],
                          statements=["income"], items=["营业收入"])


def test_report_info_write_failure_preserves_successful_cache(tmp_path, monkeypatch, income):
    monkeypatch.setattr(ci, "annual_report_info", lambda *a: {"AUDITOR": "原值"})
    args = dict(periods=["2025-12-31"], statements=["meta"], items=["审计单位"])
    fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args)
    before = deepcopy(data_store.read(str(tmp_path), "002586.SZ", fs.DOMAIN, "report_info_ifind"))
    original_write = data_store.write
    def write(root, code, domain, module, value):
        if module == "report_info_ifind":
            raise OSError("写入失败")
        return original_write(root, code, domain, module, value)
    monkeypatch.setattr(data_store, "write", write)
    monkeypatch.setattr(ci, "annual_report_info", lambda *a: {"AUDITOR": "新值"})
    result = fs.get_financial_data(str(tmp_path), "002586.SZ", "cumulative", **args, force_refresh=True)
    assert result["stale"] and result["rows"][0]["amount"] == "原值"
    assert data_store.read(str(tmp_path), "002586.SZ", fs.DOMAIN, "report_info_ifind") == before


@pytest.mark.parametrize("fee,expected", [(None, None), ("", ""), (0, 0), ("--", "--"), ("12.34", 123400)])
def test_ipo_fee_zero_empty_and_placeholder(monkeypatch, fee, expected):
    monkeypatch.setattr(ci, "basic", lambda *a: {"发行费用": fee, "发行后市净率": None})
    assert ci.section(".", parse_code("002586.SZ"), "ipo")["发行费用"] == expected


def test_ipo_formulas_normalize_fee_and_upgrade_old_cache(tmp_path, monkeypatch):
    calls = []
    def basic(root, mc, fields, parameters=""):
        calls.append((fields, parameters))
        assert fields["发行后市净率"] == "ths_ipo_pb_stock" and fields["发行费用"] == "ipo_fee"
        assert parameters.get("发行费用") == "10000"
        return {"发行后市净率": 2.84, "发行费用": 3734.3}
    monkeypatch.setattr(ci, "basic", basic)
    value = ci.section(str(tmp_path), parse_code("002586.SZ"), "ipo")
    assert value["发行后市净率"] == 2.84 and value["发行费用"] == 37343000
    monkeypatch.setattr(ci, "section", lambda *a, **k: value)
    data_store.write(str(tmp_path), "002586.SZ", "company_data", "ipo", {
        "meta": {"schema_version": 2, "source": "ifind"}, "scopes": {}})
    first = company_service.get_company_profile(str(tmp_path), "002586.SZ", "ipo")
    assert first["units"]["发行费用"] == "原币基础单位"
    payload = data_store.read(str(tmp_path), "002586.SZ", "company_data", "ipo")
    for entry in payload["scopes"].values():
        entry["data"] = {"发行价格": 19}
    data_store.write(str(tmp_path), "002586.SZ", "company_data", "ipo", payload)
    second = company_service.get_company_profile(str(tmp_path), "002586.SZ", "ipo")
    assert second["data"]["发行费用"] == 37343000
    monkeypatch.setattr(ci, "section", lambda *a, **k: pytest.fail("已有空值也应复用"))
    company_service.get_company_profile(str(tmp_path), "002586.SZ", "ipo")
