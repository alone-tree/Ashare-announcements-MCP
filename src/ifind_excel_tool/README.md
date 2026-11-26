# ifind_excel_tool：iFinD Excel 取数工作台

纯 CLI，stdin JSON → stdout JSON，顶层字段 `cmd`。与 market_data_mcp 平级，零 import 依赖。

整体分五块，框架与「加东西放哪」见 [框架说明](../../docs/iFinD-CLI框架说明.md)。本文件只给入口与用法。

| 块 | 目录 | 这块是什么 |
|---|---|---|
| 第一块 公式录入 | `formulas/` | iFinD 公式本身，见[录入规范](formulas/README.md) |
| 第二块 业务定义 | `indicators/` | 衍生科目、科目组合、取数，见[定义规范](indicators/README.md) |
| 第三块 额外功能 | `features/` | 绘图、报告，见[功能说明](features/README.md) |
| 第四块 AI 交互 | `interface/` | 检索、帮助、证券代码，见[交互说明](interface/README.md) |
| 第五块 执行层 | `execution/` | Excel COM 与鲁棒性，见[执行层说明](execution/README.md) |

## 快速上手

在仓库根目录执行，必须设 `PYTHONPATH=src` 并用项目 venv：

```bash
# 不知道数据叫什么，先搜
echo '{"cmd":"find","keyword":"毛利率"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe -m ifind_excel_tool.cli

# 搜到后直接取
echo '{"cmd":"get","indicator":"毛利率","code":"002796.SZ","report_date":"2026-09-30"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe -m ifind_excel_tool.cli

# 一页看清有什么
echo '{"cmd":"help"}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe -m ifind_excel_tool.cli
```

## 命令

| 命令 | 用途 |
|---|---|
| `find` | 搜科目（指标、衍生科目、组合、批量公式、特殊能力），返回带用法 |
| `get` | 按科目取一个值或一组值，类型自动分派 |
| `fetch_package` | 按科目组合取，支持多期、维度覆盖、周月聚合、导出 CSV |
| `fetch_batch` | 按批量公式取整表 |
| `search` | 查证券代码，必须指定 kind=股票/指数/外汇 |
| `packages` / `package_info` | 列组合、看某组合的字段与参数 |
| `help` / `help_indicators` | 总览、列原始公式 |
| `report` | 一条命令出完整报告：取数、换算、绘图、拼 Markdown、落盘 |
| `draw` | 按模板绘图，读已导出的行情 CSV |
| `lookup` | 查还没登记成科目的原始公式 |
| `run` / `text` | 直接执行公式矩阵或文本公式，逃生舱 |
| `open` / `status` / `close` | 专用工作簿生命周期 |

## 科目是什么

对调用的 AI 来说只有一种东西：科目。底层是原始公式、批量公式、衍生计算还是打包，
检索和调用方式完全一样。

```bash
# 一个数
echo '{"cmd":"get","indicator":"毛利率","code":"002796.SZ"}' | ...

# 一组数
echo '{"cmd":"get","indicator":"利润表常用科目","code":"002796.SZ"}' | ...

# 一段序列（默认最近 14 个日历日）
echo '{"cmd":"fetch_package","package":"历史行情","code":"600519.SH"}' | ...

# 整张表
echo '{"cmd":"fetch_batch","batch":"指数成分股","code":"000300.SH"}' | ...
```

## 默认时间口径

不需要手动传日期：

| 类别 | 默认 |
|---|---|
| 财报类（三表、单季、营收结构、衍生科目、财报类组合） | 最新已披露报告期 |
| 行情类（时间序列） | 最近 14 个日历日，剔除非交易日 |
| 公司信息类（不随时间变） | 今天 |

另按需：分红最近 5 个年度、历史估值最近 5 个年末、指数进出记录最近一年。
报告画图的起点 2016 年至今是报告功能自己的参数，不是取数默认。

## 取到 0 时先看这里

iFinD 插件会缓存结果，0 不一定表示上游没有数据。实测 600519.SH 探测最新报告期，
重启前返回 0，`close` 关掉专用工作簿重开后返回 2026-09-30。

取数结果全为 0 时会带 `hint` 字段，看到就执行一次 `{"cmd":"close"}` 再重试。

## 报告与绘图

```bash
echo '{"cmd":"report","code":"002796.SZ","output":"导出目录"}' | ...
echo '{"cmd":"draw","template":"kline_volume","data_path":"行情.csv","output":"图.png"}' | ...
```

报告产出：一份 Markdown 报告骨架、各板块 CSV、一张行情图。绘图模板与参数见[功能说明](features/README.md#绘图)。
