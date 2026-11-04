"""独立 Excel 运行层契约；真实 COM 验收记录见 Excel 取数实测报告。"""

import importlib.util
import shutil
import subprocess

import pytest
from openpyxl import load_workbook

from market_data_mcp import ifind_excel


def test_template_contains_only_empty_data_sheet():
    with ifind_excel.WORKBOOK.open("rb") as stream:
        book = load_workbook(stream, read_only=True)
        assert book.sheetnames == ["data"]
        assert all(cell.value is None for row in book.active for cell in row)
        book.close()


def test_copied_module_locates_its_own_workbook(tmp_path, monkeypatch):
    target = tmp_path / "copy" / "ifind_excel.py"
    target.parent.mkdir()
    shutil.copy2(ifind_excel.__file__, target)
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("excel_runtime_copy", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.WORKBOOK == target.parent / "data" / "ifind_workspace.xlsx"
    assert module.WORKBOOK != ifind_excel.WORKBOOK


def test_calendar_dates_and_raw_empty_zero_are_preserved(monkeypatch):
    written = []

    def fetch(formulas, **kwargs):
        written.extend(formulas)
        return {"values": [10, None, 0, 12]}

    monkeypatch.setattr(ifind_excel, "fetch_formulas", fetch)
    result = ifind_excel.get_market_value("300502.SZ", "2026-10-30", "2026-11-02")
    assert [row["date"] for row in result["rows"]] == [
        "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"
    ]
    assert [row["value"] for row in result["rows"]] == [10, None, 0, 12]
    assert len(written) == 4
    assert all(row["date"] in formula for row, formula in zip(result["rows"], written))
    assert all('"ths_mv_back_test_stock","300502.SZ"' in formula for formula in written)


def test_invalid_input_never_launches_excel(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("非法输入不应启动 Excel 工作进程")

    monkeypatch.setattr(ifind_excel, "_call", forbidden)
    with pytest.raises(ValueError):
        ifind_excel.get_market_value("300502.SZ", "2026-11-03", "2020-01-01")
    with pytest.raises(ValueError):
        ifind_excel.fetch_formulas([])
    with pytest.raises(ValueError):
        ifind_excel.fetch_formulas(["=SUM(1,2)"])


def test_whole_worker_deadline_becomes_timeout(monkeypatch):
    def blocked(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(ifind_excel.subprocess, "run", blocked)
    with pytest.raises(TimeoutError, match="Excel 保持原状"):
        ifind_excel.status(timeout=0.1)
