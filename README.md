# Ashare-announcements-MCP

A 股上市公司公告查询 MCP Server。让 AI Agent 通过 MCP 协议直接查询、筛选、下载、阅读 A 股上市公司公告。

## 功能

- **查询公告列表** — 按股票代码、日期范围、关键字筛选公告
- **本地缓存** — 首次拉取全量后自动增量更新，后续查询毫秒级
- **PDF 下载** — 从东方财富直接下载公告 PDF 原件
- **正文提取** — 从 PDF 提取文本内容，支持分页 chunking

## 当前阶段：导出用户版

项目早期先不使用 `pip install`。推荐用 export 脚本生成一份独立的用户版代码，方便检查、复制、删除和调试。

```bash
python scripts/export.py D:/path/to/ashare-announcements-user
```

## 使用

Hermes 配置（`config.yaml`）：

```yaml
mcpServers:
  ashare-announcements:
    command: python
    args: ["D:/path/to/ashare-announcements-user/ashare_announcements_mcp/server.py"]
```

Claude Desktop 配置（`claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "ashare-announcements": {
      "command": "python",
      "args": ["D:/path/to/ashare-announcements-user/ashare_announcements_mcp/server.py"]
    }
  }
}
```

后续工具稳定后，再考虑发布为 PyPI 包：

```bash
pip install ashare-announcements-mcp
```

## MCP 工具

### `query_announcements`

查询指定公司的公告列表，支持关键字、日期、分类筛选和翻页。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| stock_code | string | ✅ | 六位股票代码 |
| keyword | string | ❌ | 标题关键字，空格=AND，竖线=OR |
| category | string | ❌ | 公告分类过滤 |
| start_date | string | ❌ | 起始日期 YYYY-MM-DD |
| end_date | string | ❌ | 结束日期 YYYY-MM-DD |
| page | int | ❌ | 页码，默认 1 |
| page_size | int | ❌ | 每页数量，默认 50 |

### `read_announcement`

下载并阅读指定公告的 PDF 正文。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| stock_code | string | ✅ | 六位股票代码 |
| url | string | ✅ | 公告 PDF 链接（从 query 返回） |
| max_chars | int | ❌ | 最大字数，默认 8000 |

## 数据源

东方财富公告 API（`np-anotice-stock.eastmoney.com`），免费公开接口，无需 API Key。

## 缓存

公告列表缓存在 MCP 包目录下的 `cache/` 中，每次查询自动增量更新。PDF 文件下载后缓存在本地，阅读同一公告不重复下载。

## 技术栈

- Python 3.10+
- requests / cloudscraper（PDF 下载）
- pdfplumber（PDF 文本提取）
- MCP stdio 协议

## 参考

`reference/` 目录下是从 [CrewAI-A-share-info-reasearcher](https://github.com/alone-tree/CrewAI-A-share-info-reasearcher) 项目中提取的原始参考代码：

- `company_announcements.py` — 东方财富 API 查询 + 翻页逻辑
- `announcement_downloader.py` — PDF 下载（cloudscraper + requests 双通道）
- `real_announcement_tools.py` — PDF 文本提取 + Excel 缓存
- `trace_utils.py` — 日志工具

## 许可证

MIT
