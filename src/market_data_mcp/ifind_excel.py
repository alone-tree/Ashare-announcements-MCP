"""独立 iFinD Excel 运行层；无 MCP/CLI/SDK/业务缓存依赖。

使用说明见 docs/Excel常驻运行层.md。COM 在有超时边界的短工作进程中执行，
Excel 自身常驻；每次从本模块相对位置定位专用工作簿。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path


WORKBOOK = Path(__file__).resolve().parent / "data" / "ifind_workspace.xlsx"
SHEET = "data"
FORMULA = '=@thsiFinD("ths_mv_back_test_stock","{code}","{date}")'
LOADING = ("抓取", "提取", "请求数据", "重新计算", "#GETTING_DATA", "#BUSY!")


def _call(operation: str, *, timeout: float, **arguments) -> dict:
    if os.name != "nt":
        raise RuntimeError("iFinD Excel 运行层需要 Windows 和桌面版 Excel")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout 必须为正数秒")
    request = {"operation": operation, "timeout": timeout, **arguments}
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            input=json.dumps(request, ensure_ascii=True), capture_output=True,
            text=True, encoding="utf-8", timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as error:
        # 只结束本次 Python 工作进程；不杀 Excel，不影响其他工作簿。
        raise TimeoutError(
            f"Excel {operation} 超过 {timeout:g} 秒；已停止等待，Excel 保持原状"
        ) from error
    if completed.returncode:
        raise RuntimeError(f"Excel 工作进程退出：{completed.stderr.strip()}")
    response = json.loads(completed.stdout)
    if "error" in response:
        raise RuntimeError(response["error"])
    return response


def open_excel(*, visible: bool = True, timeout: float = 60) -> dict:
    """打开或复用专用工作簿，清空 data 页；保持常驻。"""
    return _call("open", visible=visible, timeout=timeout)


def status(*, timeout: float = 15) -> dict:
    """只读状态；未打开时不启动 Excel。"""
    return _call("status", timeout=timeout)


def set_visible(visible: bool, *, timeout: float = 15) -> dict:
    """切换已打开专用实例的可见性；有其他用户工作簿时拒绝隐藏。"""
    return _call("visible", visible=visible, timeout=timeout)


def fetch_formulas(formulas: list[str], *, visible: bool | None = None,
                   timeout: float = 120) -> dict:
    """一列普通 iFinD 公式批写批读；返回原始数值/空值，前后清空 data 页。

    visible=None 保持复用实例的状态，新实例默认可见。这里只接受调用方
    已确认的 thsiFinD 公式，不生成指标参数或计算派生值。
    """
    if not formulas or not all(isinstance(f, str) and
                               f.lower().startswith(("=@thsifind(", "=thsifind("))
                               for f in formulas):
        raise ValueError("需要非空的普通 thsiFinD 公式列表")
    return _call("fetch", formulas=list(formulas), visible=visible, timeout=timeout)


def get_market_value(code: str, start: str, end: str, *,
                     visible: bool | None = None, timeout: float = 120) -> dict:
    """用已实测模板按日历日查询总市值，不读写业务缓存、不回退 SDK。"""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError("开始日期不能晚于结束日期")
    days = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    formulas = [FORMULA.format(code=code.replace('"', '""'), date=day) for day in days]
    result = fetch_formulas(formulas, visible=visible, timeout=timeout)
    result["rows"] = [{"date": day, "value": value, "source": "ifind"}
                      for day, value in zip(days, result.pop("values"), strict=True)]
    result.update(code=code, field="total_market_cap", frequency="calendar_day", unit="元")
    return result


def close_excel(*, timeout: float = 30) -> dict:
    """只关闭当前包的专用工作簿；未打开时不启动。"""
    return _call("close", timeout=timeout)


def _find_workbook():
    """用 WM_GETOBJECT/OBJID_NATIVEOM 取得原生 COM 对象，不改变焦点。"""
    import pythoncom
    import pywintypes
    import win32gui
    import win32process
    from win32com.client import dynamic

    windows = []
    win32gui.EnumWindows(
        lambda hwnd, _: windows.append(hwnd) if win32gui.GetClassName(hwnd) == "XLMAIN"
        and WORKBOOK.name.lower() in win32gui.GetWindowText(hwnd).lower() else None,
        None,
    )
    seen = set()
    busy = {}
    for hwnd in windows:
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        if pid in seen:
            continue
        children = []
        win32gui.EnumChildWindows(
            hwnd, lambda child, _: children.append(child)
            if win32gui.GetClassName(child) == "EXCEL7" else None, None,
        )
        for child in children:
            try:
                _, value = win32gui.SendMessageTimeout(child, 0x003D, 0, -16, 2, 1000)
                if not value:
                    continue
                app = dynamic.Dispatch(
                    pythoncom.ObjectFromLresult(value, pythoncom.IID_IDispatch, 0)
                ).Application
                for book in app.Workbooks:
                    if os.path.normcase(os.path.abspath(book.FullName)) == os.path.normcase(str(WORKBOOK)):
                        return app, book, pid
                seen.add(pid)
                break
            except (pythoncom.com_error, pywintypes.error, AttributeError) as error:
                busy[pid] = str(error)
    if busy:
        # 其他忙碌实例不妨碍绑定已经找到的目标；找不到目标时不能贸然另开。
        raise RuntimeError(f"Excel 实例尚未就绪：{busy}")
    return None


def _personal_readonly(pid: int, handled: set[int]) -> int:
    """仅处理本次新进程的 PERSONAL 文件锁提示；不处理认证或其他对话框。"""
    import win32gui
    import win32process

    dialogs = []
    win32gui.EnumWindows(
        lambda hwnd, _: dialogs.append(hwnd)
        if win32process.GetWindowThreadProcessId(hwnd)[1] == pid
        and win32gui.GetClassName(hwnd) in ("#32770", "bosa_sdm_XL9") else None, None,
    )
    count = 0
    for dialog in dialogs:
        if dialog in handled:
            continue
        title = win32gui.GetWindowText(dialog).lower()
        if title not in ("文件正在使用", "file in use"):
            continue
        # Office 自绘对话框没有按钮 HWND；UIA Invoke 不模拟键盘鼠标。
        from pywinauto import Desktop
        children = Desktop(backend="uia").window(handle=dialog).wrapper_object().descendants()
        text = " ".join(child.window_text() for child in children)
        if "PERSONAL.XLSB" not in text.upper():
            continue
        for child in children:
            label = child.window_text().replace("&", "").strip().lower()
            if child.element_info.control_type == "Button" and label.startswith(("只读", "read only", "read-only")):
                child.iface_invoke.Invoke()
                handled.add(dialog)
                count += 1
                break
    return count


def _excel_executable() -> str:
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe") as key:
                executable = str(winreg.QueryValueEx(key, None)[0]).strip('"')
                if Path(executable).is_file():
                    return executable
        except FileNotFoundError:
            pass
    raise RuntimeError("未找到桌面版 Excel 安装路径")


def _ensure_functions(app):
    """COM 插件已连接仍可能缺少 UDF；显式只读加载官方 ThsFunc.xla。"""
    import pythoncom
    import winreg

    plugin = app.COMAddIns.Item("ThsXlsSlug.ExcelAddin")
    if not plugin.Connect:
        plugin.Connect = True
    try:
        return app.Workbooks.Item("ThsFunc.xla")
    except pythoncom.com_error:
        pass
    paths = [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "iFinD/ThsFunc.xla"]
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"ThsXlsSlug.ExcelAddin\CLSID") as key:
            clsid = winreg.QueryValueEx(key, None)[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\InprocServer32") as key:
            dll = Path(str(winreg.QueryValueEx(key, None)[0]).strip('"'))
        paths.extend([dll.parent / "ThsFunc.xla", dll.parent.parent / "ThsFunc.xla"])
    except FileNotFoundError:
        pass
    for path in paths:
        if path.is_file():
            return app.Workbooks.Open(str(path), UpdateLinks=0, ReadOnly=True)
    raise RuntimeError("未找到 iFinD 官方 ThsFunc.xla，无法注册 Excel 公式")


def _other_books(app, target) -> tuple[list[str], bool]:
    """识别其他用户工作簿；仅豁免原路径的 PERSONAL 和加载项。"""
    startup = Path(app.StartupPath) / "PERSONAL.XLSB"
    others, unsaved = [], False
    for book in app.Workbooks:
        if os.path.normcase(book.FullName) == os.path.normcase(target.FullName):
            continue
        personal = os.path.normcase(book.FullName) == os.path.normcase(str(startup))
        if not book.IsAddin and not personal:
            others.append(book.FullName)
        if not book.Saved:
            unsaved = True
    return others, unsaved


def _visibility(app, book, visible):
    if visible is None:
        return
    if not isinstance(visible, bool):
        raise ValueError("visible 必须为布尔值")
    if not visible:
        others, _ = _other_books(app, book)
        if others:
            raise RuntimeError(f"专用实例包含其他工作簿，拒绝隐藏：{others}")
    app.Visible = visible


def _snapshot(app, book, pid) -> dict:
    sheet = book.Worksheets(SHEET)
    # 清理后的 UsedRange 仍可能保留旧尺寸，CountA 检查实际残留而非尺寸。
    return {"workbook": str(WORKBOOK), "opened": True, "pid": pid,
            "visible": bool(app.Visible), "read_only": bool(book.ReadOnly),
            "nonempty_cells": int(app.WorksheetFunction.CountA(sheet.UsedRange))}


def _execute(request: dict, deadline: float) -> dict:
    import pythoncom

    operation = request["operation"]
    connected = _find_workbook()
    reused = connected is not None
    startup_prompts = 0
    if connected is None:
        if operation in ("status", "visible", "close"):
            return {"workbook": str(WORKBOOK), "opened": False}
        if not WORKBOOK.is_file():
            raise FileNotFoundError(f"缺少专用工作簿：{WORKBOOK}")
        process = subprocess.Popen([_excel_executable(), "/x", str(WORKBOOK)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        handled = set()
        while time.monotonic() < deadline:
            startup_prompts += _personal_readonly(process.pid, handled)
            pythoncom.PumpWaitingMessages()
            try:
                connected = _find_workbook()
            except RuntimeError:
                connected = None  # 仅此次启动期间允许等待原实例就绪，不再次启动。
            if connected:
                break
            if process.poll() is not None:
                raise RuntimeError(f"Excel 启动进程提前退出：{process.returncode}")
            time.sleep(0.5)
        if connected is None:
            raise TimeoutError("等待专用工作簿打开超时")
    app, book, pid = connected
    if operation == "status":
        return _snapshot(app, book, pid)
    if operation == "visible":
        _visibility(app, book, request["visible"])
        return _snapshot(app, book, pid)
    if book.ReadOnly:
        raise RuntimeError("专用工作簿以只读方式打开，拒绝操作")
    if operation == "close":
        others, unsaved = _other_books(app, book)
        book.Worksheets(SHEET).Cells.ClearContents()
        book.Close(SaveChanges=False)
        quit_excel = not others and not unsaved
        if quit_excel:
            app.Quit()
        return {"workbook": str(WORKBOOK), "opened": False, "pid": pid,
                "quit_excel": quit_excel, "other_workbooks": others}
    sheet = book.Worksheets(SHEET)
    sheet.Cells.ClearContents()
    functions = _ensure_functions(app)  # 保持加载项 COM 引用直到本次操作结束。
    _visibility(app, book, request.get("visible") if reused else request.get("visible", True))
    if operation == "open":
        return {**_snapshot(app, book, pid), "reused": reused,
                "startup_personal_readonly": startup_prompts}
    if operation != "fetch":
        raise ValueError(f"未知内部操作：{operation}")
    formulas = request["formulas"]
    region = sheet.Range(f"A1:A{len(formulas)}")
    metrics = {}
    try:
        stamp = time.perf_counter()
        region.Formula2 = tuple((formula,) for formula in formulas)
        metrics["formula_write_seconds"] = time.perf_counter() - stamp
        polls = 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("等待 iFinD 自动登录或取数完成超时")
            time.sleep(0.5)
            pythoncom.PumpWaitingMessages()
            polls += 1
            try:
                stamp = time.perf_counter()
                raw = region.Value2
                values = [raw] if len(formulas) == 1 else [row[0] for row in raw]
                metrics["read_seconds"] = time.perf_counter() - stamp
                loading = False
                for index, value in enumerate(values, 1):
                    if isinstance(value, int) and value < -2000000000:
                        value = str(sheet.Cells(index, 1).Text)
                    if isinstance(value, str):
                        if any(word in value for word in LOADING):
                            loading = True
                        else:
                            raise RuntimeError(f"iFinD 单元格 A{index} 返回：{value}")
                    elif value is not None and not isinstance(value, (int, float)):
                        raise RuntimeError(f"iFinD 单元格 A{index} 类型异常：{type(value).__name__}")
                if not loading and app.CalculationState == 0:
                    break
            except pythoncom.com_error:
                continue  # 正在计算，继续等待；外层工作进程有整体超时。
        metrics["polls"] = polls
    finally:
        sheet.Cells.ClearContents()
    return {**_snapshot(app, book, pid), "reused": reused, "values": values, "metrics": metrics}


def _worker(request: dict) -> dict:
    sys.coinit_flags = 2  # pywin32 与可选 UIA 组件均使用同一 STA。
    import pythoncom
    import win32api
    import win32event

    started = time.perf_counter()
    deadline = time.monotonic() + request["timeout"]
    lock_name = "Local\\ifind-excel-" + hashlib.sha256(os.path.normcase(str(WORKBOOK)).encode()).hexdigest()
    mutex = win32event.CreateMutex(None, False, lock_name)
    acquired = False
    pythoncom.CoInitialize()
    try:
        wait = win32event.WaitForSingleObject(mutex, int(request["timeout"] * 1000))
        if wait not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
            raise TimeoutError("等待专用工作簿使用权超时")
        acquired = True
        result = _execute(request, deadline)
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        return result
    finally:
        pythoncom.CoUninitialize()
        if acquired:
            win32event.ReleaseMutex(mutex)
        win32api.CloseHandle(mutex)


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("这是 Python 模块；请导入后调用公开函数。")
    try:
        response = _worker(json.load(sys.stdin))
    except Exception as error:
        response = {"error": f"{type(error).__name__}: {error}"}
    print(json.dumps(response, ensure_ascii=True), flush=True)
