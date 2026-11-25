# ifind_excel_tool：iFinD Excel 插件取数工作台

纯 CLI、公式库驱动、随用随开发。与 market_data_mcp 平级，零 import 依赖。

## 组成

| 部分 | 内容 |
|---|---|
| engine.py | Excel COM 执行层，从 market_data_mcp/ifind_excel.py 复制，独立定位工作簿；启动前自动清除本工作簿的崩溃恢复残留 |
| cli.py | 极薄入口，stdin JSON → stdout JSON，顶层字段 `cmd`；命令见下 |
| scenes.py / scenes/ | 固定场景清单，`fetch_scene` 按场景取数 |
| search.py | 证券代码搜索，股票走东财、指数外汇查本地表 |
| report.py | 固定报告拼装，`export_report` 把各板块CSV拼成Markdown骨架 |
| chart.py | 绘图基础模块，`draw` 按模板出PNG，仅用matplotlib，零 import market-data |
| resample.py | 行情周/月本地聚合 |
| formula_library/verified-formulas.jsonl | 已验证公式，人工锚定，AI 优先检索 |
| formula_library/catalog.jsonl | 全量30281条指标索引，内容不可靠，禁止查询 |
| data/ifind_workspace.xlsx | 专用工作簿，只含 data 页（纯取数通道，永不保存） |

命令分三类：取数 `fetch_scene`（固定场景，优先用）、`search`（查证券代码）、`lookup`/`run`/`text`（场景没有才用）、`export_report`（各板块CSV拼报告骨架）、`draw`（按模板绘图）；帮助 `help`/`help_scene`/`help_indicators`/`scenes`/`scene_info`；Excel生命周期 `open`/`status`/`close`。先跑 `{"cmd":"help"}` 看导航。

## 用法

AI 取数流程：

1. `lookup` 查已验证库，拿到公式模板和参数。
2. 命中：写一次性脚本调 engine.fetch_matrix（数值）或 fetch_formulas（文本）执行。
3. 未命中：按[公式来源与录入流程](formula_library/README.md#批量公式录入与验证流程)核对插件原文。
4. 反复使用的场景才写成 recipes/ 下的固定脚本。

CLI 示例（stdin JSON → stdout JSON）：

在仓库根目录执行（必须设 PYTHONPATH=src 并用项目 venv）：

```bash
echo '{"cmd":"lookup","keyword":"净利润","limit":5}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
```

`run`/`text` 同理，把上面 JSON 换成 `{"cmd":"run","matrix":[...]}` 或 `{"cmd":"text","formulas":[...]}`；用完可发 `{"cmd":"close"}` 不保存关闭专用 Excel。

另有 `{"cmd":"status"}`（只读查状态，未打开时不启动 Excel）与 `{"cmd":"open"}`（打开或复用专用工作簿）。

## 固定报告导出

一个板块导一份 CSV：`fetch_scene` 带 `export_path` 写到指定路径即可，每个代码单独导就按单 `code` 调用。

```bash
echo '{"cmd":"fetch_scene","scene":"工商信息","code":"002796.SZ","export_path":"数据/工商信息.csv"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
```

板块与场景对应：工商信息、十大股东、历史行情、估值快照、资产负债表、利润表、现金流量表、利润表单季、现金流量表单季、指数成分股、指数进出记录。显式传 `export_path` 时 `records` 全量返回；不传且超过200行时自动落 `exports/` 且只回前20行预览（`truncated=true`），完整数据在 `export.path`，判断是否取全看 `rows` 与CSV。

各板块CSV齐了以后，拼成固定Markdown骨架：

```bash
echo '{"cmd":"export_report","company":"世嘉科技","code":"002796.SZ","sections":{"工商信息":"数据/工商信息.csv","利润表":"数据/利润表.csv"},"output":"骨架.md"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
```

`export_report` 只做拼装，不取数、不推算。没有数据的板块留空节并标注缺口。IPO信息、分红、营收结构、盈利预测四块暂未在场景中提供，会标"未取到数据，待补"。

注意：财报类场景（三表、单季表、十大股东）不传 `report_date` 时会自动探测最新已披露报告期，并在返回里给出 `report_date` 与 `report_date_probed=true`；探测失败会明确报错要求显式指定。固定资产、在建工程已合并为多候选字段，自动取合计与单科目的较大值，两值不同时留 `__choices` 痕迹。

## 绘图draw

`draw` 读已导出的行情CSV出PNG，不取数。列名自动识别中文（iFinD导出）与英文；也可用 `price_col`/`mcap_col` 显式指定。

```bash
echo '{"cmd":"draw","template":"kline_volume","data_path":"数据/历史行情.csv","output":"行情.png"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
```

四个模板：

| 模板 | 内容 | 常用参数 |
|---|---|---|
| kline_volume | 标准K线+成交量副图+MA5/10/20/60，红涨绿跌 | `ma_windows`、`log_scale` |
| kline_log_volume | 同上，价格与量轴取对数，含0或负值自动退回普通坐标 | `ma_windows` |
| close_mcap_events | 双轴折线（总市值+前复权收盘价）+事件标注 | `events`、`price_col`、`mcap_col` |
| close_line_keypoints | 单折线+最高/最低/最新+回撤高低点标注 | `drawdown_threshold`（默认0.30） |

`events` 支持 CSV（date,description 两列）或 JSON 数组 `[{"date":"2024-09-24","description":"..."}]`，事件日对齐到不早于事件日的最近交易日。绘图视觉规范（配色、字体、布局、标签避让）由 chart.py 统一固定，模板不各自维护。此绘图能力与 market-data 的 `get_quote_chart` 各自独立：market-data 是取数即绘图，这里是读已导出的CSV绘图，零 import 依赖。

## 取数失败时怎么判断

COM 连不上专用工作簿时，报错会直接说明最可能的原因和下一步，不需要猜：

| 提示 | 含义 | 处理 |
|---|---|---|
| Excel 界面有响应但拒绝COM，最常见原因是正在编辑单元格 | 光标停在格子里没按回车 | 自动发 Esc 解除，无需人工干预 |
| Excel 被对话框挡住：函数搜索/参数定义 | iFinD 弹窗遮挡 | 关掉该窗口 |
| Excel 实例已无响应（真的僵死） | 窗口线程也不响应 | 结束该进程后重新取数 |
| 该进程已没有本工作簿的窗口 | 残留进程 | 结束该进程 |

单元格编辑状态会自动解除：检测到「窗口有响应但 COM 拒绝」时，向专用工作簿发 Esc 后重试，必要时关掉重开以清除 iFinD 的公式缓存。只对专用工作簿操作，不碰同实例的其他工作簿与其他 Excel 进程。

注意：其余故障时 `close` 命令走同一条 COM 通道、同样会失败，不要反复重试 close。

一次性脚本示例（写到 `.codex-temp/` 用完即删）：

```python
import sys
sys.path.insert(0, 'src')
from ifind_excel_tool import engine

# 先用 lookup 拿 formula_template，替换 {code}/{date}/{type} 占位符后填入完整公式
matrix = [
    ['=@thsiFinD("ths_revenue_stock","600519.SH","2025-12-31",100)'],
    ['=@thsiFinD("ths_np_stock","600519.SH","2025-12-31",100)'],
]
r = engine.fetch_matrix(matrix, timeout=300)
print(r['values'], r.get('errors'))
# engine 返回裸数值二维数组；单位取 lookup 的 unit 字段（注意 EPS 为元/股，与金额元不同）
```

公式模板里的占位符有 `{code}`、`{date}`、`{type}` 三种，需自行替换成完整公式；engine 只接受以 `=@thsiFinD(` 开头或 `=thsiFinD(` 开头的完整公式。

## 库维护

- 公式来源、字段定义和验收标准见[公式库说明](formula_library/README.md)。
- catalog.jsonl 内容不可靠，除用户明确要求外禁止查询，不得用于找候选、核对字段或补参数。
- 文本字段（简称、日期）用 reading_mode=text，走 fetch_formulas(text_ok=True)。
