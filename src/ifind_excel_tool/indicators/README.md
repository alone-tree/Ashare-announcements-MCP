# 第二块 业务定义

这块回答「有哪些科目、每个科目怎么取」。用户在这里提业务要求，AI 负责写清楚并保证能取到。

## 两类定义

| 文件 | 是什么 | 例子 |
|---|---|---|
| `derived.jsonl` | 衍生科目：用已有科目算出来的新科目 | 毛利润、毛利率 |
| `packages.jsonl` | 科目组合：若干科目打包，一次取回 | 利润表常用科目、工商信息、十大股东、历史行情 |

## 衍生科目字段

```json
{"name":"毛利率","aliases":["gross_margin"],"description":"（营业总收入−营业成本）÷营业总收入",
 "unit":"%","decimals":2,
 "expr":"(营业总收入 - 营业成本) / 营业总收入 * 100",
 "deps":[{"label":"营业总收入","indicator":"ths_operating_total_revenue_stock","params":{"type":"100"}},
         {"label":"营业成本","indicator":"ths_operating_cost_stock","params":{"type":"100"}}]}
```

| 字段 | 含义 |
|---|---|
| name / aliases | 科目名与常用别名，规则同第一块 |
| description | 一句话说明这个科目是什么，检索要靠它 |
| expr | 算式，只允许四则运算，变量名是 deps 里的 label |
| deps | 依赖的原始科目，每项写 label 与指标码 |
| unit / decimals | 单位与保留小数位 |

算式只走四则运算白名单，不执行任意代码。缺依赖或分母为零时该值不可用并给原因，不回退成 0。

## 科目组合字段

```json
{"name":"利润表常用科目","description":"看盈利能力常用的一组","code_required":true,
 "date_kind":"report",
 "fields":[{"label":"营业总收入","indicator":"ths_operating_total_revenue_stock","params":{"type":"100"}},
           {"label":"毛利率","derived":"毛利率"}]}
```

| 字段 | 含义 |
|---|---|
| name / aliases | 科目名与别名。它在检索里就是一个科目 |
| description | 说明，检索会匹配这里 |
| date_kind | `report` 表示报告期类，缺日期时自动探最新已披露期 |
| defaults | 默认参数，支持 `today`、`today-Nd`、`__recent_years:N__`、`__recent_year_ends:N__` |
| dims | 维度取值，如 `{"year":[...]}`、`{"date":[...]}`、`{"rank":[1..10]}`、`{"date_range":true}` |
| fields | 字段列表，每项写 label 加 `indicator`（指标码）、`derived`（衍生科目名）或 `candidates`（多候选） |
| pick | 多候选取值规则，现支持 `max` |
| resample | 有则支持 period=weekly/monthly，由日线本地聚合 |
| drop_non_trading_field | 剔除非交易日用的判定字段 |
| group / hidden / unit | 字段级：分组标题、只用于筛选不进结果、单位 |

字段可以引用衍生科目；取数时会自动展开依赖、算好再返回，调用方不用关心。

多候选取值（如固定资产=max(固定资产合计, 固定资产)）写在字段的 `candidates` 里，取数时自动暴露成独立科目，不需要单独登记。

## 组合与衍生科目的关系

组合的字段可以放衍生科目，衍生科目的 deps 只能放原始公式。这样不会出现循环依赖，也不需要额外校验。

## 加东西的口径

- 新增一个衍生科目：只加一行 JSON，写清 expr 与 deps，改完立刻能搜能取。
- 新增一个组合：只加一行 JSON，写清 fields 与默认值。
- 一旦要改「算不出来时的行为」「新的聚合方式」，那属于这层的代码（`fetch.py`、`packages.py`、`aggregate.py`），改前先确认这是业务口径问题不是代码缺陷。

## 文件职责

| 文件 | 职责 |
|---|---|
| `definitions.py` | 登记表：加载、构建统一索引、按名称解析 |
| `packages.py` | 组合展开成公式矩阵、结果还原成记录、写 CSV |
| `fetch.py` | 统一取数入口，按科目类型分派，衍生计算，探最新报告期 |
| `aggregate.py` | 股票聚合：日线聚合成周线月线 |
