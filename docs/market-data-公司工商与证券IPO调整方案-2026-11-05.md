# 公司工商信息与证券 IPO 信息调整方案

日期：2026-11-05。状态：完整分组暂缓，尚未修改业务实现。用户随后要求先只处理行情必要资料，当前范围见[内地 Excel 行情实施方案](内地Excel行情接入实施方案-2026-11-05.md)；本文其余字段清单保留为后续规划。

本方案承接用户本轮清单。现行行为仍见[架构§5](market-data架构设计.md#5-公司信息获取工具-get_company_profile)，上游原始返回见[支持情况§14](../字段与数据源支持情况.md#14-股票种类同公司代码及简称输入的-sdk-实测2026-11-05)。行情整组接入仍由[行情方案](market-data-Excel行情整组取数方案-2026-11-04.md)维护，本文只负责公司信息分组及其缓存。

用户随后将讨论扩展到搜索、身份确认、建档及行情/财报/公告共同使用档案的总体流程，父决策见[公司建档与研究流程方案](公司建档与跨工具研究流程方案-2026-11-05.md)。该讨论可能进一步影响证券代码的展示归属，尚未据此改写本方案字段清单或业务实现。

## 一、范围与脑图核对

- 当前工作树脑图的内地分支为 IPO 信息 17 项、工商信息 25 项；开发主目录磁盘脑图为 IPO 信息 18 项（增加股份类型）、工商信息 25 项。两份均已只读通读相关分支及备注，未覆盖、同步或修改脑图。
- 用户截图使用“证券IPO信息”“公司工商信息”名称；本轮文字清单是调整依据。IPO 清单的上市日期出现两次，去重后为 20 项；工商清单为 24 项，第一项代码含义的问题见第四节。脑图原有数量标签不作为新清单数量。
- 仅调整 SH/SZ/BJ 的公司信息，继续使用 iFinD Python SDK；本轮不将公司信息切到 Excel，不扩展 HK/US 公司信息接口。公司内部包含关联境外证券代码不等于已经接入该市场公司信息。
- 复用 `get_company_profile` 与现有 `information_type="profile"/"ipo"`，中文含义分别为公司工商信息、证券 IPO 信息。不新增工具或额外模式；股东、年度分红、盈利预测保持当前内容。

## 二、证券 IPO 信息：20 项

| 对外科目 | iFinD 指标 |
| --- | --- |
| 上市板块 | `ths_listedsector_stock` |
| 交易所 | `ths_listing_exchange_stock` |
| 上市日期 | `ths_ipo_date_stock` |
| 股份类型 | `ths_stock_varieties_stock` |
| 发行股数 | `ths_ipo_quantity_stock` |
| 发行价格 | `ths_ipo_price_stock` |
| 募集资金总额 | `ths_ipo_rc_stock` |
| 募集资金净额 | `ths_ipo_actual_rc_stock` |
| 发行后总股本 | `ths_total_shares_after_ipo_ld_stock` |
| 发行后市盈率 | `ths_ipo_pe_dlt_stock` |
| 发行后市净率 | `ths_ipo_pb_stock` |
| 发行费用 | `ipo_fee` |
| 保荐机构（主承销商） | `ths_ipo_main_underwrite_stock` |
| 保荐代表人 | `ths_ipo_sponsor_representative_stock` |
| 发行人律师 | `ths_law_firm_stock` |
| 经办律师 | `ths_lawyer_stock` |
| 会计事务所 | `ths_accounting_firm_stock` |
| 经办会计师 | `ths_accountant_stock` |
| 资产评估机构 | `ths_asset_evaluate_org_stock` |
| 经办评估师 | `ths_charged_evaluator_stock` |

现有 IPO 已有 17 项，包含上市日期；新增上市板块、交易所、股份类型三项，即为 20 项，不重复增加上市日期。前两项从 profile 移出；股份类型已经通过用户提供的 SDK 原式验证，可用于程序内部识别输入证券的 A/B 类别，具体取股本规则仍属行情方案。

发行费用沿用已验证的参数及基础单位归一方式，发行后 PB 与其他既有 IPO 字段保持原式；本次分组不改变数值口径或增加计算字段。

## 三、公司工商信息：24 项目标清单

除第一项的命名建议外，下表对应用户列出的工商信息；不额外保留其未列出的证券简称。现有 `profile` 25 项移出上市板块、交易所、上市日期，移除证券简称，增加 B/H/美股关联代码三项，数量为 24 项。

| 对外科目 | iFinD 指标 |
| --- | --- |
| 当前证券代码（命名建议，原清单为 A 股证券代码） | `ths_thscode_stock` |
| B 股证券代码 | `ths_corp_bshare_code_stock` |
| H 股证券代码 | `ths_corp_hshare_code_stock` |
| 美股证券代码 | `ths_us_stock_code_stock` |
| 公司名称 | `ths_corp_cn_name_stock` |
| 公司网站 | `ths_corp_website_stock` |
| 成立日期 | `ths_established_date_stock` |
| 注册地址 | `ths_reg_address_stock` |
| 办公地址 | `ths_office_address_stock` |
| 法定代表人 | `ths_legal_representative_stock` |
| 企业性质 | `ths_corp_nature_stock` |
| 董事长 | `ths_chairman_stock` |
| 总经理 | `ths_general_manager_stock` |
| 控股股东 | `ths_controlling_holder_stock` |
| 控股股东持股比例 | `ths_controlling_holder_held_ratio_stock` |
| 实际控制人 | `ths_actual_controller_stock` |
| 实际控制人持股比例 | `ths_actual_controller_held_ratio_stock` |
| 主要产品 | `ths_mo_product_name_stock` |
| 产品类型 | `ths_mo_product_type_stock` |
| 申万行业 | `ths_the_ths_industry_stock` |
| 证监会行业 | `ths_the_new_csrc_industry_stock` |
| 主营业务 | `ths_main_businuess_stock` |
| 员工人数 | `ths_ygzs_new_stock` |
| 上市以来违规次数 | `ths_int_illegality_num_stock` |

行业、主营业务、员工人数和违规次数沿用当前已验证参数。上市日期虽然移出 profile 对外字段，仍是违规次数的内部取数依赖：请求 profile 时可在原批次中携带上市日期供计算使用，返回及写入 profile 的业务数据时不再暴露它，不为此连带获取整份 IPO 资料。

## 四、证券代码的实测差异与未定命名

`ths_thscode_stock` 在京东方 B 返回 `200725.SZ`，在伊泰 B 返回 `900948.SH`，不能统一命名为 A 股证券代码。用户随后明确没有“所属 A 股代码”指标；不再寻找或猜测该指标，也不通过 B 股前缀或关联代码反推 A 股。

建议将这一项称为“当前证券代码”，保留实际返回含义，仍维持四个代码字段。该名称尚待用户确认，不据此修改公共返回键。

B/H/美股关联代码保留原始字符串及前导零。关联字段可能保留已退市证券；原值及空值忠实返回，不据非空自动认定当前上市关系。本次简称试验返回参数错误，不增加简称输入、自动搜索或代码补全能力；正式入口继续使用已有的带市场后缀代码。

## 五、拟改动位置与缓存影响

1. `providers/company_ifind.py`：调整 `PROFILE`、`IPO` 的字段归属，增加三个关联代码和股份类型；保留原有日期参数、费用单位及违规次数所需的内部日期依赖。
2. `company_ifind_service.py`：继续复用 `company_data/profile.json`、`company_data/ipo.json` 及当前 30 天刷新规则。旧缓存缺少新字段时按需刷新相应 section，不能因缓存仍新鲜而一直缺股份类型或关联代码；空值与缺少字段键分开。成功后仅保存新分组字段；失败沿用现有旧值及 stale 语义，不伪造新字段值。
3. 不清空全局缓存、不迁移公告注册表、不建立公司级共享缓存。A/B 同公司仍按输入证券代码使用现有独立缓存，避免在此次分组中扩展公司归并机制。
4. `company_service.py`、`market_help.py`、`server.py` 及相关调用点：对齐两类中文说明和返回字段；MCP/CLI 继续共用业务实现，参数签名不变。行情分类读取 IPO 中的股份类型，不再把这一项放进 profile。
5. 验证通过后更新架构§5及帮助，并记录决策；本方案不提前修改现行架构为已实施状态。脑图由用户维护，本轮保持原文件不变。

## 六、执行及验收

本轮已完成 XMind 相关分支阅读、现有字段和依赖核对、用户四字段代码查询及简称试验；尚未实施上述修改。

命名与方案确认后，逐步实施并验证：

- 对照本方案核对 IPO 20 项和工商 24 项，上市日期对外只在 IPO；违规次数仍能按真实上市日期正常取数。
- 验证京东方 A/B、中际旭创及伊泰的代码原值，不将 B 股代码写成 A 股代码，不把历史关联 H 股自动当成有效上市证券。
- 用独立缓存副本验证旧 profile/ipo 缺新字段时的按需刷新、成功空值复用及失败保留旧值；不操作用户正式缓存。
- 通过开发版 MCP/CLI 的代表性真实调用核对完整返回和一致性，再跑相关回归检查；完成后本地提交，不自行导出或推送。
