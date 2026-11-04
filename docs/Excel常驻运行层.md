# Excel 常驻运行层

这是尚未接入 market-data 业务通道的独立实验模块。模块与空白工作簿已实现；已初始化实例的批量取数、隐藏复用、清空及关闭已验证。冷启动后的 iFinD 初始化尚未验收通过，会出现错误零值，当前不能自动写入业务缓存。实测数字、失败样本与边界统一见[实测报告](Excel取数基础实测-2026-11-04.md#常驻运行层实测2026-11-04)。后续接入范围见[实施计划](market-data-Excel常驻取数方案-2026-11-04.md)。

## 文件与依赖

- 模块：`src/market_data_mcp/ifind_excel.py`。
- 专用模板：模块同目录的 `data/ifind_workspace.xlsx`，仅有空白 `data` 工作页。
- 当前实测环境：`D:\venvs\a-share-announcements\Scripts\python.exe`，Python 3.11.15，桌面版 Excel 和已安装的 iFinD 插件。
- 独立依赖清单：`excel-probe/requirements.txt`。`pywin32` 用于 Excel COM/Windows API；`pywinauto` 用于专用启动进程的 PERSONAL 文件锁提示，使用 UI Automation Invoke，不模拟鼠标键盘；`openpyxl` 仅用于模板及测试产物检查。

本模块不依赖 `iFinDPy`、MCP、CLI、provider、业务缓存或 SDK 登录。路径由模块自身的 `__file__` 计算，不根据 cwd 或 `MARKET_DATA_ROOT` 定位。普通 Python 工作进程负责 COM 调用；Excel 保持常驻。相同完整工作簿路径使用 Windows 命名互斥锁，不同目录分别管理。

本轮没有修改导出脚本，正式用户版不会因本次提交自动带上运行层或工作簿。

## Python 调用

从当前开发树运行时设置 `PYTHONPATH=src`，再在普通 Python 脚本中导入。以下是各函数的用法示例，不表示冷启动已具备业务验收条件：

```python
from market_data_mcp.ifind_excel import (
    open_excel, status, set_visible, fetch_formulas,
    get_market_value, close_excel,
)

open_excel()                       # 打开或复用，默认可见，清空 data 页
status()                           # 只读状态，不自动打开
set_visible(False)                 # 隐藏已打开的专用实例

result = get_market_value(
    "600519.SH", "2000-01-01", "2026-11-03",
)
rows = result["rows"]              # date/value/source；按日历日，原始值

set_visible(True)                  # 恢复可见
close_excel()                      # 单独关闭；未打开则直接返回
```

`get_market_value` 仅使用用户已提供并实测的 `ths_mv_back_test_stock` 模板。本轮真实数据范围只覆盖报告中的 A 股样本，不将其外推到其他指标或市场。

`fetch_formulas` 接受调用方已确认的普通 `thsiFinD` 公式列表，一列批写、一次批读，返回 `values`；当前返回类型是数值或空值，不是公司概况等文本字段的通用提取器。日期序列接口、自动发现指标和新公式推测均不在模块内。

取数的 `visible=None` 表示复用时保持现有可见状态；新实例正常可见启动。`visible=False` 表示启动完成后再隐藏，首次启动可能短暂显示窗口。每次取数前后清空整个 `data` 页，原始零值与空值不填充、不转换；临时公式不保存到磁盘模板。返回 `nonempty_cells=0` 表示本次工作页清理完成。

每个公开函数接受秒数 `timeout`。超时覆盖工作进程内的同步 COM 调用；超时时只终止本次 Python 工作进程，Excel 保持原状，不能保证已经执行请求后的清理。下次取数开头仍会清空工作页。

## 启动与隔离

正常启动采用安装信息中的 `EXCEL.EXE /x 专用路径`，再经 Windows 原生对象模型取得 COM 对象。候选窗口按文件名初筛，最终必须核对完整路径，避免开发树与独立副本串用；同名不能证明是同一文件。绑定隐藏实例不改变焦点。

启动可能加载 `PERSONAL.XLSB`。如果其他 Excel 已占用它，只对本轮新启动 PID 的“文件正在使用”窗口读取 UI Automation 内容，确认包含 `PERSONAL.XLSB` 后调用“只读”的 Invoke。不会自动处理其他文件锁、认证或恢复询问；未知窗口及不可访问状态按实际错误或超时返回。

插件连接与公式注册分别检查，必要时只读打开已安装的官方 `ThsFunc.xla`。这只说明加载动作已执行，不能作为已登录或数据正确的证明；当前冷启动失败正是尚未解决的初始化边界。

隐藏前若发现同实例内还有其他用户工作簿，则拒绝隐藏。关闭只清空、关闭当前包的专用工作簿；有其他用户工作簿或其他未保存内容时保留实例，不保存或丢弃其内容。自动启动的原路径 PERSONAL 只作退出条件识别，不改其内容。

## 当前交付边界

已验证和未通过项只在实测报告维护。冷启动错误零值的根因未确认；不能据此断言“多实例不支持”，也不能通过把零值改为空、固定等待、补值或改缓存掩盖。

本模块目前保留原始结果供实验核验，不提供“数据已正确”的保证。MCP/CLI、SDK 回退、现有缓存与月频加工均未改动。启动就绪判定通过前不接入业务通道。
