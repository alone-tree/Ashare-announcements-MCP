# -*- coding: utf-8 -*-
"""2026-11-26：批量切分与插件原生请求包（3000公式）对齐。"""
from ifind_excel_tool.execution import engine


def test_split_by_cells_aligns_plugin_packet():
    """11408式切成3000+3000+3000+2408四批，与插件原生请求包对齐。"""
    rows = [["f"] * 8 for _ in range(1426)]
    batches = engine._split_by_cells(rows, 3000)
    sizes = [sum(len(r) for r in b) for b in batches]
    assert sizes == [3000, 3000, 3000, 2408]
    assert sum(len(b) for b in batches) == 1426


def test_split_keeps_row_atomic():
    """一行是一个整体：宽行（如三表155式）不被拆开，超上限自成一批。"""
    wide = [["f"] * 155 for _ in range(20)]
    batches = engine._split_by_cells(wide, 3000)
    # 每批最多装19行（19*155=2945），第20行进下一批
    assert [len(b) for b in batches] == [19, 1]
    merged = [row for batch in batches for row in batch]
    assert merged == wide


def test_split_single_row_over_limit():
    """单行超上限时不死循环，自成一批。"""
    huge = [["f"] * 4000]
    assert engine._split_by_cells(huge, 3000) == [huge]
