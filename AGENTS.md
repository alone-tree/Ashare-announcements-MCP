# 项目协作说明（AGENTS.md）

> **本文件是项目的协作规则、文档地图与关键约定总纲。** 操作本项目之前，先阅读本文件和 `PROJECT.md`。
> 细枝末节（接口返回结构、逐字段契约）与决策记录在对应文档，**但关键约定、工具清单、铁律必须在本文件可见**。同一内容只在一个文档记录，新增内容先确认归属。

## 一、项目是什么

个人投资研究工具，仓库内含**三个并列的 MCP**：

| | 公告 MCP | market-data MCP | chart MCP |
|---|---|---|---|
| 定位 | 公告/提交文档（非结构化）的发现、定位、阅读 | 行情/财报/指标/概况（结构化）数据获取 | 行情绘图（K线/折线） |
| 数据源 | A/B/H 股=东方财富；美股=SEC EDGAR；LOCAL-=本地材料 | 行情=新浪单源；财报=东财 datacenter；股本/美股后复权=iFinD | 复用 market-data get_quote（不复制取数代码） |
| 状态 | **已实现、完善**（不要动坏） | **行情 + 财报三表已实现**；财务比率/公司概况待实现 | **已实现**（get_quote_chart，2026-08） |
| 文档 | `docs/AH公告与互动问答改造方案.md`（公告侧唯一权威） | `docs/market-data架构设计.md`（决策）+ `字段与数据源支持情况.md`（客观能力） | `docs/chart-MCP绘图工具设计.md`（任务交接+全部决策） |

克制、数据准确真实、维护简单；不为假设中的需求增加抽象或字段。个人工具，不追求大而全。

## 二、工具总览与开发要点

### 公告 MCP（5 个 MCP 工具 + CLI 批处理入口）

| 工具 | 要点 |
|---|---|
| `establish_company(keyword, action="check")` | 关键词查询，只读不建缓存，忠实返回东财前 20 条候选，不过滤/不归组/不补查；返回总命中数与实际返回数，超限提示用更精确关键词 |
| `establish_company(codes=[...], action="establish")` | 明确代码列表建档；接受一个代码或 A+H 两个；不自动搜索/补全另一市场代码；一次获取全部 A/H 公告 + A 股互动问答；保存名称与 A/H 映射；**不用 `-R`/`-WR` 人民币柜台代码** |
| `query_announcements` | 首次全量建档、之后增量补全；每页 50 条；日期/关键词/翻页只作用于本地缓存 |
| `read_announcement` | 不传 `start_page`=检测模式（≤20 页全文 / >20 页画像+前 5 页预览）；传 `start_page`=精读（默认 `return_pages=20`，不设上限，可一次读完全文）；扫描页 OCR |
| `search_announcement` | 逐页索引检索，返回命中页和片段；扫描页按需 OCR 并写回缓存 |
| `query_interactions` | 互动问答（仅 A 股），全量/增量 |

CLI（`python -m ashare_announcements_mcp.cli`，stdin JSON → stdout JSON）：`query_batch`/`read_batch`/`search_batch`/`query_interactions_batch`，与 MCP 工具一一对应、能力一致。**CLI 顶层请求字段是 `tool`**（不是 `action`），响应字段也是 `tool`；建档子动作参数用 `action`（check/establish）。

### market-data MCP（4 个工具，设计已定稿）

| 工具 | 要点 |
|---|---|
| `get_quote` | 行情；code 带后缀、vars 字段列表（date 恒留）、adjust=raw/hfq/qfq、period=daily/weekly/monthly（周/月由日线现算）、**start_date 特殊值 "all"（end 空=全部数据；end 指定=只取 ≤end 早期数据，2026-08-10 为 chart 增加）**、超长(>200 行)自动导出、export_path 指定 CSV。**缓存为字段级 9 个 json**（open/high/low/close/close_hfq/volume/amount/total_shares/floating_shares，items `[{date,value,source}]` 每字段同日期仅一条），**每字段唯一数据源**（A/北交所流通股本=新浪、港美股=ifind 等），派生（qfq/市值/换手率/周月/hfq OHL 还原）全现算；**覆盖判定带探测状态机**（盘后 verified_until 覆盖周末/节假日、盘中续探零请求，见架构文档 §1.8） |
| `get_financial_statements` | 三表；科目名原样不翻译、不做跨市场映射；`amount_basis` 必填（cumulative/single），30 天缓存+强制刷新，同报告期多版本，三表批次全有或全无；single 不返回 EPS/每股股息/加权平均股数等非加总科目 |
| `get_financial_ratios` | 财务衍生指标，东财英文列名原样 |
| `get_company_profile` | 概况/分红/盈利预测，sections 可选 |

market-data 核心原则：**字段为中心、来源可插拔**；**强制市场后缀代码**（`.SZ/.SH/.HK/.US/.BJ`，脚本按后缀路由、禁止按位数猜市场）；**行情单源无回退**（raw=新浪；hfq=A/港新浪+美股 iFinD，失败即失败不混源）；下载到缓存+返回元信息、缓存优先增量更新。

## 三、已确认的产品要求与约定（公告侧，完整版见方案文档）

### 三类公司与主键

- 纯 A 股：A 股公告档案 + 互动问答档案；纯港股：港股公告档案（无互动问答）；A+H：识别并保存两个市场证券代码及东财 `InnerCode`，共用同一公司档案。
- 公司唯一主键：有 A 股用 A 股代码，纯港股用港股代码；目录保持 `cache/{证券代码}/`。

### 公告与互动问答

- A/H 公告按证券代码分别存缓存，查询时内存合并排序筛选；**A/H 同一事项不同 `art_code`/标题不得去重删除**。
- 互动问答单独建档，不和公告混合；首次全量、后续增量。

## 四、已验证的上游边界（公告侧）

- 东财搜索返回 A 股/港股/人民币柜台/权证/期货/ADR 等多种真实候选；`check` 不过滤，由 AI 根据返回字段选择。
- 数字代码搜索是模糊匹配（`03308` 可能命中 `603308`）：数字代码先按 `Code` 精确匹配，再用返回 `Name` 补查同名证券。
- **港股公告必须按当前证券 `InnerCode` 过滤**（代码可能被旧公司复用：03308 混金鹰商贸、00300 混昆明机床）。
- 互动问答翻页是 POST `interface/GetData.aspx`，不是页面 URL 的 `page=` 参数。
- PDF 下载后必须检查响应以 `%PDF-` 开头（防临时反爬页面被当 PDF 缓存）；PDF 仅实际阅读时下载，建档时不批量下载。
- 判定策略：**SecurityTypeName 白名单 + TypeUS 黑名单，未知 TypeUS 默认接受**（兼容性优先，历史教训：科创板/北交所曾被误拒）。

### 东财证券分类字段速查（2026-08 实测）

| SecurityTypeName | TypeUS（该市场内含义） | 判定 |
|---|---|---|
| 沪A / 深A / 科创板 / 京A（北交所） | 2 / 6 / 80 / 23 / 81 | A 股，接受 |
| 港股 | 3=普通股/人民币柜台/同股不同权；**1=杠杆ETF；6=权证** | 接受（排除 1、6） |
| 沪B / 深B | 3 / 7 | B 股，接受 |
| 美股 | 1=原生正股；3=ADR；**5=ETF；6=票据** | 接受（排除 5、6） |
| 三板 / 英股 / 日股 / 粉单 / 债券 / 基金 / 期货 / 期权 / 指数 / 板块 | — | 无数据通道，拒绝 |

## 五、美股公告支持要点（2026-08 已实现）

- 美股走 SEC EDGAR：内部两套通道（东财/EDGAR）、对外统一参数；字母代码自动路由 EDGAR。
- HTML 按 page-break 切虚拟页（无分页按结构切块），复用 PDF 阅读引擎；参数语义与 PDF 完全一致。
- ticker→CIK 用 company_tickers.json（本地缓存 24h）；建档对外只有 1 个动作（`establish_company(codes=["AAPL"])`）。
- 发行类表单（424B*/FWP）默认保留不过滤（用户决策）。
- **title 只做"原始信息 + 翻译"，不做推断**：8-K items 翻译进 title、FORM_MEANINGS 表单类型翻译；**EDGAR 没有的季度/财年不推算**（财年可能非自然年），有原始信息原样附上、没有的不编。

## 六、铁律（绝对不能改/必须遵守）

1. **iFinD 参数严禁猜测/试探变体**——官方对 AI 爬取不友好、参数混乱且分接口分市场语义不一（A 股 107=现金分红、美股 107=分红再投）；需要新接口/参数写法直接向用户要（用户有官方手册）。
2. **不自己推算/编造上游没有的信息**（"如果没有的我们不要自己瞎写"）：有原始信息原样附上并标注来源字段，没有的不补、不推算。
3. **不加武断限制**：加限制前问"为什么要限制"，区分数据源边界（英股/日股/三板无通道，拒绝对）、防误收（杠杆ETF/权证/ETF，拒绝对）与武断限制（可用市场被编码判断误伤，不对）。判定字段稳定性：`security_type_name` > `classify` > `type_us`。
4. **不要随意改契约/命名**：CLI 顶层字段 `tool`、建档子动作 `action`、read 参数 `start_page`/`return_pages`、market-data 工具金融术语命名——改契约后必须 grep 全部调用点逐一核对（曾漏改 read_batch 导致正文读取全挂）。
5. **文档写入铁律**：决策→架构文档（或公告方案文档）；客观能力→数据源支持文档；协作规则→AGENTS.md；**不要**在 skill/memory 里重复项目决策细节（指向项目文档即可）。
6. **重写/大改任何文档前必须先备份**（时间戳目录 `docs/backup-YYYYMMDD-HHMM/`）。
7. 未经用户明确要求，不部署、不导出、不提交、不推送。
8. 临时探针放 `.codex-temp/`，不得混入生产模块。

## 七、开发方式

- 一次只实现和验证一个小步骤，汇报真实结果后再继续。
- 探索/方案设计阶段：先讨论确认再动手（必要时用 grill-me 拷问决策树），不急着写代码。
- 不要先假设完整返回结构再一次性实现；上游接口字段、过滤规则和分页行为必须先做真实调用验证。
- 上游改契约，下游脚本适应上游；但改完必须同步所有调用点。
- 偶发/一次性任务不做成通用脚本/工具（用户强烈偏好克制）。
- 返回结构保持克制，只保留投资研究确实需要或上游实际返回的内容。

开发测试环境：

```powershell
$env:PYTHONPATH = 'src'
& 'D:\venvs\a-share-announcements\Scripts\python.exe' -m pytest -q
```

`reference/` 仅供参考，不在其中开发。

## 八、文档地图（什么内容记到哪里）

| 文档 | 记录什么 | 不记录什么 |
|---|---|---|
| **AGENTS.md（本文件）** | 协作规则、工具总览、关键约定、铁律、文档地图 | 接口逐字段契约、客观能力矩阵 |
| **PROJECT.md** | 公告 MCP 的 CLI/MCP 工具契约（请求/响应/缓存结构/依赖/导出） | 实现细节、决策理由 |
| **docs/AH公告与互动问答改造方案.md** | 公告 MCP 的实施约定 + 已验证上游接口（公告侧决策与事实的唯一权威） | market-data 内容 |
| **docs/market-data架构设计.md** | **market-data 全部决策**（数据源选择/来源链/复权口径/缓存/代码架构/股本方案/历史决策/待办） | 客观能力细节 |
| **字段与数据源支持情况.md** | **上游客观能力**（各源支持的市场/字段/参数/返回格式/单位/限制、接口速查、实测记录） | 任何决策 |
| **docs/market-data设计讨论.md** | 历史讨论过程记录（已降级，冲突以架构设计为准） | 当前决策 |
| **docs/公告阅读产品设计.md** | 公告阅读策略、样本与验收标准 | — |

## 九、关键坑（操作级，详见 skill a-share-announcements-mcp-dev）

- FastMCP 未知参数静默忽略 → server.py 已设 `extra="forbid"` 严格模式（未知参数显式报错）。
- 导出用户版必须导出到实际生效目录（`D:\HermesSync\tools\a-share-announcement-reading`），export 后 Hermes 内置 MCP 需重启才生效（能力库每次新起进程不受影响）。
- **Hermes MCP 注册（2026-08-10 实测踩坑）**：`hermes mcp add` 无 cwd 选项，stdio 启动不设 cwd——server.py 必须自带 `sys.path` 自处理（`if __package__ in (None, ""): sys.path.insert(0, parents[1])`，公告/market-data 两个 server.py 都要有）；配置 args 用脚本**绝对路径**（如 `...\market_data_mcp\server.py`），不要用 `-m 包.模块`（依赖 cwd 会 ModuleNotFoundError）。改 Hermes MCP 配置只能走 CLI（remove+add 或 hermes config），直接 patch `Share\Configs\*.yaml` 会被安全策略拒绝；改完验证：`hermes mcp test <name>` + 模拟启动探针（subprocess 脚本路径 + 任意 cwd + env，走 JSON-RPC 真实调用一次）。
- 港股过滤后 `total_hits` 含旧公司记录，完成判断用"连续 3 页过滤后为空"。
- read 检测阈值必须与 `return_pages` 默认值一致（20 页），改阈值需同步 reader.py/server.py 两处 docstring。
- 能力库 use_tool.py 返回结构有嵌套：`d["result"]["content"][0]["text"]` 才是工具真实返回。
- 本机 `read_file` 会把中文文档误判为 binary，用 python 读取。
