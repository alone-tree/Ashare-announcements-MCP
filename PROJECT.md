# AShare-Announcements-MCP 项目说明

## 目标

把 A 股/港股/美股公告的“发现、定位、阅读”变成 AI 可稳定调用的 MCP 工具。当前只优化个人环境中的可用性，采用 export 用户版，不处理 PyPI 发布和跨用户适配。

用户用语与市场范围统一见[AGENTS的用语约定](AGENTS.md#用户用语与市场范围)，此处不重复维护。

## 工具契约

### 批处理 CLI

`python -m ashare_announcements_mcp.cli` 从 stdin 接收一个 JSON 请求，stdout 只返回一个 JSON 响应。CLI 与 MCP 共用公告档案、下载和 PDF 阅读模块，不维护第二套缓存。

支持七个 tool（与 MCP 工具一一对应）：

- `query_batch`：批量同步并查询多家公司，返回日期和关键词范围内的全部公告。
- `query_a_share_interactions_batch`：批量查询 A 股互动问答（原 `query_interactions_batch` 改名，仅 A 股适用）。
- `search_batch`：批量检索整份 PDF，返回命中页和短片段；默认不主动 OCR。
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
)
```

- 首次查询直接翻完东方财富全部列表，建立完整档案。
- 后续每次查询前检查最新公告并增量补全。
- 日期、关键词、翻页只作用于本地缓存。
- 每页固定最多 50 条；返回完整公告数、匹配数和总页数。
- 股票代码自动清理市场前后缀；关键词空格为 OR，显式 `AND` 为 AND。

### `search_announcement`

在完整逐页索引中检索关键词，返回命中页和短片段。扫描页可按需 OCR 并写回缓存，因此后续检索和阅读无需重复识别。

### `read_announcement`

不传 `start_page` 时自动检测：短公告（≤20 页）直接返回全文；长公告返回文档画像（页数、profile、扫描页、文本覆盖率、推荐动作）和前 5 页正文预览。传 `start_page` 时精读指定页段：正常页通过 PyMuPDF4LLM 尽量保留标题、段落和表格；扫描页通过 RapidOCR 恢复文字。单次最多返回 `return_pages` 页（默认 20，不设上限，可一次读完全文），使用 `next_page` 继续。

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

A 股互动问答查询（原 `query_interactions` 改名，凸显 A 股范围；核心功能不变）。首次全量建档，之后增量更新；仅 A 股适用，传 H 股代码可定位关联 A 股问答，纯港股/B 股/本地公司/美股返回 `applicable=false`。

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

提取缓存记录 PDF 文件大小和修改时间。源文件变化或索引版本升级时自动重建。
电话会议：正文全文缓存（每财季一篇，~40-60K 字符）；首次同步最近 12 财季、每次调用同步索引页、`force_refresh` 重试失败季；`report_date` 由公告档案（EDGAR 10-Q/10-K）反查，不解析 XBRL。

## 依赖

| 依赖 | 用途 |
|---|---|
| `mcp` | stdio MCP Server |
| `requests` | 东方财富 API 和 PDF 下载 |
| `pymupdf` | 快速逐页索引、图像检测和页面渲染 |
| `pymupdf4llm` | Markdown 与原生表格提取 |
| `rapidocr` | 中文扫描页 OCR |
| `onnxruntime` | 本地 CPU OCR 推理 |

OCR 工作进程必须使用 `stdin=DEVNULL`，不能继承 MCP stdio 输入管道；否则 ONNX 初始化会在能力库 relay 场景下长期无响应。

## 导出与注册

```bat
python scripts\export.py "D:\HermesSync	ools-share-announcement-reading"
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
