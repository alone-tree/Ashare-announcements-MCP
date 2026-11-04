# A股总市值与总股本切 iFinD 方案（2026-11-04）

> 状态：待用户确认后实施。文档为临时方案稿，执行完成后按项目规则删除，Git 恢复位置记入决策记录。

## 一、背景

XMind「代码实际情况」页 A 股分支已把总股本定为 `ifind totalShares`、总市值定为 `ifind totalCapital`，代码仍是本地计算法（`total_shares × 不复权收盘`）。决策记录 2026-11-03「A股市值口径决定（XMind已同步，代码未实施）」已拍板同一口径。本方案把这两项落到代码，其余不变。

## 二、范围

- 改动市场：A 股、B 股、北交所（market `A`、`BJ`）。
- 不变：港股、美股总市值继续现算；A 股流通股本仍新浪 `outstanding_share`；流通市值仍现算；换手率仍 `volume ÷ 流通股本`；行情复权、骨架日期、返回结构不动。
- 目标：全部历史序列。近 5 年用 iFinD 序列批量，5 年以前用 BD 单点月频，与股本现有拼法一致。

## 三、数据源与口径（2026-11-04 实测，errorcode 全 0）

| 项 | 近 5 年（序列） | 5 年以前（单点） |
|---|---|---|
| 总股本 | `THS_HQ(code, "totalShares", "fill:Omit", start, end)` | `THS_BD(code, "total_shares", "YYYYMMDD")` |
| 总市值 | `THS_HQ(code, "totalCapital", "fill:Omit,Currency:RMB", start, end)` | `THS_BD(code, "ths_mv_back_test_stock", "YYYYMMDD")` |

实测证据：

- HQ 一次可取多代码、多指标，A 股、A+H、北交所、688235.SH 均可用；688235.SH 走 DS 单指标报 -4210，走 HQ 正常。
- 300308.SZ 近 5 年 `totalShares` 返回 1209 行（2021-11-04 至 2026-10-30，按交易日）。
- HQ 与 DS 股本同日同值（300308.SZ 2026-10-30 均 1,177,909,641 股），切换不产生序列跳变。
- B 股必须 `Currency:RMB`：900901.SH 不加为 24.3 亿（交易币种美元），加后 163.2 亿，与 BD 一致；对 A 股无影响（5 只样本与原币口径逐位相同）。
- BD `ths_mv_back_test_stock` 与 HQ `totalCapital` 同一口径：2021-11-04、2021-11-05 两只接口在 300308.SZ、600519.SH、601398.SH、900901.SH 上逐位相同，可无缝拼接。
- 反例记录：BD `ths_market_value_stock` 在 2015-2021 各日期返回同一固定值（600519 恒 22664.3 亿），不可用于历史；BD `totalCapital` 报 -209 参数无效；BD `close_price` 全日期 0.0。

边界处理：

- 未上市期间 BD 市值返回 `0.0`（688235.SH 2015-2021、920002.BJ 2021 前），按无值处理，不写 0 市值。
- BD 市值对股本变动有滞后：300308.SZ 2026-10-30 按旧股本 11.152 亿计 6167.2 亿，HQ 按新股本 11.779 亿计 6529.9 亿。滞后只影响 BD 段近期月份，5 年以前数据不受影响；段内以 HQ 为准。
- BD 单点为月频（日历月末），与股本现有拼法一致；非月末日期不补。

## 四、代码改动

1. `providers/ifind.py`
   - `fetch_shares`：A/BJ 改为近 5 年 HQ `totalShares` + 更早 BD `total_shares` 月末采样；港美保持现有 DS + BD 路径。字段仍写 `total_shares`，A/BJ 不写 `floating_shares`（归新浪）。
   - 新增 `fetch_market_value`：A/BJ 总市值，近 5 年 HQ `totalCapital` + 更早 BD `ths_mv_back_test_stock` 月末采样，写 `total_market_cap` 字段缓存，规则同 `fetch_shares`（先近后远、跳过已覆盖日期、失败不丢弃并 notes）。
2. `service.py`
   - 字段链：A/BJ 的 `total_market_cap` → `ifind.fetch_market_value`；港美仍现算。
   - `need_fields`：A/BJ 请求 `total_market_cap` 时只需该字段；`float_market_cap` 仍要 `close + floating_shares`；`turnover` 不变。
   - 组装：A/BJ 的 `total_market_cap` 取缓存字段值（前置填充规则同股本），不再 `total_shares × close`。
   - notes：A/BJ 不再输出「总市值/流通市值为估算值」；港美保留。
3. `server.py`、`market_help.py`：`total_market_cap` 说明按市场区分口径。
4. 缓存：A/BJ 新增字段文件 `total_market_cap`，结构同其它字段（items: date/value/source），静态历史不过期。

## 五、降级

- 字段级失败沿用现有机制：该字段无数据 + notes 说明，不整单拒绝。
- 不新增「失败回退计算法」分支：A 股直取失败时总市值为空，避免两种口径混在同一序列。

## 六、文档同步

| 文档 | 改动 |
|---|---|
| `docs/market-data架构设计.md` | §1.4 来源池（A/BJ 总市值改为 iFinD）、§2.4 市值（计算法改为港美适用 + A/BJ 直取）、§7 股本方案（A/BJ 切 HQ） |
| `字段与数据源支持情况.md` | 补本次实测：HQ `totalShares`/`totalCapital` 及 `Currency:RMB`、BD `total_shares`/`ths_mv_back_test_stock` 的覆盖与边界、`ths_market_value_stock` 早期失效与 `close_price` 为 0 的反例 |
| `docs/决策记录.md` | 实施完成后记一条，含 XMind 同步情况与旧实现替换经过 |
| XMind | 由用户维护，AI 不改 |

## 七、验收

- 单测：A 股市值/股本改 mock HQ 与 BD 批次，断言直取值；港美现有计算法断言不变；全量 pytest 通过。
- 真实调用：300308.SZ、601398.SH、900901.SH、688235.SH、920002.BJ 各取近 5 年与 5 年前各一段，核对交界日与 HQ 逐位一致、未上市日期为空、B 股人民币口径。
- 用户版导出与 MCP 实机调用各一次。
