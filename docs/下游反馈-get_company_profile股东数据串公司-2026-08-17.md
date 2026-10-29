# get_company_profile 股东数据串公司问题（2026-08-17）

2026-10-29复核状态：本文记录旧新浪路径的历史问题。当前A股及北交所公共入口已改用iFinD，旧股东缓存不进入该路径；源码中的旧新浪错误写法仍保留，不视为已修正。当前有效约束见[架构§5](market-data架构设计.md#5-公司信息获取工具-get_company_profile)，本轮防回归及真实请求结果见[决策记录](决策记录.md)。

## 现象

调用 `get_company_profile(code="688498.SH", sections=["holders"])` 后，缓存文件 `cache/688498.SH/company/holders.json` 写入了中国平安的股东数据。文件中的第一大股东为“中国平安保险（集团）股份有限公司－集团本级－自有资金”，持股 9,618,540,236 股、持股比例 49.56%，与源杰科技不符。

## 根因

`src/market_data_mcp/providers/company_info.py` 的 `fetch_sina_holders()` 给证券代码增加了市场前缀：

```python
symbol = ("bj" if mc.market == "BJ" else ("sh" if mc.suffix == "SH" else "sz")) + mc.code
ak.stock_main_stock_holder(stock=symbol)
```

当前 AKShare 的 `stock_main_stock_holder()` 接受裸六位代码，并将参数直接拼入新浪 URL：

```text
https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_StockHolder/stockid/{stock}.phtml
```

因此工具实际访问了无效路径 `stockid/sh688498.phtml`。新浪没有返回错误，而是静默回落到默认股票中国平安；AKShare随后正常解析页面，工具误判为成功并写入目标公司的缓存。

## 实际复现

错误参数：

```python
ak.stock_main_stock_holder(stock="sh688498")
```

返回中国平安股东。

正确参数：

```python
ak.stock_main_stock_holder(stock="688498")
```

返回源杰科技股东，前几名为 ZHANG XINGANG、秦燕生、秦卫星、宁波创泽云、张欣颖。

## 影响范围

`fetch_sina_holders()` 对 A 股和北交所代码统一添加 `sh`、`sz` 或 `bj` 前缀，因此所有通过该函数新建或刷新的股东缓存都可能写入错误公司数据。现有 `company/holders.json` 不能默认视为可信，需要按需清除后重建。

## 2026-08-17提出的处理方向（历史记录）

当时开发库未修改，提出以下处理方向；该清单不替代上述当前路径约束，也不授权删除现有缓存：

1. 将 `stock_main_stock_holder()` 的参数改为 `mc.code`；
2. 增加一个最小回归测试，确认调用参数是裸代码；
3. 删除受影响的 `company/holders.json` 后重新获取；
4. 可向 AKShare 反馈：无效代码路径会静默回落到默认股票，建议上游对页面证券代码与请求参数不一致的情况显式报错。
