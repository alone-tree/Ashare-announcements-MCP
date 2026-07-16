# Ashare-announcements-MCP

面向 AI Agent 的 A 股公告查询与阅读 MCP。当前优先服务个人使用，通过 export 脚本生成可直接注册的用户版，不依赖 PyPI 发布。

## 核心能力

- `query_announcements`：首次查询建立公司全部公告档案，之后每次查询前自动补充最新公告；所有筛选和翻页只读本地缓存。
- `inspect_announcement`：快速检查 PDF 页数、目录、原生文本覆盖率和扫描页分布。
- `search_announcement`：检索整份公告，返回命中页和上下文片段；扫描页可按需 OCR 后参与检索。
- `read_announcement`：按完整页面返回内容；原生页面由 PyMuPDF Layout 排除页眉页脚并转为 Markdown，扫描页自动 OCR，长文通过 `next_page` 连续阅读。

## 导出用户版

```bat
python scripts\export.py "D:\path\to\ashare-announcements-user"
```

导出目录包含运行源码、`requirements.txt`、使用说明和独立缓存目录。安装依赖后，MCP 客户端直接以对应 Python 启动 `ashare_announcements_mcp/server.py`。

```yaml
mcpServers:
  ashare-announcements:
    command: python
    args:
      - D:/path/to/ashare-announcements-user/ashare_announcements_mcp/server.py
```

## 工具参数

### `query_announcements`

| 参数 | 必填 | 说明 |
|---|---:|---|
| `stock_code` | 是 | 支持 `002271`、`SZ002271`、`002271.SZ` |
| `page` | 否 | 默认 1，每页固定最多 50 条 |
| `start_date` | 否 | `YYYY-MM-DD` |
| `end_date` | 否 | `YYYY-MM-DD` |
| `keyword` | 否 | 空格表示 OR；显式 `AND` 表示所有词都要命中 |

返回完整公告数量、筛选后数量、总页数、是否还有下一页和当前页明细。

### `inspect_announcement`

参数为 `stock_code` 和查询结果中的 PDF `url`。长公告或未知格式公告应先调用，用于判断直接阅读、先检索还是启用 OCR。

### `search_announcement`

参数为 `stock_code`、`url`、`query`，可选 `max_results` 和 `ocr_scanned`。关键词逻辑与公告查询一致，返回命中页码、片段、匹配次数和提取方式。扫描页每次最多建立 3 页 OCR 索引；若 `search_complete=false`，AI 应使用相同参数再次调用，直到扫描页索引完整。

### `read_announcement`

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `stock_code` | 必填 | 股票代码 |
| `url` | 必填 | 东方财富公告 PDF 链接 |
| `start_page` | 1 | 起始页，按 PDF 可见页码计数 |
| `end_page` | 文档末页 | 可选的结束页 |
| `max_chars` | 12000 | 单次返回软上限，始终保留完整页面 |
| `ocr` | true | 扫描页是否自动 OCR |

返回 `pages_returned`、每页提取方式、正文和 `next_page`。继续阅读时将 `next_page` 作为下一次的 `start_page`。

## 推荐阅读流程

- 10 页以内短公告：直接 `read_announcement`。
- 年报、招股书等长文：`inspect_announcement` → `search_announcement` → `read_announcement`。
- 混合扫描件：先检查扫描页，再检索或直接读取目标页；OCR 结果会缓存。
- 表格密集页：直接读取目标页，工具会优先返回 Markdown 表格。

## 缓存

运行数据位于用户版目录的 `cache/{股票代码}/`：

- `announcements.json`：完整公告档案。
- `pdfs/`：下载后的 PDF。
- `extracted/`：逐页原生文本、Layout Markdown 和 OCR 结果。

## 技术栈

- Python 3.10+
- MCP Python SDK、requests
- PyMuPDF、PyMuPDF4LLM、PyMuPDF Layout
- RapidOCR、ONNX Runtime

详细设计和样本验证见 [公告阅读产品设计](docs/公告阅读产品设计.md)。

## 许可

MIT
