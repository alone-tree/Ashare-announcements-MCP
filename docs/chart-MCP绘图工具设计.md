# chart MCP 绘图工具 —— 任务交接文档

> 2026-08-10 由子柯与 Hermes（grill-me 逐项对齐）定稿。
> 本文档是接手 AI 的**唯一交接物**：背景、目标、决策与考量都在这里；
> 代码细节请自己读仓库，本文档只提示"看哪里"。

## 一、背景：为什么要做这个

子柯维护"个股研究基本工具" Hermes project（`D:\Github\Ashare-announcements-MCP`），当前已有两个 MCP：

1. **公告 MCP**（`src/ashare_announcements_mcp/`）——查 A/H/B/美股公告
2. **market-data MCP**（`src/market_data_mcp/`）——三市场行情/财报/公司信息

研究流程中 AI 看完公告、查到数据之后，还缺**画图**这一环。目标是把体系做成三个 MCP 一体：**看公告 → 查数据 → 画图**。chart MCP 就是第三块。

参考项目 `D:\Github\price-insight`（子柯的本地分析项目，约 8500 行 matplotlib 脚本）**只是灵感来源**——子柯明确说"不是要照搬他的所有东西"。其中"单资产四联图（价格+回撤+波动率）"这类分析图是后续轮次的事，本期只做最基础的行情图。

## 二、任务目标（本期，做完即交付）

新建独立第三个 MCP（包名 `chart_mcp`，MCP 名 `chart`），提供工具 **`get_quote_chart`**：输入行情参数，输出一张行情图 PNG（K线或折线），返回文件路径。

- **K线模式**（默认）：蜡烛图 + 成交量副图 + MA5/10/20/60 均线
- **折线模式**：传 `field`（open/high/low/close 任一）→ 单价格字段走势折线，不带副图、**不带均线**（2026-08-10 确认）
- **CLI 双入口必须同步做**（子柯明确要求："我也需要使用 CLI 来绘图"）

## 三、全部已确认决策（grill-me 拍板，接手 AI 不得擅自更改）

### 1. 工具拆分
- **`get_quote_chart`（本期）**：K线/折线行情图
- **`get_insight_chart`（后续轮次）**：分析图（price-insight 式单资产四联图等），本期**不做**，不要顺手实现

### 2. 数据链路（核心架构决策）
- 绘图工具**内部直接 import 调用 `market_data_mcp.service.get_quote()`**，**不复制取数代码**
- 缓存语义：有缓存用缓存，没缓存由 get_quote 自动补拉——**绘图层完全不操心数据**
- 复用方式：同仓库同 venv，`import market_data_mcp` 即可（与公告 MCP 共用 `D:\venvs\a-share-announcements` venv）
- **不做**独立数据源兜底（如本地 Excel），即使单独导出 chart 也不允许它自己拉数

### 3. export 强约束（用户版部署）
- chart 与 market-data **必须同时导出**，不能单独导出 chart
- 用户版缺 market-data 时，chart 调用要**报错提示"数据未配置，请导出 market-data MCP"**，而不是假装能用
- 理由（子柯原话）："因为现在只是我个人在用，后期有需要了再把它增加相应的功能"

### 4. 参数设计
`code`（带市场后缀，如 300308.SZ / 00700.HK / AAPL.US）、`adjust`（raw/hfq/qfq）、`start_date`/`end_date`、`period`（daily/weekly/monthly）、`log_scale`（默认普通坐标）、`field`（默认 None → K线；传 open/high/low/close 任一 → 折线）

**log_scale 适用范围（2026-08-10 确认）**：对 K线、折线、成交量副图都生效；**只有数据包含负值或 0 时才自动退回普通坐标**。

### 5. 日期区间默认值（⚠️ 与 get_quote 不同）
- **不传日期区间 = 返回全部缓存数据**，不是 get_quote 的默认最近 10 个交易日，**不是**默认一年
- 子柯明确拍板："不传时间区间，默认返回所有缓存的数据"
- **"全部"语义需要上游支持（2026-08-10 确认）**：get_quote 当前 start_date 空 = 最近 10 个交易日，无法表达"全部"。需给 get_quote 增加 `start=all` 之类的上游参数（改 market-data 数据层），chart 层不自行实现"全量拉取"（遵守"绘图层完全不操心数据"）

### 6. 视觉风格：全部代码写死
- 尺寸、PPI、中文字体、配色全部固定，**不提供模板系统**，AI 不用操心样式
- 红涨绿跌（A股口径）；MA5/10/20/60 四根均线本期带上（"第一期先带这个均线，后面有需要再调整"）
- **MA 按当前周期计算（2026-08-10 确认）**：周图 MA5 = 5 周均线，月图 MA5 = 5 月均线；不是按日 K 换算
- **均线数据不足就不绘制（2026-08-10 确认）**：如新股上市仅 3 天数据，MA20/60 画不出就不画，不报错、不伪造

### 7. 输出
- **每次调用都重新绘图**（不按参数做图缓存复用），PNG 落盘 `{MARKET_DATA_ROOT}/cache/_charts/`
- **只返回文件路径**，不返回图片内容；AI 需要看图时自己读图文件

### 8. 其他
- 本期不做：模板系统、多标的对比、分析图、volume/amount 单独折线图
- 中文字体必须处理（matplotlib 默认无中文，乱码不可接受）

## 四、接手 AI 需要知道的实施环境事实

- 仓库：`D:\Github\Ashare-announcements-MCP`，分支 `main`，当前干净
- venv：`D:\venvs\a-share-announcements\Scripts\python.exe`（pandas/numpy/akshare/yfinance 已装；**matplotlib 未装，需要补装**——已查证）
- 用户版目录：`D:\HermesSync\tools\a-share-announcement-reading`（MARKET_DATA_ROOT 指向这里，cache/ 下已有各代码行情缓存，可用来做真实绘图验证）
- 测试：venv 里 pytest（当前 208 tests 全绿基线）；iFinD 相关测试自包含（tmp_path 伪 config.yaml，不依赖本机真配置）
- 用户协作规则（AGENTS.md + 项目 skill 有完整版）：实现前读 AGENTS.md；测试通过 → 提交 git → 继续；遇到障碍停下汇报

## 五、需要动的地方（自己读代码，这里只指路）

| 位置 | 用途 |
|---|---|
| `src/market_data_mcp/service.py` 的 `get_quote()` | 数据源，绘图直接 import 调用；注意它的对外返回契约（`docs/market-data架构设计.md` §1.6 有工具契约） |
| `src/market_data_mcp/server.py` | FastMCP 入口样板（严格参数模式、sys.path 自处理），chart server.py 照此模式 |
| `src/market_data_mcp/cli.py` | CLI 样板（stdin JSON → stdout JSON，顶层字段 `tool`），chart cli.py 照此模式 |
| `scripts/export.py` | 目前导出两个 MCP，需扩展为三个 + market-data 依赖检查 |
| `docs/market-data架构设计.md` | market-data 架构决策中枢，了解 get_quote 口径（复权/频率/缓存） |
| 测试目录 `tests/` | 现有测试组织方式，chart 测试照此加入 |

## 六、交付验证标准

1. `get_quote_chart` 真实调用成功：至少用 300308.SZ 画 K线（含成交量+均线）和 00700.HK 画折线，PNG 落盘 `cache/_charts/`，中文显示正常
2. CLI 入口同样可画出图
3. 不传日期区间时确实返回全部缓存数据（对比缓存文件的实际日期范围验证）
4. export.py 导出后用户版目录含 `chart_mcp/`，且单独删掉 market-data 时 chart 调用给出明确报错提示
5. 全量测试绿（新增 chart 测试 + 既有 208 不回归）
6. 提交 git（信息格式参考仓库历史，如 `feat(chart): ...`）并 push 到 origin/main

## 七、后续轮次（本期不要做，仅记录方向）

- `get_insight_chart`：分析图工具（单资产价格+回撤+波动率四联图、多资产对比等），参考 `D:\Github\price-insight\scripts\price_insight.py` 的绘图思路，单独设计
- 模板系统：子柯说"先没有模板这个问题"，后期按需
