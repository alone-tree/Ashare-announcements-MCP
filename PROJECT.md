# AShare-Announcements-MCP 项目说明

## 目标

把 A 股公告的“发现、定位、阅读”变成 AI 可稳定调用的 MCP 工具。当前只优化个人环境中的可用性，采用 export 用户版，不处理 PyPI 发布和跨用户适配。

## 工具契约

### 批处理 CLI

`python -m ashare_announcements_mcp.cli` 从 stdin 接收一个 JSON 请求，stdout 只返回一个 JSON 响应。CLI 与 MCP 共用公告档案、下载和 PDF 阅读模块，不维护第二套缓存。

支持四个 action：

- `query_batch`：批量同步并查询多家公司，返回日期和关键词范围内的全部公告。
- `inspect_batch`：批量检查 PDF 页数、文档画像、原生文本覆盖率和扫描页。
- `search_batch`：批量检索整份 PDF，返回命中页和短片段；默认不主动 OCR。
- `read_batch`：批量读取指定页段；默认 `max_pages=20`、`ocr=true`。

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

不传 `start_page` 时自动检测：短公告（≤10 页）直接返回全文；长公告返回文档画像（页数、profile、扫描页、文本覆盖率、推荐动作）和前 3 页正文预览。传 `start_page` 时精读指定页段：正常页通过 PyMuPDF4LLM 尽量保留标题、段落和表格；扫描页通过 RapidOCR 恢复文字。单次最多返回 `max_pages` 页（默认 20，不设上限，可一次读完全文），使用 `next_page` 继续。

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
  -> 短公告直接返回全文；长公告返回画像 + 前 3 页预览
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
```

提取缓存记录 PDF 文件大小和修改时间。源文件变化或索引版本升级时自动重建。

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

完整的阅读策略、样本与验收标准见 `docs/公告阅读产品设计.md`。
