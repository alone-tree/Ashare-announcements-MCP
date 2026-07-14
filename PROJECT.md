# AShare-Announcements-MCP — 项目文档

> 给 AI Agent 提供 A 股上市公司公告查询能力的 MCP Server。让 Claude、Hermes 等支持 MCP 协议的 AI 通过结构化工具直接查询、筛选、下载、阅读公告。

---

## 一、项目定位

### 解决的问题

A 股投资者/研究员在分析公司时，需要反复查询公司公告——不同时间段、不同类型、不同关键词。传统方式是手动打开东方财富/巨潮资讯网页搜索，效率低且无法与 AI 工作流整合。

本 MCP Server 将公告查询变成 AI Agent 可直接调用的工具，对话中说"查一下东方雨虹近三个月财务报告公告"即可获得结构化结果，无需离开对话环境。

### 使用场景

- 研究一家公司时，查询其历史公告列表，按关键词/类型筛选
- 发现感兴趣的事件后，下载对应公告 PDF 并提取正文阅读
- 将多份公告串联为事件时间线，辅助投资研究

### 不是做什么的

- 不是公告聚合/新闻推送服务
- 不提供投资建议或分析结论
- 不保证公告数据的完整性和及时性（数据源为公开免费接口）

---

## 二、架构设计

### 核心决策：用旧 CrewAI 工具做底版，而非 AKShare

| 维度 | CrewAI 旧工具 | AKShare |
|------|-------------|---------|
| 数据源 | 东方财富 JSONP API（直连） | 东方财富网页爬取 |
| URL 类型 | PDF 直链 `pdf.dfcfw.com/pdf/H2_xxx_1.pdf` | HTML 详情页 |
| 元数据 | 公司简称、细分栏目名(可多个)、art_code | 代码、名称、公告类型(单一) |
| PDF 下载 | 已有（cloudscraper + requests 双通道） | 无 |
| PDF 正文 | 已有（pdfplumber，分页 chunking） | 无 |
| 缓存层 | Excel + JSON + 下载状态追踪 | 无 |

参考代码位于 `reference/` 目录下，生产代码在此基础上重构。

### MCP 工具设计

**工具 1：`query_announcements`**

```
query_announcements(
    stock_code: str,          # 必填，六位数字
    keyword: str = None,      # 可选，空格=AND，竖线=OR
    category: str = None,     # 可选，公告分类过滤
    start_date: str = None,   # YYYY-MM-DD
    end_date: str = None,     # YYYY-MM-DD
    page: int = 1,            # 页码
    page_size: int = 50,      # 每页数量
)
→ { stock_name, total_cached, filtered, page, page_size, total_pages, results[] }
```

**工具 2：`read_announcement`**（后续实现）

```
read_announcement(
    stock_code: str,          # 必填
    url: str,                 # 必填，PDF 链接（从 query 返回）
    max_chars: int = 8000,    # 最大字数
)
→ { text, total_pages, chars_returned, is_last_chunk }
```

### 传输协议

stdio 模式 — MCP 客户端通过 `python <导出目录>/ashare_announcements_mcp/server.py` 启动，Hermes / Claude Desktop 自动管理进程生命周期。

### 初期交付方式：export 用户版，而非 pip 包

早期阶段先不做 `pip install ashare-announcements-mcp`。原因是 pip 分发会引入包发布、Python 环境选择、site-packages 安装位置、版本升级等额外复杂度，不利于先验证 MCP 工具本身是否好用。

当前优先采用 **export 脚本**：

```
python scripts/export.py <目标路径>
```

脚本在目标路径生成一份可直接配置为 MCP Server 的“用户版”代码，包含：

- MCP Server 运行代码
- 必要依赖说明
- 示例配置文件
- 独立缓存目录

用户侧配置时直接指向导出的入口文件，例如：

```yaml
mcpServers:
  ashare-announcements:
    command: python
    args:
      - D:/path/to/exported/ashare_announcements_mcp/server.py
```

这样做的取舍：

- 优点：安装路径直观，方便检查、复制、删除和调试
- 优点：不用处理 PyPI 发布和多 Python 环境混乱
- 优点：适合早期快速迭代，用户版代码可以稳定冻结
- 缺点：后续升级需要重新 export
- 缺点：不如 pip 包标准化

等工具形态稳定后，再进入 PyPI 发布阶段。

---

## 三、缓存策略

### 设计原则

用户会围绕一家公司做多轮探索式查询（不同时间段、不同类型、不同关键词），不应每次都从 API 全量拉取。

### 机制

1. **首次查询某公司**：后台全量拉取（可能 2-3 分钟，取决于公告数量），API 每次 50 条分页请求
2. **存入本地缓存**：CSV 格式，放在导出目录下的 `cache/{代码}/announcements.csv`
3. **后续查询**：纯本地过滤（关键字/日期/分类筛选），不走网络，毫秒级
4. **自动增量更新**：每次查询前对比当前日期与缓存最新日期，差值 > 1 天则拉取增量。增量通常只有 1-2 页，几秒完成
5. **缓存不设过期**：公告一旦发布就不改不删，不存在"过期"概念
6. **PDF 文件**：下载后缓存在 `cache/{代码}/pdfs/`，同一公告不重复下载

### 状态文件

`cache/{代码}/meta.json` 记录：
- 首次拉取时间
- 最后更新日期
- 已缓存总条数

---

## 四、数据流

```
用户: "查东方雨虹近三个月减持公告"
         │
         v
┌──────────────────────────────────────┐
│  MCP Tool: query_announcements       │
│                                      │
│  1. 加载缓存 meta.json               │
│  2. 判断是否需要增量更新              │
│     ├── 无缓存 → 调用 API 全量拉取    │
│     └── 有缓存 → 增量拉取 + 合并      │
│  3. 关键字/日期/分类本地过滤          │
│  4. 分页返回                         │
└──────────────────────────────────────┘
         │
         v
    返回结构化 JSON
         │
         v
用户: "读第 3 条公告"
         │
         v
┌──────────────────────────────────────┐
│  MCP Tool: read_announcement         │
│                                      │
│  1. 检查本地 PDF 缓存                │
│     ├── 已缓存 → 直接读取            │
│     └── 未缓存 → 下载 PDF 并存盘     │
│  2. pdfplumber 提取文本              │
│  3. 按 max_chars 截断返回            │
└──────────────────────────────────────┘
```

---

## 五、数据源

### 公告列表 API

```
GET https://np-anotice-stock.eastmoney.com/api/security/ann
  ?cb=jQuery_xxx
  &sr=-1              # 按时间倒序
  &page_size=50
  &page_index=1
  &ann_type=A         # 所有类型
  &client_source=web
  &stock_list=002271
```

返回 JSONP 格式，解析后每条公告包含：

| 字段 | 说明 |
|------|------|
| art_code | 公告唯一编码 |
| title | 公告标题 |
| title_ch | 中文标题 |
| notice_date | 公告日期 |
| display_time | 发布时间（精确到毫秒） |
| columns | 分类标签数组（可多个） |
| codes | 关联公司数组（含 short_name） |

### PDF 下载

```
https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf
```

### 可靠性说明

- 数据源为东方财富免费公开 API，无需注册或 API Key
- 数据获取依赖 HTTP 请求，受网络环境影响
- 东方财富可能改版 API（历史上发生过），需要关注
- PDF 链接基于 `H2_{art_code}_1.pdf` 命名规则，不保证100%覆盖
- 本工具不保证数据完整性和及时性

---

## 六、技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| MCP 协议 | `mcp` Python SDK | Server 注册、工具定义、stdio 传输 |
| HTTP 请求 | `requests` | API 调用（主） |
| 反爬处理 | `cloudscraper` | PDF 下载（备选，绕过 Cloudflare） |
| PDF 解析 | `pdfplumber` | 文本层提取 |
| 数据存储 | CSV + JSON | 本地缓存 |
| 交付脚本 | `scripts/export.py` | 生成用户版 MCP 代码 |
| 包管理 | `uv` / `pip` | 后期依赖管理和发布 |
| Python 版本 | 3.10+ | 运行时要求 |

---

## 七、目录结构

```
Ashare-announcements-MCP/
├── README.md                    # 面向用户的快速开始
├── PROJECT.md                   # 本文件，面向开发者和协作者
├── LICENSE                      # MIT
├── pyproject.toml               # 包配置和依赖
├── scripts/
│   └── export.py                 # 导出用户版代码到指定目录
├── reference/                   # 原始参考代码（只读，不改动）
│   ├── company_announcements.py # 东方财富 API 查询 + 翻页逻辑
│   ├── announcement_downloader.py # PDF 下载（双通道）
│   ├── real_announcement_tools.py # PDF 提取 + Excel 缓存
│   └── trace_utils.py           # 日志工具
├── src/
│   └── ashare_announcements_mcp/
│       ├── __init__.py
│       ├── __main__.py          # python -m 入口
│       ├── server.py            # MCP Server 注册 + 工具实现
│       ├── api.py               # 东方财富 API 封装
│       ├── cache.py             # 缓存读写 + 增量更新
│       ├── downloader.py        # PDF 下载
│       └── reader.py            # PDF 文本提取
├── cache/                       # 运行时缓存（.gitignore）
│   └── {股票代码}/
│       ├── announcements.csv    # 公告列表缓存
│       ├── meta.json            # 缓存状态
│       └── pdfs/                # 已下载 PDF
└── tests/
    └── test_api.py
```

导出的用户版目录结构：

```
目标路径/
├── ashare_announcements_mcp/
│   ├── server.py                 # MCP Server 入口
│   ├── api.py
│   ├── cache.py
│   ├── downloader.py
│   └── reader.py
├── cache/                        # 用户侧运行缓存
├── requirements.txt              # 用户侧依赖
└── README.md                     # 用户侧配置说明
```

---

## 八、开发阶段

### 第一阶段（当前）

- [x] 项目初始化、README、PROJECT.md
- [x] 参考代码复制
- [x] MCP Server 框架搭建（server.py、__main__.py）
- [x] `query_announcements` 工具实现（API 查询 + 缓存 + 过滤）
- [x] export 脚本实现（生成用户版代码到指定目录）
- [x] 用户版配置说明生成
- [x] 本地调试通过

### 第二阶段

- [x] `read_announcement` 工具实现
- [x] PDF 下载 + 文本提取集成
- [ ] 增量更新逻辑完善
- [ ] 错误处理和重试机制

### 第三阶段

- [ ] pyproject.toml 包配置
- [ ] PyPI 发布（`pip install ashare-announcements-mcp`）
- [ ] 用户文档和示例
- [ ] 与其他 AI 平台（Claude Desktop、Cursor 等）的兼容性测试

---

## 九、开发约定

- Python 代码注释使用中文
- 文档使用中文
- MCP 工具返回结构化 JSON（非纯文本）
- 缓存文件路径不硬编码，从包目录动态定位
- 网络请求必须设置 User-Agent 和超时
- 所有 API 调用需要 try/except + 错误日志
- 参考代码放在 `reference/` 下不修改，生产代码在 `src/` 下重新组织
