"""本轮独立 Excel 实测；实施依据见 docs/Excel取数基础实测-2026-11-04.md。"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path


FORMULA = '=@thsiFinD("ths_mv_back_test_stock","{code}","{date}")'
LOADING = ("抓取", "提取", "请求数据", "重新计算", "#GETTING_DATA", "#BUSY!")


def get_market_value(code: str, start: str, end: str, output: str | None = None,
                     timeout: float = 120) -> dict:
    """可见启动、按日历日取数、一次读回、关闭本次工作簿；不读写业务缓存。"""
    import pythoncom
    import pywintypes
    from openpyxl import Workbook
    from win32com.client import dynamic

    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError("开始日期不能晚于结束日期")
    dates = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    root = (Path(output) if output else Path(__file__).parent / "runs" /
            datetime.now().strftime("%Y%m%d-%H%M%S-%f")).resolve()
    root.mkdir(parents=True, exist_ok=False)
    book_path = root / "取数测试.xlsx"
    events = []
    started = time.perf_counter()

    def log(event, **details):
        entry = {"event": event, "elapsed_seconds": round(time.perf_counter() - started, 3), **details}
        events.append(entry)
        with (root / "过程.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=True), file=sys.stderr, flush=True)

    disk_book = Workbook()
    disk_sheet = disk_book.active
    disk_sheet.title = "取数"
    disk_sheet.append(["日期", "总市值（元）"])
    for row, (label, value) in enumerate((("证券代码", code), ("开始日期", start), ("结束日期", end)), 1):
        disk_sheet.cell(row, 5, label)
        disk_sheet.cell(row, 6, value)
    for column, width in (("A", 16), ("B", 24), ("E", 18), ("F", 24)):
        disk_sheet.column_dimensions[column].width = width
    disk_book.save(book_path)
    disk_book.close()
    log("created_workbook", path=str(book_path), calendar_rows=len(dates))

    pythoncom.CoInitialize()
    excel = workbook = sheet = raw = None
    had_excel = False
    result = None

    def active_excel():
        nonlocal raw
        try:
            raw = pythoncom.GetActiveObject(pywintypes.IID("Excel.Application"))
        except pywintypes.com_error as error:
            if error.hresult == -2147221021:  # MK_E_UNAVAILABLE：没有已注册的运行实例。
                return None
            raise
        # 使用动态 IDispatch，避免依赖本机生成的 COM 包装缓存。
        return dynamic.Dispatch(raw.QueryInterface(pythoncom.IID_IDispatch))

    try:
        excel = active_excel()
        had_excel = excel is not None
        if had_excel:
            workbook = excel.Workbooks.Open(str(book_path))
            log("opened_in_existing_excel")
        else:
            subprocess.run(["explorer.exe", str(book_path)], timeout=10, check=False)
            log("requested_excel_start")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    excel = active_excel()
                    if excel is not None:
                        for candidate in excel.Workbooks:
                            if Path(candidate.FullName).resolve() == book_path:
                                workbook = candidate
                                break
                        if workbook is not None:
                            break
                except (pywintypes.com_error, AttributeError):
                    pass  # 启动尚未就绪；不重新启动 Excel。
                time.sleep(1)
            if workbook is None:
                raise TimeoutError("等待 Excel 打开测试工作簿超时")

        excel.Visible = True
        sheet = workbook.Worksheets("取数")
        addins = [{"id": item.ProgId, "connected": bool(item.Connect)} for item in excel.COMAddIns
                  if "ths" in item.ProgId.lower()]
        log("connected_excel", visible=bool(excel.Visible), hwnd=excel.Hwnd, addins=addins)

        bottom = len(dates) + 1
        sheet.Range(f"A2:A{bottom}").NumberFormat = "@"
        stamp = time.perf_counter()
        sheet.Range(f"A2:A{bottom}").Value2 = tuple((day,) for day in dates)
        date_write = time.perf_counter() - stamp
        formulas = tuple((FORMULA.format(code=code.replace('"', '""'), date=day),) for day in dates)
        stamp = time.perf_counter()
        sheet.Range(f"B2:B{bottom}").Formula2 = formulas
        formula_write = time.perf_counter() - stamp
        log("wrote_batch", rows=len(dates), date_write_seconds=date_write,
            formula_write_seconds=formula_write)

        # Excel 的计算状态不覆盖插件全部网络活动，还要检查整块返回内容。
        deadline = time.monotonic() + timeout
        attempt = 0
        while True:
            attempt += 1
            time.sleep(1)
            try:
                stamp = time.perf_counter()
                rows = sheet.Range(f"A2:B{bottom}").Value2
                read_seconds = time.perf_counter() - stamp
                loading, errors = [], []
                for index, (_, value) in enumerate(rows, 2):
                    if isinstance(value, int) and value < -2000000000:
                        value = str(sheet.Cells(index, 2).Text)
                    if isinstance(value, str):
                        if any(word in value for word in LOADING):
                            loading.append(index)
                        else:
                            errors.append({"cell": f"B{index}", "value": value})
                state = excel.CalculationState
                if errors:
                    raise RuntimeError(f"Excel 返回错误或非数值文本：{errors[:5]}")
                log("read_batch", attempt=attempt, loading_cells=len(loading),
                    calculation_state=state, read_seconds=read_seconds)
                if not loading and state == 0:
                    break
            except (pywintypes.com_error, AttributeError) as error:
                log("excel_busy", attempt=attempt, error=str(error))
            if time.monotonic() >= deadline:
                raise TimeoutError("等待 iFinD 自动登录或取数完成超时；没有操作登录窗口")

        if [row[0] for row in rows] != dates:
            raise RuntimeError("读回日期与实际写入的日历日不一致")
        records = [{"date": day, "value": value, "source": "ifind"} for day, value in rows]
        metrics = {"date_write_seconds": date_write, "formula_write_seconds": formula_write,
                   "read_seconds": read_seconds, "polls": attempt,
                   "numeric_rows": sum(isinstance(row[1], (int, float)) for row in rows),
                   "empty_rows": sum(row[1] is None for row in rows)}
        result = {"code": code, "field": "total_market_cap", "source": "ifind",
                  "start": start, "end": end, "frequency": "calendar_day", "unit": "元",
                  "total_rows": len(rows), "formula_template": FORMULA, "metrics": metrics,
                  "output_dir": str(root), "workbook": str(book_path), "rows": records}
        (root / "结果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        with (root / "结果.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["date", "total_market_cap"])
            writer.writerows(rows)
        workbook.Save()
        log("saved_results", numeric_rows=metrics["numeric_rows"], empty_rows=metrics["empty_rows"])
    except Exception as error:
        log("failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        try:
            if workbook is not None:
                workbook.Close(SaveChanges=False)
                log("closed_workbook")
            if excel is not None and not had_excel:
                others = [book.Name for book in excel.Workbooks
                          if book.Name.upper() != "PERSONAL.XLSB" and not book.IsAddin]
                if not others:
                    excel.Quit()
                    log("quit_excel")
                else:
                    log("kept_excel_for_other_workbooks", workbooks=others)
        finally:
            sheet = workbook = excel = raw = None
            pythoncom.CoUninitialize()
    if result is not None:
        result["events"] = events
        (root / "结果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="可见 Excel 总市值取数探针，不接入 MCP 或业务缓存")
    parser.add_argument("--code", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    value = get_market_value(args.code, args.start, args.end, args.output)
    print(json.dumps({key: item for key, item in value.items() if key not in ("rows", "events")},
                     ensure_ascii=True), flush=True)
