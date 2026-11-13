# Excel 常驻运行层

这是已接入market-data内地与港股行情的Excel运行层，业务范围见[Excel行情细则](行为-Excel行情.md)。打开、隐藏、批量取数、复用、清空、关闭及目录隔离已完成样本验证。此前错误零值已确认与Excel禁用iFinD有关；恢复后的冷启动及共存取数通过，历史实测和边界见[报告](Excel取数基础实测-2026-11-04.md#插件禁用根因确认与恢复后复测)。

## 文件与依赖

- 模块：`src/market_data_mcp/ifind_excel.py`。
- 专用模板：模块同目录的 `data/ifind_workspace.xlsx`，仅有空白 `data` 工作页。
- 当前实测环境：`D:\venvs\a-share-announcements\Scripts\python.exe`，Python 3.11.15，桌面版 Excel 和已安装的 iFinD 插件。
- 独立依赖清单：`excel-probe/requirements.txt`。`pywin32` 用于 Excel COM/Windows API；`pywinauto` 用于专用启动进程的 PERSONAL 文件锁提示，使用 UI Automation Invoke，不模拟鼠标键盘；`openpyxl` 仅用于模板及测试产物检查。

本模块不依赖 `iFinDPy`、MCP、CLI、provider、业务缓存或 SDK 登录。路径由模块自身的 `__file__` 计算，不根据 cwd 或 `MARKET_DATA_ROOT` 定位。普通 Python 工作进程负责 COM 调用；Excel 保持常驻。相同完整工作簿路径使用 Windows 命名互斥锁，不同目录分别管理。

导出脚本声明Windows COM依赖并携带空白专用工作簿；实际导出与验收的有日期记录见[决策记录](决策记录.md)。

## Python 调用

从当前开发树运行时设置 `PYTHONPATH=src`，再在普通 Python 脚本中导入。需要桌面 Excel 已安装 iFinD 插件、插件处于启用状态，并已按用户设置记住账号及自动登录：

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

`fetch_formulas` 保留已确认普通 `thsiFinD` 公式的单列批写、批读接口。`fetch_matrix` 接受等宽二维公式列表，一行一个日期、一列一个字段，整块写入和读取，返回二维 `values` 及零起始行列索引的 `errors`；个别单元格错误置空并报告，不丢弃其他字段。返回类型仍为数值或空值，不是工商文本的通用提取器。日期序列接口、自动发现指标和新公式推测均不在模块内。

取数的 `visible=None` 表示复用时保持现有可见状态；新实例正常可见启动。`visible=False` 表示启动完成后再隐藏，首次启动可能短暂显示窗口。每次取数前后清空整个 `data` 页，原始零值与空值不填充、不转换；临时公式不保存到磁盘模板。返回 `nonempty_cells=0` 表示本次工作页清理完成。

每个公开函数接受秒数 `timeout`。超时覆盖工作进程内的同步 COM 调用；超时时只终止本次 Python 工作进程，Excel 保持原状，不能保证已经执行请求后的清理。下次取数开头仍会清空工作页。

## 启动与隔离

正常启动采用安装信息中的 `EXCEL.EXE /x 专用路径`，再经 Windows 原生对象模型取得 COM 对象。候选窗口按文件名初筛，最终必须核对完整路径，避免开发树与独立副本串用；同名不能证明是同一文件。绑定隐藏实例不改变焦点。

启动可能加载 `PERSONAL.XLSB`。如果其他 Excel 已占用它，只对本轮新启动 PID 的“文件正在使用”窗口读取 UI Automation 内容，确认包含 `PERSONAL.XLSB` 后调用“只读”的 Invoke。不会自动处理其他文件锁、认证或恢复询问；未知窗口及不可访问状态按实际错误或超时返回。

取数前读取当前用户的 Excel `Resiliency/DisabledItems`，若发现 iFinD DLL 或 ProgID，明确报告“iFinD 插件已被 Excel 禁用”，不继续将此状态下的零值作为正常结果。检查只读、不自动删除禁用记录，不干预用户主动禁用的选择；`Connect=True` 与 `ThsFunc.xla` 存在不足以排除硬禁用。

恢复禁用加载项可使用 Excel 的“文件 → 选项 → 加载项 → 管理：禁用项目 → 转到 → 选择 iFinD → 启用”，之后正常重启。此为[微软提供的禁用项目恢复入口](https://support.microsoft.com/en-us/office/lifecycle/open-office-apps-in-safe-mode-on-a-windows-pc)，不是每次取数时自动执行的步骤。

插件连接与公式注册仍分别检查，必要时只读打开已安装的官方 `ThsFunc.xla`。禁用检查不代替登录；登录继续依赖客户端记住账号与自动登录，不自动处理认证窗口。

隐藏前若发现同实例内还有其他用户工作簿，则拒绝隐藏。关闭只清空、关闭当前包的专用工作簿；有其他用户工作簿或其他未保存内容时保留实例，不保存或丢弃其内容。自动启动的原路径 PERSONAL 只作退出条件识别，不改其内容。

## 当前交付边界

已验证项与失败历史只在实测报告维护。本轮已确认 Excel 禁用插件的故障原因并完成恢复后的对照，不将故障期间的零值用于推断正常启用时的冷启动可靠性，也不改写历史失败记录。原始零值和空值继续按上游返回保留，不自行改为空或补算。

本模块只返回运行结果，业务缓存及MCP/CLI由数据服务管理，范围见Excel行情细则；没有SDK行情回退。已验证样本不能外推为所有指标或市场均已验证。
