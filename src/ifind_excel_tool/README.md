# ifind_excel_tool：iFinD Excel 插件取数工作台

纯 CLI、公式库驱动、随用随开发。与 market_data_mcp 平级，零 import 依赖。

## 组成

| 部分 | 内容 |
|---|---|
| engine.py | Excel COM 执行层，从 market_data_mcp/ifind_excel.py 复制，独立定位工作簿；启动前自动清除本工作簿的崩溃恢复残留 |
| cli.py | 极薄入口，stdin JSON → stdout JSON，顶层字段 `cmd`；命令见下 |
| scenes.py / scenes/ | 固定场景清单，`fetch_scene` 按场景取数 |
| indicator_index.py | 统一指标索引，`find` 在全部能力里搜指标并给用法 |
| indicators.py | 统一指标取数，`get` 按定义类型自动分派并完成派生计算 |
| formula_library/derived-indicators.jsonl | 自定义派生指标（毛利润、毛利率），写依赖与算式 |
| formula_library/indicator-groups.jsonl | 指标组（利润表常用科目），一次取一组 |
| search.py | 证券代码搜索，股票走东财、指数外汇查本地表 |
| report.py | 固定报告排版，`report` 命令把各板块数据拼成Markdown（取数在cli.py编排） |
| chart.py | 绘图基础模块，`draw` 按模板出PNG，仅用matplotlib，零 import market-data |
| resample.py | 行情周/月本地聚合 |
| formula_library/verified-formulas.jsonl | 已验证公式，人工锚定，AI 优先检索 |
| formula_library/catalog.jsonl | 全量30281条指标索引，内容不可靠，禁止查询 |
| data/ifind_workspace.xlsx | 专用工作簿，只含 data 页（纯取数通道，永不保存） |

命令分三类：取数 `fetch_scene`（固定场景）、`get`（按指标取一个数，优先用这个）、`find`（搜指标，不知道指标叫什么时先搜）、`search`（查证券代码）、`lookup`/`run`/`text`（场景没有才用）；一键报告 `report`（取数、换算、绘图、拼Markdown、落盘）；绘图 `draw`；帮助 `help`/`help_scene`/`help_indicators`/`scenes`/`scene_info`；Excel生命周期 `open`/`status`/`close`。先跑 `{"cmd":"help"}` 看导航。

## 指标find与get

不知道某个数据在库里叫什么，先 `find` 搜；搜到后按用法 `get` 取数。

搜索范围覆盖全部业务数据能力，不按存储形态割裂：已验证单格公式807条、固定场景、
报表函数型（指数成分股、指数进出记录）、自定义派生指标（毛利率）、指标组、探最新报告期。

```bash
echo '{"cmd":"find","keyword":"毛利率"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
echo '{"cmd":"get","indicator":"毛利率","code":"002796.SZ","report_date":"2026-09-30"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
```

`get` 的 `indicator` 可以写中文名（毛利率、固定资产、利润表常用科目），也可以写指标码
（ths_operating_cost_stock）。类型自动分派，调用方不用判断底层是公式、多候选、派生还是场景。

一次取一组：

```bash
echo '{"cmd":"get","indicator":"利润表常用科目","code":"002796.SZ","report_date":"2026-09-30"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
```

返回 `members` 逐项给值；组内派生指标（毛利润、毛利率）已算好，不用再加工。

两条要注意的：

- 跨市场同名指标（营业利润、总股本、收盘价等）按代码后缀自动择市场。库里没有该市场版本时
  明确报错说明缺哪个市场，不会拿别的市场公式套。
- `find` 里 `kind` 可限定类型：`derived`/`group`/`select`/`excel`/`scene`/`table`/`special`。

新增自定义指标：往 `formula_library/derived-indicators.jsonl` 加一行，写 `name`、`expr`
（四则运算，变量名是 `deps` 里的 `label`）、`deps`、`unit`、`decimals`，即刻可搜可调。

## 用法

AI 取数流程：

1. 不确定数据在库里叫什么：先 `find` 搜。它覆盖公式、场景、报表函数、自定义指标与指标组。
2. 指标级、要一个数或一组数：`get` 取，类型自动分派，拿回的是加工好的结果。
3. 整表、一次要很多字段：`fetch_scene` 按场景取（三表、行情、工商信息、十大股东等）。
4. 以上都没有：`lookup` 查公式，用 `run`/`text` 把原始公式原样传给 Excel 执行。
   新公式按[公式来源与录入流程](formula_library/README.md#批量公式录入与验证流程)核对插件原文后入库，
   入库后 `find`/`get` 即可用。

CLI 示例（stdin JSON → stdout JSON）：

在仓库根目录执行（必须设 PYTHONPATH=src 并用项目 venv）：

```bash
echo '{"cmd":"lookup","keyword":"净利润","limit":5}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
```

`run`/`text` 同理，把上面 JSON 换成 `{"cmd":"run","matrix":[...]}` 或 `{"cmd":"text","formulas":[...]}`；用完可发 `{"cmd":"close"}` 不保存关闭专用 Excel。

另有 `{"cmd":"status"}`（只读查状态，未打开时不启动 Excel）与 `{"cmd":"open"}`（打开或复用专用工作簿）。

## 一键完整报告

一条命令出单公司全量报告：取数、单位换算、绘图、拼Markdown、落盘到指定目录。

```bash
echo '{"cmd":"report","code":"002796.SZ","output":"D:\导出目录"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
```

可选参数：`company`（省略则从工商信息取证券简称）、`end_date`（数据截止交易日，默认今天）、`chart_start`（行情起点，默认2016-01-01）、`events`（事件CSV路径，有则画进行情图，没有则不画）。

产出：一份 `公司-报告骨架-<时间戳>.md`、14个板块CSV、一张 `公司-行情图.png`（总市值左轴、前复权收盘价右轴，有事件CSV则标注）。

报告期固定7列：最新报告期 + 去年同期（若最新非年报）+ 最近年度。财报摘要和附录统一万元口径（取整），摘要亿元保留2位小数。预测年份按年报推：最新年报未出则预测当年，已出则预测次年及后两年。

方案与决策见[全量报告命令方案](../../docs/iFinD-CLI全量报告命令方案-2026-11-25.md)。

### 单板块取数

需要单独看某个板块时用 `fetch_scene`，带 `export_path` 落CSV：

```bash
echo '{"cmd":"fetch_scene","scene":"分红","code":"002796.SZ","dims":{"year":["2025","2024"]},"export_path":"分红.csv"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
```

财报类场景传 `report_dates` 列表可一次取回多期。可用场景跑 `{"cmd":"scenes"}` 查看。

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
