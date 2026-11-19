# 公式库字段说明

## verified-formulas.jsonl（已验证）

每行一条，字段：

| 字段 | 含义 |
|---|---|
| path | 插件函数搜索树路径，斜杠分隔，只到分组层（如资产负债表/流动资产），不含具体科目名 |
| name / aliases | 中文名与别名，用于检索。name 前导空格（每级4个）是报表内层级缩进，勿 strip；层级同时以 parent_name 标直接上级纯名称（path 相同的父子不另标 path，多层只标直接上级不穿透） |
| indicator | iFinD 指标码 |
| formula_template | 带 {code}/{date}/{type} 占位符的完整公式；喂给 engine 前需自行替换成完整 thsiFinD 公式 |
| definition / algorithm | 定义与算法原文 |
| parameters | 数组，每项 position/name/meaning/options/default |
| source / unit | 来源与单位，原文为空则留空 |
| example / example_value | 示例公式与实测值 |
| verification | verified 或 verified_with_caveat |
| verified_at / evidence | 验证日期与证据出处 |
| notes | 仅本条专属备注（口径限制、错值反例）；通用规则不放这里，见 general-notes.jsonl |
| reading_mode | matrix（数值）或 text（文本，走 text_ok=True） |

verified_with_caveat 表示公式正确但有限制条件，返回数据时必须带出 notes 提示。

## general-notes.jsonl（通用注释库）

每条是一条对一类公式生效的通用规则，跨多条公式复用，不在各条 notes 重复。

| 字段 | 含义 |
|---|---|
| id | 序号，简单递增 |
| scope | 生效范围，按公式 path 前缀匹配；公式 path 以 scope 开头即生效 |
| note | 规则正文 |

lookup 命中公式时，按该公式 path 找出所有前缀匹配的通用注释，作为每条 hit 的 general_notes 一起返回（含 id 与 note）；单条 notes 只放本条专属备注。

## catalog.jsonl（全量索引）

由 build_catalog.py 从 C:/Program Files/iFinD/etc/datacube/excel_description.dat 生成。
保留定义/算法/参数原文/参数枚举/来源/单位/ui_path，verification 固定为 unverified。
只作查漏与候选推测，不直接当可用公式。

## 数据来源等级（2026-11-18 踩坑后定）

权威来源只有两类：用户从 iFinD 插件界面提供并确认的描述与值；真实 Excel 取数且人工确认过的结果。

不可靠来源：catalog.jsonl（来自 excel_description.dat，信息可能旧/错/笼统）、2018手册、历史仓库、AI 自己填的 path/name/source/unit。**严禁用不可靠来源核对或覆盖已验证库**。

具体教训：
- 不得拿 catalog 的 source/unit 覆盖已有记录。曾把用户实测的港元数据「港元」改成 catalog 的「元」，把对值改错。原文为空就留空，不从其他市场推断。
- 枚举只认用户贴的参数说明或实测确认的，不从相似指标搬。曾把 ths_close_price_stock 的105/106/101/102 误塞给 close_no_forward（插件只有100/107/108）。
- path/name 以用户从插件界面贴的为准，不自己按理解填，不从历史仓库路径映射推测。
- 无 example_value 的记录不得标 verified，只能 verified_with_caveat。
- 修正须经 update_verified.py 并记录到 correction-log.jsonl；修正只改用户确认过的字段。

总原则：宁可库里少几条，不能有一条错的。

## 转入规则

未验证公式经推测、实测后，满足全部条件才转入已验证库：
返回非空非零、量级合理、参数取值在说明库枚举内、同类样本横比一致。
任一条件不满足则标可疑，列候选与实测值交人工判定，不自动入库。