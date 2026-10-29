"""独立批次原子写入：短暂占用恢复、持久失败与原文件保护。"""
import json
import time

import pytest

from market_data_mcp import data_store


def denied_error():
    error = PermissionError("目标文件暂时被占用")
    error.winerror = 5
    return error


@pytest.mark.parametrize("code,domain,module", [
    ("600106.SH", "financial_data", "segments_product"),
    ("600106.SH", "company_data", "dividends"),
    ("00700.HK", "financial_data", "income"),
])
def test_replace_recovers_from_short_access_denial(tmp_path, monkeypatch, code, domain, module):
    root = str(tmp_path)
    data_store.write(root, code, domain, module, {"value": "old"})
    target = data_store.path(root, code, domain, module)
    original = target.read_bytes()
    replace = data_store.os.replace
    attempts, waits = [], []

    def busy_then_available(source, destination):
        attempts.append((source, destination))
        if len(attempts) <= 3:
            assert target.read_bytes() == original
            raise denied_error()
        replace(source, destination)

    monkeypatch.setattr(data_store.os, "replace", busy_then_available)
    monkeypatch.setattr(time, "sleep", waits.append)
    data_store.write(root, code, domain, module, {"value": "new"})
    assert len(attempts) == 4 and len({str(source) for source, _ in attempts}) == 1
    assert waits == [0.05, 0.10, 0.20]
    assert json.loads(target.read_text(encoding="utf-8")) == {"value": "new"}
    assert not list(target.parent.glob("*.tmp"))


def test_persistent_access_denial_preserves_original_and_error(tmp_path, monkeypatch):
    root = str(tmp_path)
    data_store.write(root, "600106.SH", "company_data", "dividends", {"value": "old"})
    target = data_store.path(root, "600106.SH", "company_data", "dividends")
    original = target.read_bytes()
    error = denied_error()
    attempts, waits = [], []

    def denied(source, destination):
        attempts.append(source)
        raise error

    monkeypatch.setattr(data_store.os, "replace", denied)
    monkeypatch.setattr(time, "sleep", waits.append)
    with pytest.raises(PermissionError) as raised:
        data_store.write(root, "600106.SH", "company_data", "dividends", {"value": "new"})
    assert raised.value is error
    assert len(attempts) == 4 and waits == [0.05, 0.10, 0.20]
    assert target.read_bytes() == original
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.parametrize("winerror", [None, 32])
def test_other_write_errors_are_not_retried(tmp_path, monkeypatch, winerror):
    error = OSError("其他写入错误")
    if winerror is not None:
        error.winerror = winerror
    attempts = []

    def failed(source, destination):
        attempts.append(source)
        raise error

    monkeypatch.setattr(data_store.os, "replace", failed)
    monkeypatch.setattr(time, "sleep", lambda _: pytest.fail("不应重试其他错误"))
    with pytest.raises(OSError) as raised:
        data_store.write(str(tmp_path), "600106.SH", "financial_data", "income", {"value": 1})
    assert raised.value is error and len(attempts) == 1
    assert not list(tmp_path.rglob("*.tmp"))


def test_serialization_failure_does_not_replace_original(tmp_path, monkeypatch):
    root = str(tmp_path)
    data_store.write(root, "600106.SH", "company_data", "dividends", {"value": "old"})
    target = data_store.path(root, "600106.SH", "company_data", "dividends")
    original = target.read_bytes()
    monkeypatch.setattr(data_store.os, "replace", lambda *a: pytest.fail("序列化失败不应替换"))
    monkeypatch.setattr(time, "sleep", lambda _: pytest.fail("序列化失败不应重试"))
    with pytest.raises(ValueError):
        data_store.write(root, "600106.SH", "company_data", "dividends", {"value": float("nan")})
    assert target.read_bytes() == original
    assert not list(target.parent.glob("*.tmp"))
