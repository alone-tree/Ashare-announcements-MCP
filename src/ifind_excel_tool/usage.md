# iFinD Excel CLI使用说明

给AI用的取数入口。一句话：说清要什么数据，不用管公式怎么拼。

## 先看有什么

```
{"cmd":"help"}
```

按四族列出全部场景。不确定用哪个先跑这个。

## 四族场景

| 族 | 是什么 | 变化在哪 | 现有场景 |
|---|---|---|---|
| 行情 | 按交易日连续更新的数值 | 复权方式、要哪些量、频率 | 历史行情、估值快照 |
| 财报 | 按报告期更新的数值 | 累计还是单季、要哪些科目 | 资产负债表、利润表、现金流量表、利润表单季、现金流量表单季 |
| 基本信息 | 单点时刻的状态 | 问哪个时点 | 工商信息、十大股东 |
| 零散命令 | 一次返回一张特定报表 | 参数各不相同 | 指数成分股 |

## 怎么取数

统一入口 `fetch_scene`：

```
{"cmd":"fetch_scene","scene":"历史行情","code":"600519.SH"}
{"cmd":"fetch_scene","scene":"工商信息","code":"600519.SH"}
{"cmd":"fetch_scene","scene":"十大股东","code":"600519.SH","report_date":"2024-12-31"}
{"cmd":"fetch_scene","scene":"指数成分股","idx_code":"000688.SH","trade_date":"20251124"}
```

取数前想知道某场景要什么参数：

```
{"cmd":"scene_info","scene":"历史行情"}
{"cmd":"help_scene","scene":"指数成分股"}
```

## 各场景的默认值与常见改法

| 场景 | 默认 | 常见改法 |
|---|---|---|
| 历史行情 | 2016年至今、前复权、日线 | 改 `start`/`end` 换区间；`params` 里改 `adjust`：100不复权、107后复权、108前复权 |
| 估值快照 | 最新交易日 | `report_date` 指定某天 |
| 三表与单季 | 最新已披露报告期 | `report_date` 指定报告期，用季末日如 `2025-09-30` |
| 工商信息 | 今天 | 带日期的字段用 `report_date` |
| 十大股东 | 最新一期 | `report_date` 指定报告期末 |
| 指数成分股 | 今天 | `trade_date` 指定日期（YYYYMMDD） |

## 需要知道的三件事

一、行数超过200自动写CSV并返回文件路径，返回里只留前20行示意。要指定路径就传 `export_path`。

二、历史行情已剔除周末与节假日，但停牌日保留、量额记0。判据是不前推收盘价大于0，与market-data口径一致。

三、指数成分股返回的「生效日期」是这批权重开始生效的日子，不是查询日。指数按季度调仓，所以查询日与生效日期常常不同，两个都要看。

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
