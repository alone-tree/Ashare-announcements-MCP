"""独立 Excel 运行层契约；真实 COM 验收记录见 Excel 取数实测报告。"""

import importlib.util
import shutil
import subprocess
from contextlib import nullcontext

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
    for matrix in ([], [[]], [["=SUM(1,2)"]], [["=@thsiFinD(1)"], []]):
        with pytest.raises(ValueError):
            ifind_excel.fetch_matrix(matrix)


def test_matrix_is_one_worker_request_with_rows_and_columns(monkeypatch):
    calls = []
    monkeypatch.setattr(ifind_excel, "_call", lambda operation, **kw: calls.append(
        (operation, kw)) or {"values": [[10, None], [0, 20]], "errors": []})
    formulas = [[f'=@thsiFinD("field{col}","300308.SZ","2026-11-0{day}")'
                 for col in (1, 2)] for day in (3, 4)]
    result = ifind_excel.fetch_matrix(formulas, visible=False)
    assert len(calls) == 1 and calls[0][1]["matrix"] == formulas
    assert result["values"] == [[10, None], [0, 20]]


def test_single_column_text_values_remain_flat(monkeypatch):
    calls = []

    def worker(operation, **kwargs):
        calls.append((operation, kwargs))
        return {"values": ["2004-06-16"], "metrics": {}}

    monkeypatch.setattr(ifind_excel, "_call", worker)
    formula = '=@thsiFinD("ths_ipo_date_hks","0700.HK")'
    result = ifind_excel.fetch_formulas([formula], text_ok=True)
    assert result["values"] == ["2004-06-16"]
    assert calls[0][1]["formulas"] == [formula]
    assert calls[0][1]["text_ok"] is True
    assert len(calls) == 1


def test_whole_worker_deadline_becomes_timeout(monkeypatch):
    def blocked(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(ifind_excel.subprocess, "run", blocked)
    with pytest.raises(TimeoutError, match="Excel 保持原状"):
        ifind_excel.status(timeout=0.1)


def test_disabled_ifind_is_detected_before_com_access(monkeypatch):
    import winreg

    data = b"\x02\x00\x00\x00" + "C:\\iFinD\\x64\\ThsXlsSlug_x64.dll\0thsxlsslug.exceladdin".encode("utf-16le")
    monkeypatch.setattr(winreg, "OpenKey", lambda *args: nullcontext(object()))
    monkeypatch.setattr(winreg, "QueryInfoKey", lambda key: (0, 1, 0))
    monkeypatch.setattr(winreg, "EnumValue", lambda key, index: ("disabled", data, winreg.REG_BINARY))
    # None 也可触发明确禁用错误：不能先访问 Connect 并把 True 当作就绪。
    with pytest.raises(RuntimeError, match="iFinD 插件已被 Excel 禁用"):
        ifind_excel._ensure_functions(None)


def test_unrelated_disabled_items_are_left_alone(monkeypatch):
    import winreg

    monkeypatch.setattr(winreg, "OpenKey", lambda *args: nullcontext(object()))
    monkeypatch.setattr(winreg, "QueryInfoKey", lambda key: (0, 1, 0))
    monkeypatch.setattr(winreg, "EnumValue", lambda key, index: (
        "unrelated", "other-addin.dll".encode("utf-16le"), winreg.REG_BINARY))
    monkeypatch.setattr(winreg, "DeleteValue", lambda *args: pytest.fail("检查不能删除禁用项"))
    ifind_excel._check_ifind_disabled()
