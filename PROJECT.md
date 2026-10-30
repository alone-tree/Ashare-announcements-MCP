# AShare-Announcements-MCP 项目说明

## 目标

把 A 股/港股/美股公告的“发现、定位、阅读”变成 AI 可稳定调用的 MCP 工具。当前只优化个人环境中的可用性，采用 export 用户版，不处理 PyPI 发布和跨用户适配。

用户用语与市场范围统一见[AGENTS的用语约定](AGENTS.md#用户用语与市场范围)，此处不重复维护。

## 工具契约

### 批处理 CLI

`python -m ashare_announcements_mcp.cli` 从 stdin 接收一个 JSON 请求，stdout 只返回一个 JSON 响应。CLI 与 MCP 共用公告档案、下载和 PDF 阅读模块，不维护第二套缓存。

支持七个 tool（与 MCP 工具一一对应）：

- `establish_company`：`action="check"`配`keyword`查询候选，`action="establish"`配`codes`数组建档；公司识别与映射规则见[公告主文档§3—4](docs/AH公告与互动问答改造方案.md#3-establish_company)。
- `query_batch`：批量同步并查询多家公司，返回日期和关键词范围内的全部公告。
- `query_a_share_interactions_batch`：批量查询 A 股互动问答（原 `query_interactions_batch` 改名，仅 A 股适用）。
- `search_batch`：批量检索整份 PDF，返回命中页和短片段；`ocr_scanned=true`为默认值。
- `read_batch`：批量读取指定页段；默认 `return_pages=20`、`ocr=true`。
- `query_transcripts_batch`：批量查询美股电话会议索引/正文（参数 `period`、`force_refresh`）。
- `search_transcripts_batch`：批量检索电话会议正文（参数 `query`）。

CLI 只提供通用查询和阅读能力。按公告类型、长度和扫描比例分流的业务规则由调用方维护。

### `query_announcements`

```python
query_announcements(
    stock_code: str,
    page: int = 1,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
    market: str = "all",
)
```

- 查询前须显式建档；未建档时提示`check → establish → query`。建档与同步规则见[公告主文档§3—5](docs/AH公告与互动问答改造方案.md#3-establish_company)。
- `market`可取`all/A/H`，只筛选本地结果；`A`包含B股，`H`只筛港股，美股提交使用`all`。所有关联证券仍执行同步。
- 日期、关键词、翻页只作用于本地缓存。
- 每页固定最多 50 条；返回完整公告数、匹配数和总页数。
- 股票代码自动清理市场前后缀；关键词空格为 OR，显式 `AND` 为 AND。

### `search_announcement`

参数为`stock_code`、`url`、`query`、`max_results=20`、`ocr_scanned=true`。在完整逐页索引中检索关键词，返回命中页和短片段；扫描页索引与续查流程见[阅读产品文档§4.3](docs/公告阅读产品设计.md#43-扫描件)。

### `read_announcement`

参数为`stock_code`、`url`、`start_page=None`、`return_pages=20`、`ocr=true`。不传`start_page`时自动检测：短公告（≤20页）返回全文，长公告返回画像和前5页正文预览。传`start_page`时按页精读，`return_pages`不设上限，可一次读完全文，使用`next_page`续读。PDF页码从1开始，参数语义同样适用于SEC HTML虚拟页；阅读引擎、扫描页和表格策略只在[阅读产品文档](docs/公告阅读产品设计.md)维护。

阅读与检索的`url`接受东方财富`pdf.dfcfw.com`、SEC EDGAR链接或本地已存在的PDF路径，不要求公司先建档。链接与附件的已知边界见[公告主文档§8.3](docs/AH公告与互动问答改造方案.md#83-公告详情与附件)。

### `query_transcripts`

```python
query_transcripts(
    stock_code: str,
    period: str | None = None,
    force_refresh: bool = False,
)
```

- 美股电话会议（earnings call transcript）通道，仅美股适用；其他市场返回 `applicable=false`。
- 不传 `period`：返回全部财季索引（`fiscal_quarter`/`report_date`/`form`/`status`），每次调用同步一次索引页，首次下载最近 12 财季，`force_refresh` 重试失败季。
- 传 `period`（如 `FY2026-Q3`）：返回该财季完整正文（逐发言轮次：`author` + `text`）；索引里有但没缓存过的季会按需单独补下载。
- 正文来源 stockanalysis.com：`/stocks/{ticker}/transcripts/` 索引页列出全部财季电话会（标签即公司财季），正文页按发言轮次结构化解析；纯 `requests`，不依赖 cookie 或浏览器。
- `report_date`/`form` 只从本地公告档案的 10-Q/10-K 反查，有则附上、没有留空（刚开完会尚未提交 10-Q 时为空，属正常）；是否有电话会完全由索引页决定，不再依赖 10-Q/10-K。
- ADR/外国发行人走主上市代码兜底：美股代码页 404 时读个股页 `transcriptsLinkSymbol`（TSM → `TPE-2330`、BABA → `HKG-9988`），改走 `/quote/{exchange}/{code}/transcripts/`；两者都没有才返回空索引 + `note`。
- 状态语义：`ok`=正文已缓存；`missing`=页面 404（该季上游未收录）；`failed`=网络/HTTP/解析异常（带 `http_status` 或 `error`），不冒充「未收录」。

### `search_transcripts`

```python
search_transcripts(
    stock_code: str,
    query: str,
)
```

- 在全部已缓存电话会议正文中检索关键词（空格=AND），返回命中财季、发言作者与上下文片段。
- 仅美股适用；未同步过正文的财季不参与检索（先调 `query_transcripts` 全量同步）。

### `query_a_share_interactions`

参数为`stock_code`、`page=1`、`start_date=None`、`end_date=None`、`keyword=None`。仅A股适用；关联H股可定位A股，纯港股/B股/本地公司/美股返回`applicable=false`。同步、筛选与缓存见[公告主文档§6](docs/AH公告与互动问答改造方案.md#6-互动问答)。

## 美股公告提交与标题

美股走SEC EDGAR，东财与EDGAR使用统一对外参数，字母代码自动路由EDGAR。ticker→CIK使用company_tickers.json，本地缓存24小时；建档入口仍为`establish_company(codes=["AAPL"], action="establish")`。

HTML按page-break切虚拟页，没有分页时按结构切块，复用PDF阅读引擎；读取与检索参数语义与PDF一致。具体阅读实现与验收见[公告阅读产品设计](docs/公告阅读产品设计.md)。

发行类表单424B*、FWP默认保留，不在列表中自动过滤。title只组合原始信息与翻译：8-K的items按含义翻译，表单类型使用FORM_MEANINGS映射；EDGAR未提供的季度或财年不推算，有原始信息原样附上，没有则不补。

## 数据流

```text
query_announcements
  -> 首次全量建档 / 后续增量补全
  -> 本地筛选与 50 条分页

query_batch CLI
  -> 复用同一档案同步服务
  -> 多公司查询与扁平结果

search_batch / read_batch CLI
  -> 复用同一 PDF 下载、索引和阅读缓存

read_announcement
  -> 下载并缓存 PDF
  -> PyMuPDF 全文快速索引
  -> 自动检测画像（页数/扫描页/覆盖率/推荐动作）
  -> 短公告直接返回全文；长公告返回画像 + 前 5 页预览
  -> 带 start_page 时按页精读（普通页转 Markdown，扫描页 OCR）

search_announcement
  -> 查询逐页索引
  -> 必要时由独立工作进程每批 OCR 3 个扫描页并缓存
  -> 返回命中页和片段
```

## 缓存结构

```text
cache/{股票代码}/
  announcements.json
  meta.json
  pdfs/{公告编号}.pdf
  extracted/{公告编号}.json
  transcripts.json          # 电话会议索引（fiscal_quarter/report_date/status）
  transcripts/{FY2025-Q1}.json  # 电话会议正文（逐发言轮次）
```

提取缓存结构与失效规则见[阅读产品文档§3](docs/公告阅读产品设计.md#3-核心判断)；电话会议同步与状态语义见上文`query_transcripts`，不维护第二套规则。

## 依赖

| 依赖 | 用途 |
|---|---|
| `mcp` | stdio MCP Server |
| `requests` | 东方财富 API 和 PDF 下载 |
| `pymupdf` | 快速逐页索引、图像检测和页面渲染 |
| `pymupdf4llm` | Markdown 与原生表格提取 |
| `rapidocr` | 中文扫描页 OCR |
| `onnxruntime` | 本地 CPU OCR 推理 |

OCR进程及引擎初始化约束见[阅读产品文档§3](docs/公告阅读产品设计.md#3-核心判断)。

## 导出与注册

```bat
python scripts\export.py "D:\HermesSync\tools\a-share-announcement-reading"
```

Hermes 配置（config.yaml a-stock-announcements）直接注册导出目录的 `ashare_announcements_mcp/server.py`；历史的能力库 A股公告阅读 注册已不用。所有修改必须先在本开发库完成并通过测试，随后先提交 Git，再执行 export；禁止直接修改用户版导出目录。

开发测试环境：`D:\venvs\a-share-announcements\Scripts\python.exe`。

## 开发约束

- MCP 返回结构化 JSON，不把日志写入 stdout。
- PDF 页码统一从 1 开始，与人类阅读习惯一致。
- 长公告不整篇返回，只返回检索片段或完整页段。
- OCR 和复杂表格转换均按需执行并缓存。
- `reference/` 只保留原始参考代码，不在其中开发。
- 建档证券识别与接入边界见[公告主文档§8.1.1](docs/AH公告与互动问答改造方案.md#811-证券分类与数字代码搜索边界)，不在本文件重复维护字段判定表。

完整的阅读策略、样本与验收标准见 `docs/公告阅读产品设计.md`。
