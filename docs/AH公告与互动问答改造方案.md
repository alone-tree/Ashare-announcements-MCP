# A/H 公告与互动问答改造方案

## 1. 目标与边界

把现有 A 股公告工具克制地扩展为：

- 查询纯 A 股、纯港股和 A+H 公司的公告；
- A/H 公告分别缓存，查询时合并；
- 独立查询 A 股互动问答；
- 继续使用东方财富；
- PDF 仅在实际阅读时下载。

这是个人投资工具。不要增加未经真实使用证明的抽象、字段、迁移工具或错误日志。

## 2. 实施顺序

必须小步实现，每一步完成真实调用和测试后再继续：

1. 简化 `establish_company(action="check")`；
2. 实现 `cache/companies.json` 和 `action="establish"`；
3. 改造 A/H 公告查询；
4. 增加互动问答查询。

当前分支中的 `check` 是探索版，仍带有过滤和自动同名补查逻辑，不是本方案确认的最终行为。

> 状态：四步已全部完成并通过真实调用验证（提交 c1f6110 / c0d58ec / 6f4a602 / 5255027 / 830fb7c）。`check` 已按本方案简化；`establish`、A/H 合并查询、互动问答均已实现。

## 3. `establish_company`

### 3.1 `action="check"`

调用形式：

```python
establish_company(action="check", keyword="中际")
```

规则：

- 把关键词直接交给东方财富独立证券搜索接口；
- 返回接口前 20 条候选；
- 不过滤衍生品、人民币柜台、ADR、期货等；
- 不归组 A/H，不推断公司关系；
- 不创建或修改缓存；
- 只整理东方财富实际返回字段，不补充推测字段；
- 返回 `source_total_count` 和 `returned_count`；
- 当 `source_total_count > returned_count` 时，返回提示：使用更精确的关键词重新查询。

已经确认可取得的字段：

```text
Code, Name, PinYin, ID, JYS, Classify, MarketType,
SecurityTypeName, SecurityType, MktNum, TypeUS,
QuoteID, UnifiedCode, InnerCode
```

项目可以统一转换为 snake_case。

示例：搜索“中际”时，东方财富会同时返回中际联合、中际旭创 A/H 和相关港股衍生品。候选应全部交给 AI 判断。

### 3.2 `action="establish"`

调用形式：

```python
establish_company(
    action="establish",
    codes=["300308", "03308"],
)
```

规则：

- `codes` 是数组，不解析逗号分隔字符串；
- 接受一个明确代码，或一个 A 股代码加一个 H 股代码；
- 拒绝两个 A 股、两个 H 股或三个及以上代码；
- 不自动搜索、猜测或补全另一市场；
- 代码必须能精确查询到证券；
- 拒绝用权证、期货、ADR 等非普通 A/H 公司证券建档；
- 工具描述提醒 AI 不要使用 `-R`、`-WR` 人民币柜台代码，应选择主要港股代码；
- A/H 是否属于同一家公司由 AI 根据 `check` 结果选择，程序不实现复杂关系推断。

公司映射只增不减：

- 重复建档不得删除已有证券；
- 新代码可以加入已有公司；
- 新代码已经属于另一公司映射时，报冲突，不覆盖或自动合并。

各部分独立执行：

- 每个证券的公告列表独立全量或增量更新；
- 有 A 股时，互动问答独立全量或增量更新；
- 一个部分失败不影响其他部分保存；
- 抓取错误只在本次工具结果中报告，不写错误日志；
- 失败后再次建档：无缓存则重新全量，有缓存则增量更新；
- 重复建档复用旧缓存，不重复全量抓取。

返回结果按每个部分报告：是否成功、现有总数、本次新增数和错误。纯港股互动问答直接返回：

```text
港股无互动问答，不适用
```

## 4. 公司映射

保留现有缓存目录，不增加 `A-`、`HK-` 前缀：

```text
cache/300308/announcements.json
cache/300308/interactions.json
cache/03308/announcements.json
cache/00700/announcements.json
```

只新增：

```text
cache/companies.json
```

有 A 股时使用 A 股代码作为公司键；纯港股使用港股代码。未来纯 H 公司新增 A 股时如何迁移，实际遇到后再处理。

建议的最小结构：

```json
{
  "companies": {
    "300308": {
      "securities": [
        {
          "code": "300308",
          "market": "A",
          "name": "中际旭创",
          "classify": "AStock",
          "inner_code": "35942435293078"
        },
        {
          "code": "03308",
          "market": "H",
          "name": "中际旭创",
          "classify": "HK",
          "inner_code": "41388730200001"
        }
      ]
    }
  },
  "aliases": {
    "300308": "300308",
    "03308": "300308"
  }
}
```

不重复保存公司名称；各证券记录已经包含自己的真实名称。`InnerCode` 只供程序过滤和抓取，不在普通查询结果中暴露。

纯 A、纯 H、A+H 全部写入 `companies.json`。

旧缓存不自动迁移。下一次显式建档时就地复用并增量更新，PDF和解析缓存不受影响。

## 5. 公告缓存与查询

A/H 公告按现有方式分别保存在各证券目录：

```text
cache/300308/announcements.json
cache/03308/announcements.json
```

不要增加公告子目录或磁盘合并文件。查询时读取关联证券缓存，在内存中合并、按日期排序和筛选。

港股公告必须按当前证券 `InnerCode` 过滤，防止代码复用。已经验证：

- `03308` 混有旧公司金鹰商贸集团；
- `00300` 混有旧公司昆明机床。

### 5.1 `query_announcements`

增加：

```python
market: str = "all"
```

允许 `all`、`A`、`H`，默认 `all`。市场筛选只作用于本地结果，不影响所有关联证券都执行增量更新。

查询规则：

- 输入任一关联代码，通过 `companies.json` 定位公司；
- 未建档时明确报错并提示 `check → establish → query`；
- 自动增量更新所有已建档关联证券；
- 各市场独立成功或失败；
- 更新失败但已有旧缓存时继续返回旧公告；
- A/H 同一事项不去重删除；
- 每条公告运行时增加 `market` 字段，不迁移旧缓存。

顶部不重复返回公司名，只返回证券及更新状态：

```json
{
  "securities": [
    {
      "code": "300308",
      "market": "A",
      "name": "中际旭创",
      "update": {
        "success": true,
        "total": 2761,
        "new": 2,
        "error": null
      }
    },
    {
      "code": "03308",
      "market": "H",
      "name": "中际旭创",
      "update": {
        "success": false,
        "total": 19,
        "new": 0,
        "error": "东方财富请求超时"
      }
    }
  ],
  "results": []
}
```

不向 AI 返回 `InnerCode`。

工具描述和失败结果应提醒 AI：更新失败时重新查询一次；第二次仍失败则停止重复尝试，换其他方法或向用户报告。

## 6. 互动问答

互动问答独立保存在 A 股代码目录：

```text
cache/300308/interactions.json
```

不与公告混合。

查询入口：

```python
query_interactions(
    stock_code: str,
    page: int = 1,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
)
```

规则：

- 输入 A 股或关联 H 股代码都通过 `companies.json` 定位 A 股代码；
- 纯港股返回“港股无互动问答，不适用”；
- 首次获取完整历史，后续增量更新；
- 更新失败但已有旧缓存时继续返回旧数据；
- 每页最多 50 条；
- 日期按回答时间筛选；
- 关键词同时检索问题和回答；
- 空格表示 OR，显式 `AND` 表示 AND；
- 东方财富只提供已回答问题，不处理未回答问题。

## 7. PDF 阅读

- 建档和公告查询不批量下载 PDF；
- 实际阅读时才下载；
- 公告详情接口 `api/content/ann` 可返回正文和 `attach_url_web`；
- 下载后必须验证响应以 `%PDF-` 开头，避免把临时反爬页面缓存为 PDF；
- 现有 `inspect_announcement`、`search_announcement`、`read_announcement` 阅读流程尽量复用。

## 8. 已验证的上游接口

本节记录此前已经完成的真实调用。实现者应直接复用这些结论，不要重新抓包或猜测分页方式。

### 8.1 东方财富证券搜索

接口：

```text
GET https://searchapi.eastmoney.com/api/suggest/get
```

参数：

```text
input={keyword}
type=14
count=20
token=D43BF722C8E33BDC906FB84D85E326E8
```

响应数据：

```text
QuotationCodeTable.Status
QuotationCodeTable.Message
QuotationCodeTable.TotalCount
QuotationCodeTable.Data
```

`Data` 中已经确认存在：

```text
Code
Name
PinYin
ID
JYS
Classify
MarketType
SecurityTypeName
SecurityType
MktNum
TypeUS
QuoteID
UnifiedCode
InnerCode
```

`check` 应返回 `TotalCount`、实际 `Data` 数量和候选内容。若 `TotalCount` 大于实际返回数量，提示 AI 使用更精确的关键词查询。

真实样本：

```text
输入：中际

605305  中际联合          AStock  TypeUS=2
300308  中际旭创          AStock  TypeUS=80
03308   中际旭创          HK      TypeUS=3
14866   中际华泰七三购A   HK      TypeUS=6
23139   中际华泰六八购A   HK      TypeUS=6
27989   中际麦银六十购A   HK      TypeUS=6
```

```text
输入：中际旭创

300308  中际旭创  AStock  QuoteID=0.300308    InnerCode=35942435293078
03308   中际旭创  HK      QuoteID=116.03308  InnerCode=41388730200001
```

简称不一致样本：

```text
输入：中国海油

600938  中国海油       AStock
00883   中国海洋石油   HK
```

歧义样本：

```text
输入：中国石油

601857  中国石油           AStock
00386   中国石油化工股份   HK
00857   中国石油股份       HK
以及期货、ADR等
```

因此 `check` 不能替 AI 归组公司关系。

人民币柜台样本：

```text
00700 / 80700  腾讯控股 / 腾讯控股-R
01810 / 81810  小米集团-W / 小米集团-WR
09988 / 89988  阿里巴巴-W / 阿里巴巴-WR
00883 / 80883  中国海洋石油 / 中国海洋石油-R
```

人民币柜台同样可能是 `Classify=HK`、`TypeUS=3`，不能仅凭这两个字段识别。由工具描述提醒 AI 选择主要港股代码。

模糊关键词可能远多于 20 条。例如“腾讯”实测 `TotalCount=724`，接口只返回前 20 条。

### 8.2 A/H 公告列表

接口：

```text
GET https://np-anotice-stock.eastmoney.com/api/security/ann
```

关键参数：

```text
sr=-1
page_size=50
page_index={page}
ann_type=A 或 H
client_source=web
stock_list={code}
f_node=0
s_node=0
```

响应数据位于：

```text
data.total_hits
data.list
```

列表项已经确认包含：

```text
art_code
codes[]
columns[]
display_time
eiTime
language
listing_state
notice_date
product_code
sort_date
source_type
title
title_ch
title_en
```

`codes[]` 中已经确认包含：

```text
ann_type
inner_code
market_code
short_name
stock_code
```

港股公告必须用建档时保存的当前 `InnerCode` 过滤：

```python
any(code["inner_code"] == expected_inner_code for code in item["codes"])
```

不能只按五位股票代码过滤。

真实全量样本：

```text
300308 A股：
接口总数              2761
完整分页接收          2761
art_code去重后        2761
最早记录              2012-01-05
最近五年              1041
```

```text
03308 H股：
接口总数              919
当前中际旭创InnerCode 过滤后 19
当前记录时间范围      2026-07-17 至 2026-07-30
旧记录属于            金鹰商贸集团
```

```text
00300 H股：
接口总数              1606
当前美的集团InnerCode 过滤后 481
旧记录包含            昆明机床
```

其他扫测样本的历史末页仍属于当前证券：

```text
00700 腾讯控股
03690 美团-W
01810 小米集团-W
03750 宁德时代
02359 药明康德
00941 中国移动
00883 中国海洋石油
01658 邮储银行
01398 工商银行
```

这不改变统一按 `InnerCode` 过滤的要求。

### 8.3 公告详情与附件

接口：

```text
GET https://np-cnotice-stock.eastmoney.com/api/content/ann
```

参数：

```text
art_code={art_code}
client_source=web
page_index=1
```

已经确认返回：

```text
art_code
attach_list
attach_list_ch
attach_list_en
attach_size
attach_type
attach_url
attach_url_web
eitime
extend
is_ai_summary
is_rich
is_rich2
language
notice_content
notice_date
notice_title
page_size
page_size_ch
page_size_cht
page_size_en
security
short_name
```

中际旭创 H 股“海外监管公告”实测：

```text
art_code       AN202607301827500445
notice_title   海外监管公告
notice_date    2026-07-30
notice_content 4334字符
attach_url_web https://pdf.dfcfw.com/pdf/H2_AN202607301827500445_1.pdf?1785450119000.pdf
```

带时间戳和不带时间戳的 PDF 地址实测返回同一个文件。生产实现仍应优先使用详情接口实际返回的 `attach_url_web`，不要依赖自行拼接。

建档阶段不能为数千条公告逐条调用详情接口；详情接口只在实际阅读公告时调用。

部分 A 股公告详情的 `security` 会同时列出关联 A/H 证券，即使两边简称不同，例如：

```text
600938 中国海油 / 00883 中国海洋石油
601857 中国石油 / 00857 中国石油股份
600028 中国石化 / 00386 中国石油化工股份
```

但 H 股最新公告通常只列 H 股证券，关系并不对称。本方案已经决定由 AI 显式提交建档代码，因此程序不再依赖该字段自动推断公司关系。

**上游异常（2026-08-12 实测）：部分公告"PDF 链接"实际返回 Word 文档。** 源杰科技三份投资者关系活动记录表（调研纪要类）的 `attach_url_web` 链接后缀为 `.pdf`、响应头 `Content-Type: application/pdf`，但文件内容实为 docx（文件头 `PK\x03\x04`，Python 可用 `docx.Document` 直接打开）。受影响示例：

```text
AN202607231827288573  投资者关系活动记录表(2026年7月21日)        40559B  docx
AN202605221822681938  投资者关系活动记录表(业绩说明会)            26550B  docx
AN202603261820764245  投资者关系活动记录表(2026年3月25日)        28595B  docx
```

因此 `read_announcement` 的 `%PDF-` 魔数校验会拒绝并报"公告链接未返回 PDF 文件"，且不写入缓存（PDF 校验铁律保持不放松）。**待处理**：`downloader.py` 检测到 `PK\x03\x04` 魔数时可走 docx 解析通道（python-docx 读段落+表格），或至少把错误信息改为"链接返回的是 Word 文档而非 PDF"，避免 AI 误判为链接失效后绕道 curl 手动下载。

**搜索词语义鸿沟（2026-08-12 实测）：`keyword="招股书"` 返回 matched=0，但全量 604 条里明明有 H 股申请公告。** 原因：`keyword_matches` 只匹配 `title + column_name` 子串，而东财 A 股公告标题里没有"招股书"字样——招股书全文在港交所披露易，A 股渠道只有"关于向香港联合交易所有限公司递交H股发行及上市申请并刊发申请资料的公告"（2026-03-25，`keyword="H股"` 可命中 18 条）。AI 搜"招股书"落到 matched=0 死胡同且无任何指引。**待处理**：matched=0 时返回引导提示（如"未命中标题/栏目名，可换词如 H股/香港/发行，或省略 keyword 查看全量"）；是否加同义词典（"招股书"→"发行及上市/全球发售"）待定，注意词典维护成本与武断限制风险。

**H 股申请稿（招股书本体）读取通道边界（2026-08-12 实测）：公告 MCP 不接受披露易 URL。** `read_announcement`/`search_announcement` 的 url 白名单只有三类：东财 `pdf.dfcfw.com`、SEC EDGAR、**本地已存在的 PDF 路径**；传入 `https://www1.hkexnews.hk/app/sehk/2026/108326/documents/sehk26032500809.pdf` 直接报错"url 必须是东方财富…本地已存在的 PDF 文件路径，或 SEC EDGAR 文档链接"。**可行路径**：申请稿先手动下载到本地（如 `项目/_research_temp/源杰科技_H股申请稿_20260325.pdf`），再用本地路径调 read/search —— 实测可完整读取 391 页申请稿（产能/收入/销量/ASP 全有）。**待处理**：考虑是否把披露易 URL 加入白名单（HKEXnews 直连需处理其 UA/证书限制），或保持现状（下载到本地再读）。

**待办方向（2026-08-12 用户提出，暂不展开）：上市进程中公司的披露材料获取。** IPO 进行中 / H 股申请中的公司（如源杰 H 股申请中），披露在交易所 IPO 专区/披露易申请版本，东财公告渠道没有对应证券，现有建档+查询链路够不着。后续考虑：拟上市公司的披露源（A 股 IPO 专区、披露易申请版本、SEC S-1 等）是否纳入工具能力。用户明确暂不实施，仅记录方向。

**上市进程中公司披露支持边界（2026-08-12 实测）：现有工具以“证券代码已进入东财/SEC 映射体系”为分水岭，递表/聆讯阶段不能稳定覆盖。** 本轮用 `establish_company(action="check")`、`establish_company(action="establish")`、`query_announcements` 实测多阶段样本，结论如下：

| 市场/阶段 | 当前工具支持性 | 实测样本 | 说明 |
|---|---|---|---|
| A 股受理/问询/过会但尚无正式股票代码 | 不支持 | 钶锐锶、思哲睿 | `check` 返回 0；披露在交易所 IPO 审核专区，不在证券公告档案。 |
| A 股注册生效/发行中，已有正式股票代码 | 支持 | 宇树科技 `688836`、长裕集团 `603407`、盛龙股份 `001257`、高凯技术 `688835`、格林生物 `301688` | 建档成功；历史申报稿、上会稿、注册稿、招股意向书、发行公告等会归档到正式代码下。 |
| 三板/北交所在审但仍为三板证券 | 不支持 | 环能涡轮 `874798` | `check` 可出现三板候选，但 `establish` 被拒；当前设计不接股转系统公告。 |
| A+H 筹划/递表/申请版本阶段 | 只能支持 A 股进展公告，不支持 H 股申请稿本体 | 源杰科技、拓斯达、德业股份、聚辰股份、中文在线、汉得信息 | `check` 只返回 A 股候选；A 股公告可查“拟发行 H 股/递交申请”等进展，但披露易申请版本/招股书本体不在当前建档链路。 |
| 非 A 股上市申请人递表/处理中 | 不支持 | 奕斯伟计算、卡奥斯物联、希音、哥瑞利、本末动力、坦博尔 | 东财证券搜索无稳定候选，或误命中无关证券；当前工具没有“港交所申请人档案”入口。 |
| H 股通过聆讯但未进入发售/上市代码链条 | 不稳定，不能依赖 | 希音、本末动力、坦博尔、北京君正集成电路 | 外部 IPO 日历显示通过聆讯，但东财 `check` 返回 0 或只返回 A 股旧证券；说明“通过聆讯”本身不足以保证东财已生成 H 股代码。 |
| H 股全球发售/配发结果/新上市前后 | 支持较好 | 拿森科技 `02261`、剂泰科技 `07666`、中际旭创 `03308` | 建档后可查申请版本、聆讯后资料集、全球发售、配发结果、新上市及后续月报/自愿公告；东财会把早期 A1/PHIP 回填到 H 股代码档案下。 |
| H 股代码已能 `check` 到但公告建档失败 | 存在待排查个案 | 百利天恒 `02615` | `check` 返回 A 股 `688506` + H 股 `02615`，但 `establish(["02615"])` 返回“首次建档未能获取全部公告”。需后续排查东财公告接口、InnerCode 过滤或新代码同步问题。 |
| 美股未公开提交/无 ticker | 不支持 | Anthropic | 无 ticker/CIK 映射，当前 `establish_company` 无入口。 |
| 美股已公开 S-1/DRS 且 ticker+CIK 可映射 | 支持 | SPCX | `check("SPCX")` 返回 NASDAQ 正股；`establish(["SPCX"])` 成功并获取 77 条 SEC 提交，含 DRS/A、S-1、S-1/A、EFFECT、424B4、10-Q、13G。 |

对“东财什么时候生成 H 股代码”的阶段性判断：递表/A1/申请版本阶段通常没有；通过聆讯后也不稳定；进入全球发售、配发结果、新上市前后基本会有，并且会回填早期申请版本和聆讯后资料集。这个判断只能作为工具设计边界，不代表可精确还原东财生成代码的具体日期。

后续扩展方向（待讨论，不在当前实现）：

- 港交所披露易申请人通道：按申请人名称/申请编号检索申请版本、整体协调人公告、聆讯后资料集、正式招股章程、配发结果，不依赖东财 H 股代码。
- A 股 IPO 审核专区通道：覆盖受理/问询/上会/提交注册/注册生效前无正式代码阶段。
- `matched=0` 引导：标题/栏目子串搜索无命中时提示换词或省略 keyword，避免 AI 因“招股书”未命中而误判没有材料。
- HKEX URL 阅读白名单：评估是否允许直接读取 `www1.hkexnews.hk` PDF；若保留白名单限制，则错误信息明确提示“先下载到本地再读”。
- H 股新代码建档失败诊断：以百利天恒 `02615` 为样本，排查东财公告接口同步与 InnerCode 过滤边界。

### 8.4 东方财富互动问答

页面：

```text
https://guba.eastmoney.com/qa/qa_search.aspx?company=300308&qatype=1
```

页面底部“点击加载更多”不是通过页面 URL 的 `page=` 参数翻页。前端真实请求为：

```text
POST https://guba.eastmoney.com/interface/GetData.aspx
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
Referer: https://guba.eastmoney.com/qa/qa_search.aspx?company={code}&qatype=1
```

表单字段：

```text
path=question/api/Info/Search
param=code={code}&ps=15&p={page}&qatype=1
env=2
```

`param` 是 URL 编码后的内层参数字符串。

响应已经确认包含：

```text
rc
re
PageIndex
PageSize
TotalPage
count
```

`re[]` 中与本项目直接相关的字段：

```text
post_id
stockbar_code
stockbar_name
post_publish_time
post_display_time
ask_question
ask_answer
post_content
```

时间含义：

```text
post_publish_time  提问时间
post_display_time  回答后展示时间，作为回答时间和排序/日期筛选字段
```

中际旭创 `300308` 全量实测：

```text
count                     1697
PageSize                  15
TotalPage                 114
成功抓取页数             114
接收条数                 1697
post_id去重后             1697
最近五年按回答时间       1298
最早回答时间             2014-07-11
最新回答时间             2026-07-05
```

东方财富问答仅包含已回答问题。本项目不获取未回答问题。

首次建档翻完所有页面；后续从第一页开始增量抓取，遇到已有 `post_id` 后停止。

### 8.5 电话会议正文源（stockanalysis，2026-10-22 起）

**索引页**（“有哪些财季电话会”的唯一依据）：

```text
https://stockanalysis.com/stocks/{ticker}/transcripts/
```

- 页面直接列出全部电话会条目（`Earnings Call: Q2 2026` + 链接），条目标签就是公司财季（META `Q2 2026`、NVDA `Q2 2027`），与 `FY{year}-Q{q}` 一一对应；`qN-YYYY` 之外的条目（keynote、AGM 等）按正则排除。
- 实测覆盖：META 58 季（2012Q2–2026Q3）、NVDA 64 季（2011Q1–2027Q2）、LITE 30 季、APH 54 季；当天开完的电话会当天就有稿。
- 访问：纯 `requests` + 普通 Chrome UA 200，无 Cloudflare 挑战、无 cookie；连续请求未见 429（仍保留 1 秒串行限速）。

**正文页**：`/stocks/{ticker}/transcripts/{id}-q{q}-{year}/`

- 结构：`#transcript-panel-full` 内每个发言轮次是 `div.border-t.border-sharp.pt-5`，内含 speaker（`div.text-lg.font-bold`）与若干 `<p>`（句子包在 `span.transcript-sentence`）；站点级解析，不做公司级适配。
- 无独立日期字段；报告期不进正文，由工具从公告档案反查（见下）。

**财季标签与 report_date**：

- 财季标签直接取索引页的 `q{q}-{year}`，不再由 10-Q/10-K 推算（`_derive_quarters` 只保留用于把标签映射到报告期）。
- `report_date`/`form` 从本地公告档案的 10-Q/10-K 反查：有则附上，没有留空；刚开完会尚未提交 10-Q 时为空属正常（如 2026-10-21 的 META FY2026-Q3）。
- 是否存在电话会完全由索引页决定，不再受「有没有 10-Q/10-K」影响。
- ADR/外国发行人的电话会常挂在主上市代码下：美股代码页 404 时读个股页 `transcriptsLinkSymbol`（如 TSM → `TPE-2330`、BABA → `HKG-9988`），改走 `/quote/{exchange}/{code}/transcripts/`——站点级规则，不写公司特例表。实测 TSM 62 季、BABA 48 季、NIO 32 季、ASML 41 季。
- 只有个股页也没有 `transcriptsLinkSymbol`、或主上市代码页同样 404 时，才返回空索引 + note（不报错、不冒充有数据）。

**状态与缓存**：

- `ok`=正文已缓存；`missing`=正文页 404（该季上游未收录）；`failed`=网络/HTTP/解析异常（带 `http_status` 或 `error`）。
- 全文缓存（每财季一篇 ~40–60K 字符）；首次同步下载最近 12 财季，`period` 指定早期季时按需补下载；`force_refresh` 重试全部非 `ok` 财季。

**已退役来源（2026-10-22）**：

- Alpha Spread：原主源，正文是 `div.comment` 结构。2026-09 起 Cloudflare managed challenge，须 `alphaspread_cookies.json` 的 cf_clearance + 配套 UA，而 cf_clearance 绑定出口 IP，2026-09-10 之后长期 403；同时站点改版（`div.comment` → `article.earnings-call__turn`）使旧解析器取不到正文。已整体移除。
- AlphaStreet（`news.alphastreet.com`）：原备用源（Alpha Spread 404 时补位，只覆盖最近约 8 季）。CloudFront 对整站（含 robots.txt）返回 403，换 UA/有头浏览器均无效（区域/IP 级封锁），不可用。

## 9. 当前代码入口与工作区状态

实现前应先阅读：

```text
src/ashare_announcements_mcp/api.py
    当前 A 股公告列表请求、全量和增量分页。

src/ashare_announcements_mcp/cache.py
    当前 cache/{股票代码}/announcements.json、PDF和解析缓存。

src/ashare_announcements_mcp/service.py
    当前单证券公告同步、筛选和分页。

src/ashare_announcements_mcp/server.py
    MCP工具入口。

src/ashare_announcements_mcp/company.py
    当前探索版证券搜索。它会过滤候选并自动同名补查，与最终check设计不一致。

tests/test_company.py
    当前探索版check测试，也需要随第一步一起调整。
```

临时真实探针：

```text
.codex-temp/source_probe.py
.codex-temp/zhongji_history_probe.py
```

临时探针只作证据，不应导入生产代码或纳入产品模块。

开发测试环境：

```powershell
$env:PYTHONPATH = 'src'
& 'D:\venvs\a-share-announcements\Scripts\python.exe' -m pytest -q
```

项目使用 `src/` 布局；不设置 `PYTHONPATH=src` 时，当前测试环境无法导入包。

当前工作分支：

```text
codex/establish-company-check
```

当前分支存在未提交的探索版 `check` 代码、测试、本文档和 `.codex-temp/`。下一位实现者应保留用户工作，不要擅自清理、重置或提交临时探针。

## 10. 不需要重复探索的事项

- 不需要再次研究问答页面的“点击加载更多”按钮；POST分页已经跑通。
- 不需要再次验证中际旭创问答能否全量获取；114页全部成功。
- 不需要再次验证东方财富能否查询H股公告；接口与A股基本同构。
- 不需要再次验证港股代码复用；`03308` 和 `00300` 已经证明必须按 `InnerCode` 过滤。
- 不需要再次比较带时间戳和不带时间戳的PDF地址；底层文件一致。
- 不需要再次设计A/H自动关系推断；已经决定由AI显式向 `establish` 提交一个或两个明确代码。
- 不需要新增缓存目录层级；已经决定保留现有每个证券代码一个目录，只新增 `cache/companies.json`。
