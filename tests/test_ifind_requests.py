from types import SimpleNamespace

import pandas as pd
import pytest

from market_data_mcp.providers import ifind


@pytest.fixture
def session(monkeypatch):
    ifind._LOGIN_STATE.clear()
    ifind._LOGIN_STATE["done"] = False
    monkeypatch.setattr(ifind, "_load_accounts", lambda root: [("account_a", "secret_a"), ("account_b", "secret_b")])
    monkeypatch.setattr(ifind.ths, "THS_iFinDLogout", lambda: 0)
    monkeypatch.setattr(ifind.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(ifind.audit, "log_request", lambda *args, **kwargs: None)
    active = []
    monkeypatch.setattr(ifind.ths, "THS_iFinDLogin", lambda account, password: active.append(account) or 0)
    yield active
    ifind._LOGIN_STATE.clear()
    ifind._LOGIN_STATE["done"] = False


def test_data_failure_switches_account_and_reuses_success(monkeypatch, session):
    calls = []
    def fetch(*args):
        calls.append(args)
        return SimpleNamespace(errorcode=-7 if session[-1] == "account_a" else 0,
                               errmsg="permission", data=pd.DataFrame({"field": [None]}))
    monkeypatch.setattr(ifind.ths, "THS_BD", fetch)
    result = ifind.request_ifind("root", "THS_BD", "code", "field", "param", required_columns=["field"])
    assert result.errorcode == 0
    assert session == ["account_a", "account_b"]
    assert calls[0] == calls[1]
    ifind.request_ifind("root", "THS_BD", "code", "field", "param")
    assert session == ["account_a", "account_b"]


def test_normal_empty_does_not_switch(monkeypatch, session):
    monkeypatch.setattr(ifind.ths, "THS_BD", lambda *args: SimpleNamespace(errorcode=0, data=None))
    assert ifind.request_ifind("root", "THS_BD", "code", "field", "param").errorcode == 0
    assert len(session) == 1


def test_errors_bounded_and_redacted(monkeypatch, session):
    calls = []
    def fetch(*args):
        calls.append(1)
        return SimpleNamespace(errorcode=-205, errmsg="request data error account_a secret_a", data=None)
    monkeypatch.setattr(ifind.ths, "THS_BD", fetch)
    result = ifind.request_ifind("root", "THS_BD", "code", "field", "param")
    assert len(calls) == 8
    assert result.errorcode != 0
    assert "account_a" not in result.errmsg and "secret_a" not in result.errmsg


def test_lost_session_repairs_once(monkeypatch, session):
    calls = []
    def fetch(*args):
        calls.append(1)
        return SimpleNamespace(errorcode=-1 if len(calls) == 1 else 0,
                               errmsg="you have not done login operation", data=None)
    monkeypatch.setattr(ifind.ths, "THS_BD", fetch)
    assert ifind.request_ifind("root", "THS_BD").errorcode == 0
    assert session == ["account_a", "account_a"]
