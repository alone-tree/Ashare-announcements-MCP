# iFinD CLI 框架说明

日期：2026-11-26
适用：`src/ifind_excel_tool/` 全包

这份文档只回答三件事：整个工具分成哪几块、每块管什么、要加东西时放哪。
各块的具体格式与参数在各自的 `README.md` 里，本文不复述。

## 一、五块与目录

| 块 | 目录 | 谁提供内容 | 这块管什么 |
|---|---|---|---|
| 第一块 公式录入 | `formulas/` | 用户给 iFinD 插件原文，AI 按规范录入 | iFinD 公式本身：单点公式、批量公式、科目别名 |
| 第二块 业务定义 | `indicators/` | 用户提业务要求，AI 写清楚并保证能取到 | 衍生科目（怎么算）、科目组合（打包哪些）、股票聚合 |
| 第三块 额外功能 | `features/` | 用户按需提，一事一议 | 绘图、报告。每项功能自己取数、自己加工、自己出成果 |
| 第四块 AI 交互 | `interface/` + `cli.py` | AI 自主维护 | 检索、帮助、命令分派，保证调用的 AI 不被数据淹没 |
| 第五块 执行层 | `execution/` | AI 自主维护 | 与 Excel 直接交互：COM、分块、超时、重试、僵死诊断 |

依赖方向只有一条：第四块依赖第二、三块，第二、三块依赖第一、五块。下层不知道上层存在。

```mermaid
flowchart TB
    CLI["cli.py 入口<br>只做命令分派"]
    INT["第四块 interface<br>检索 · 帮助 · 证券代码"]
    IND["第二块 indicators<br>衍生科目 · 科目组合 · 取数 · 聚合"]
    FEA["第三块 features<br>绘图 · 报告"]
    FOR["第一块 formulas<br>单点公式 · 批量公式"]
    EXE["第五块 execution<br>Excel COM 与鲁棒性"]

    CLI --> INT
    CLI --> IND
    CLI --> FEA
    INT --> IND
    IND --> FOR
    IND --> EXE
    FEA --> IND
    FEA --> EXE
```

## 二、对 AI 只有一个概念：科目

不论底层是公式、衍生计算还是打包，对调用的 AI 都叫「科目」，检索和调用方式完全一样。

| 底层形态 | 说明 | 数据在哪 |
|---|---|---|
| 单点公式 | 一条 iFinD 公式取一个值，如某天某股前复权收盘价 | `formulas/single.jsonl` |
| 批量公式 | 一条公式让 Excel 函数把整张表写到下方，如指数成分股 | `formulas/batch.jsonl` |
| 衍生科目 | 用已有科目算出来的科目，如毛利率 | `indicators/derived.jsonl` |
| 科目组合 | 若干科目打包，一次取回，如利润表常用科目、十大股东 | `indicators/packages.jsonl` |
| 多候选取值 | 同一含义有多个候选，取较大值，如固定资产 | 写在组合的字段里，自动暴露为独立科目 |
| 特殊能力 | 非取数查询，如探最新报告期 | 代码内置 |

使用流程只有两步：`find` 搜科目拿用法，`get` 按用法取数。

## 三、要加东西放哪

| 你想加 | 放哪 | 要写代码吗 |
|---|---|---|
| 一个新指标（iFinD 已有公式） | `formulas/single.jsonl` 一行 | 不用 |
| 一个批量取数的公式（一次出整表） | `formulas/batch.jsonl` 一行 | 不用 |
| 给科目起常用短名 | 该条目的 `aliases` 字段 | 不用 |
| 一个衍生科目（如净利率） | `indicators/derived.jsonl` 一行，写依赖与算式 | 不用 |
| 一个科目组合（常用科目、整张表） | `indicators/packages.jsonl` 一行，写字段与维度 | 不用 |
| 一种新的图 | `features/chart.py` 加模板 | 要 |
| 一份新的报告版式 | `features/report_command.py` 加编排 + `features/report.py` 加排版 | 要 |
| 一种新的检索排序或展示 | `interface/search.py` | 要 |
| Excel 侧的新问题（超时、崩溃、残留） | `execution/engine.py` | 要 |

绝大多数「加数据」停在第一、二块，只加 JSON，不碰代码。

## 四、几条硬规则

- 别名优先：科目有中文别名时展示与检索都用别名；没有别名才用 iFinD 原名。英文别名只参与匹配，不用于展示。
- 不猜参数：公式模板缺参数时直接报错，不填默认值猜测。iFinD 参数语义分接口分市场，猜错就是错数。
- 不推算上游没有的信息：上游没给的字段不补、不推算。
- 分层不越界：CLI 不直接操作 Excel，执行层不知道有「毛利率」这种东西。
- 数据来源纪律见 [公式录入规范](<../src/ifind_excel_tool/formulas/README.md>)：只有用户提供的插件原文与人工确认的实测值可作权威来源。
- `formulas/legacy/catalog.jsonl` 除用户明确要求外任何情况下都不查，内容错误混淆。

## 五、默认时间口径

按数据性质分三类，都不需要调用方传日期：

| 类别 | 默认 |
|---|---|
| 财报类（三表、单季、营收结构、衍生科目、财报类组合） | 最新已披露报告期，取不到时明确报错 |
| 行情类（时间序列） | 最近 14 个日历日，中间剔除非交易日 |
| 公司信息类（不随时间变） | 今天 |

另有按需的默认：分红最近 5 个年度、历史估值最近 5 个年末、指数进出记录最近一年。

2016 年至今只是报告功能画图用的起点，不是取数默认。

## 六、目录全景

```
src/ifind_excel_tool/
├── cli.py                     入口：命令分派
├── README.md                  包总览与用法
├── data/ifind_workspace.xlsx  专用工作簿
├── formulas/                  第一块 公式录入
│   ├── README.md              录入规范与数据来源纪律
│   ├── library.py             加载、渲染、批量公式拼装
│   ├── single.jsonl           单点公式
│   ├── batch.jsonl            批量公式
│   ├── notes.jsonl            按路径生效的通用说明
│   ├── tools/                 录入与校对工具
│   └── legacy/catalog.jsonl   禁用，禁止查询
├── indicators/                第二块 业务定义
│   ├── README.md              定义规范
│   ├── definitions.py         登记表与解析
│   ├── packages.py            组合展开与还原
│   ├── fetch.py               统一取数
│   ├── aggregate.py           股票聚合（周月线）
│   ├── derived.jsonl          衍生科目
│   └── packages.jsonl         科目组合
├── features/                  第三块 额外功能
│   ├── README.md
│   ├── chart.py               绘图模板
│   ├── report.py              报告排版
│   └── report_command.py      报告编排
├── interface/                 第四块 AI 交互
│   ├── README.md
│   ├── search.py              科目检索
│   ├── securities.py          证券代码检索
│   ├── help.py                帮助
│   └── data/                  检索用指数与汇率表
└── execution/                 第五块 执行层
    ├── README.md
    └── engine.py              Excel COM 与鲁棒性
```

## 七、历史方案稿

本框架之前的 12 份方案稿已完成使命，内容已并入本文与各块说明，原文见 Git 历史与
`docs/backup-20261126-0833/`。变动经过记在[决策记录](决策记录.md)。
