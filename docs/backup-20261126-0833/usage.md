# iFinD Excel CLI使用说明

给AI用的取数入口。一句话：说清要什么数据，不用管公式怎么拼。

## 先看有什么

```
{"cmd":"help"}
```

先跑 `help` 看全部场景和导航（返回值里的 `start_here` 按需求直接告诉你调哪个命令）。不确定用哪个先看它。

## 查证券代码

不知道代码时先搜，返回的 `ifind_code` 可以直接复制到取数命令。`kind` 必须指定（股票/指数/外汇），工具不替你猜渠道：

```
{"cmd":"search","keyword":"腾讯","kind":"股票"}
{"cmd":"search","keyword":"沪深300","kind":"指数"}
{"cmd":"search","keyword":"美元人民币","kind":"外汇"}
```

股票走东财搜索（港股四位、正股优先，权证/R股/票据等非正股和非股票类型直接过滤掉），指数查本地12741条指数总表，外汇查汇率表。每页最多10行，用 `offset` 翻页：

```
{"cmd":"search","keyword":"红利","kind":"指数","offset":10}
```

返回里 `total` 是命中总数，`has_more` 表示还有下一页。指数和外汇命中时 `row` 返回该行全部字段。

## 四族场景

| 族 | 是什么 | 变化在哪 | 现有场景 |
|---|---|---|---|
| 行情 | 按交易日连续更新的数值 | 复权方式、要哪些量、频率 | 历史行情、估值快照 |
| 财报 | 按报告期更新的数值 | 累计还是单季、要哪些科目 | 资产负债表、利润表、现金流量表、利润表单季、现金流量表单季 |
| 基本信息 | 单点时刻的状态 | 问哪个时点 | 工商信息、十大股东 |
| 零散命令 | 一次返回一张特定报表 | 参数各不相同 | 指数成分股、指数进出记录 |

## 怎么取数

统一入口 `fetch_scene`：

```
{"cmd":"fetch_scene","scene":"历史行情","code":"600519.SH"}
{"cmd":"fetch_scene","scene":"历史行情","code":"600519.SH","period":"weekly"}
{"cmd":"fetch_scene","scene":"历史行情","code":"600519.SH","period":"monthly","start":"2024-01-01","end":"2024-12-31"}
{"cmd":"fetch_scene","scene":"工商信息","code":"600519.SH"}
{"cmd":"fetch_scene","scene":"十大股东","code":"600519.SH","report_date":"2024-12-31"}
{"cmd":"fetch_scene","scene":"指数成分股","idx_code":"000688.SH","trade_date":"20251124"}
{"cmd":"fetch_scene","scene":"指数进出记录","iv_zsdm":"000300.SH","iv_sdate":"20251001","iv_edate":"20261124"}
```

指数进出记录底层固定取全部状态，返回结果按「状态」列（纳入/剔除）自行筛选。

取数前想知道某场景要什么参数：

```
{"cmd":"scene_info","scene":"历史行情"}
{"cmd":"help_scene","scene":"指数成分股"}
```

## 各场景的默认值与常见改法

| 场景 | 默认 | 常见改法 |
|---|---|---|
| 历史行情 | 最近14个日历日、前复权、日线 | 改 `start`/`end` 换区间（要看长历史自己传 `start`）；`params` 里改 `adjust`：100不复权、107后复权、108前复权；`period` 选 daily/weekly/monthly，先取日K再本地聚合 |
| 估值快照 | 今天 | `report_date` 指定某天 |
| 三表与单季 | 最新已披露报告期 | `report_date` 指定报告期，用季末日如 `2025-09-30` |
| 工商信息 | 今天 | 带日期的字段用 `report_date` |
| 十大股东 | 最新一期 | `report_date` 指定报告期末 |
| 分红 | 最近5个年度 | `dims` 传 `{"year":["2025","2024"]}` 指定年度 |
| 历史估值 | 最近5个年末 | `dims` 传 `{"date":["2025-12-31"]}` 指定日期 |
| 指数成分股 | 今天 | 用 `code` 传指数代码；`trade_date` 指定日期（YYYYMMDD） |
| 指数进出记录 | 最近一年 | 用 `code` 传指数代码；`iv_sdate`/`iv_edate` 改区间（YYYYMMDD） |

默认时间口径按数据性质分三类：财报类（季报更新）取最新已披露报告期，如 2026-09-30；
行情类（时间序列）取最近14个日历日，中间剔除非交易日；公司信息类（不随时间变）取今天。
都不用手动传日期。

## 需要知道的三件事

一、行数超过200自动写CSV并返回文件路径，返回里只留前20行示意。要指定路径就传 `export_path`。

二、历史行情已剔除周末与节假日，但停牌日保留、量额记0。判据是不前推收盘价大于0，与market-data口径一致。周/月线由日线本地聚合：开=周期首日、收=末日、高低=极值、量额=求和；周线按周五、月线按月末归档。

三、指数成分股返回的「生效日期」是这批权重开始生效的日子，不是查询日。指数按季度调仓，所以查询日与生效日期常常不同，两个都要看。

四、取到0或空但确认该数据应存在时，先执行 `{"cmd":"close"}` 关掉专用工作簿再重试。iFinD 插件会缓存公式结果，2026-11-25 实测：探测 600519.SH 最新报告期重启前返回 0，close 后重开同一公式返回 2026-09-30。这类返回会带 `hint` 提示，看到就照做。

四、港股代码必须是四位（0700.HK），传五位（00700.HK）会静默返回错值或0。用 `search` 查代码最稳，返回的 ifind_code 直接可用，不要自己改位数。

五、财报类场景（三表、单季表、十大股东）不传 `report_date` 时自动探最新已披露期，返回里给出 `report_date`；探不到明确报错要求指定。固定资产、在建工程已合并多候选，自动取合计与单科目较大值。

## 固定报告导出与绘图

一个板块一份CSV：`fetch_scene` 带 `export_path` 写指定路径，每个代码单独导按单 `code` 调用。CSV齐后 `export_report` 拼固定Markdown骨架，只拼装不取数，缺的板块留空节标注。IPO信息、分红、营收结构、盈利预测四块暂无场景，会标"未取到数据，待补"。

```
{"cmd":"fetch_scene","scene":"工商信息","code":"002796.SZ","export_path":"数据/工商信息.csv"}
{"cmd":"export_report","company":"世嘉科技","code":"002796.SZ","sections":{"工商信息":"数据/工商信息.csv"},"output":"骨架.md"}
```

`draw` 读已导出的行情CSV出PNG，不取数，四个模板：

```
{"cmd":"draw","template":"kline_volume","data_path":"数据/历史行情.csv","output":"行情.png"}
```

| 模板 | 内容 | 参数 |
|---|---|---|
| kline_volume | K线+量+MA5/10/20/60 | ma_windows、log_scale |
| kline_log_volume | 同上，对数轴，含0或负值自动退回 | ma_windows |
| close_mcap_events | 双轴总市值+前复权收盘价+事件 | events、price_col、mcap_col |
| close_line_keypoints | 折线+最高/最低/最新+回撤高低点 | drawdown_threshold（默认0.30） |

`events` 为 date,description 两列CSV或 `[{"date":"...","description":"..."}]`，事件日对齐到最近交易日。绘图视觉规范由 chart.py 统一固定。

## 底层能力

需要库里没有的指标，或要试新公式时：

```
{"cmd":"lookup","keyword":"营业收入"}         查单个指标
{"cmd":"help_indicators","market":"股票全部指标"}  看某市场有哪些指标
{"cmd":"help_indicators","keyword":"收盘价"}      按关键词找
{"cmd":"run","matrix":[[...]]}                直接执行拼好的公式矩阵
{"cmd":"text","formulas":["..."]}             取文本字段
```

Excel生命周期：

```
{"cmd":"open"}{"cmd":"status"}{"cmd":"close"}
```

并发调用同一个CLI时自动排队，共用一个Excel，不需要调用方处理。

## 加新场景

在 `scenes/` 下加一个JSON，CLI代码不用动。`kind` 缺省是矩阵形态。

矩阵形态（一个指标一个值，可有日期维度）：

```json
{
  "name": "场景名",
  "description": "一句话说明，写清换什么参数改什么",
  "code_required": true,
  "defaults": {"adjust": 108},
  "dims": {"date_range": true},
  "fields": [
    {"label": "收盘价", "indicator": "ths_close_price_stock", "params": {"type": "108"}}
  ]
}
```

字段支持 `candidates` 多候选按 `pick` 取值（现支持 `max`，用于固定资产取较大值这类分流），`hidden` 表示只用于筛选不出现在结果里。

表函数形态（一条公式返回整张表）：

```json
{
  "name": "场景名",
  "kind": "table",
  "function": "THS_RPT",
  "report": "idx_weight",
  "inputs": ["trade_date", "idx_code"],
  "fields": ["weight_date", "ths_code", "sec_name", "weight"],
  "field_labels": ["生效日期", "同花顺代码", "证券名称", "权重"],
  "tail": ["", "rows=1", "cols=1"]
}
```

表函数的公式全内联，不引用单元格。`rows`/`cols` 填什么都不影响返回行数，那个空参数不能省。

## 出问题怎么判断

| 现象 | 原因 | 处理 |
|---|---|---|
| 报「无法连接专用工作簿」并提示正在编辑单元格 | Excel里有未结束的编辑 | 自动处理，无需人工 |
| 取数超时 | Excel累积了坏状态 | `close` 再 `open` 重试；实测超时后重启即可恢复 |
| 报「指标未入库」 | 场景引用的指标不在公式库 | 需要补库，不能猜 |
| 返回0或空 | 该证券在当天无数据，或参数不适用该市场 | 先核对代码格式与市场 |

不知Excel是否开着，先跑 `{"cmd":"status"}`，未打开时不会启动它。

## 指数表更新

`search` 查指数用的是 `formula_library/指数总表.csv`（12741条，来自同花顺导出的每个类型sheet去重合并）。指数有更新时：把新导出的xlsx覆盖 `formula_library/同花顺股票指数.xlsx`，然后跑：

```
python src/ifind_excel_tool/formula_library/build_index_table.py
```

脚本会重新生成指数总表，并打印各类型数量、去重数、合计sheet校验结果。常用指数清单在 `常用指数基本信息.csv`，更新它也会反映到总表的「常用」标记里。
