# 公式库字段说明

## verified-formulas.jsonl（已验证）

每行一条，字段：

| 字段 | 含义 |
|---|---|
| path | 插件函数搜索树路径，斜杠分隔 |
| name / aliases | 中文名与别名，用于检索 |
| indicator | iFinD 指标码 |
| formula_template | 带 {code}/{date} 占位符的完整公式 |
| definition / algorithm | 定义与算法原文 |
| parameters | 数组，每项 position/name/meaning/options/default |
| source / unit | 来源与单位，原文为空则留空 |
| example / example_value | 示例公式与实测值 |
| verification | verified 或 verified_with_caveat |
| verified_at / evidence | 验证日期与证据出处 |
| notes | 口径限制、错值反例、别名关系 |
| reading_mode | matrix（数值）或 text（文本，走 text_ok=True） |

verified_with_caveat 表示公式正确但有限制条件，返回数据时必须带出 notes 提示。

## catalog.jsonl（全量索引）

由 build_catalog.py 从 C:/Program Files/iFinD/etc/datacube/excel_description.dat 生成。
保留定义/算法/参数原文/参数枚举/来源/单位/ui_path，verification 固定为 unverified。
只作查漏与候选推测，不直接当可用公式。

## 转入规则

未验证公式经推测、实测后，满足全部条件才转入已验证库：
返回非空非零、量级合理、参数取值在说明库枚举内、同类样本横比一致。
任一条件不满足则标可疑，列候选与实测值交人工判定，不自动入库。
