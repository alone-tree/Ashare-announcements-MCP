# -*- coding: utf-8 -*-
"""2026-11-26 新增：双轴时间序列图模板 dual_axis_series。"""
import matplotlib

matplotlib.use("Agg")

from ifind_excel_tool.features import chart


def _req(**over):
    base = {
        "template": "dual_axis_series",
        "title": "测试双轴图",
        "output": ".codex-temp/dual_test.png",
        "left": {"log": False, "label": "左轴"},
        "right": {"log": False, "label": "右轴"},
        "series": [
            {"label": "序列甲", "axis": "left",
             "data": [["2026-01-05", 100.0], ["2026-01-06", 105.0],
                      ["2026-01-07", 103.0]]},
            {"label": "序列乙", "axis": "right", "dashed": True,
             "data": [["2026-01-05", 30.0], ["2026-01-07", 32.5]]},
        ],
    }
    base.update(over)
    return base


def test_dual_axis_basic(tmp_path):
    result = chart.draw(_req(output=str(tmp_path / "basic.png")))
    assert result["ok"], result
    assert result["rows"] == 5
    assert (tmp_path / "basic.png").stat().st_size > 10_000


def test_dual_axis_relative_and_log(tmp_path):
    result = chart.draw(_req(
        output=str(tmp_path / "rel.png"),
        left={"log": True, "label": "对数左轴"},
        series=[
            {"label": "市值", "axis": "left",
             "data": [[1, 1800.0], [2, 1850.0], [3, 1830.0], [4, 1900.0]]},
            {"label": "PE", "axis": "right", "dashed": True,
             "data": [[1, 22.0], [2, 22.8], [3, 22.1], [4, 23.0]]},
        ]))
    assert result["ok"], result
    assert result["left_log"] and not result["right_log"]


def test_dual_axis_rejects_bad_input(tmp_path):
    missing = chart.draw(_req(output=str(tmp_path / "x.png"),
                              series=[{"axis": "left", "data": [[1, 1]]}]))
    assert not missing["ok"] and "label" in missing["error"]
    bad_axis = chart.draw(_req(output=str(tmp_path / "x.png"),
                               series=[{"label": "甲", "axis": "top",
                                        "data": [[1, 1]]}]))
    assert not bad_axis["ok"] and "left/right" in bad_axis["error"]
    no_data = chart.draw(_req(output=str(tmp_path / "x.png"),
                              series=[{"label": "甲", "axis": "left"}]))
    assert not no_data["ok"] and "data" in no_data["error"]


def test_dual_axis_mixed_dates_fail_cleanly(tmp_path):
    result = chart.draw(_req(output=str(tmp_path / "mix.png"),
                             series=[
        {"label": "甲", "axis": "left",
         "data": [["2026-01-05", 100.0]]},
        {"label": "乙", "axis": "right", "data": [[1, 30.0]]},
    ]))
    assert not result["ok"] and "时间类型" in result["error"]
