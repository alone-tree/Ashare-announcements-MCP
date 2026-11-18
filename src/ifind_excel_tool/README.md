# ifind_excel_tool：iFinD Excel 插件取数工作台

纯 CLI、公式库驱动、随用随开发。与 market_data_mcp 平级，零 import 依赖。

## 组成

| 部分 | 内容 |
|---|---|
| engine.py | Excel COM 执行层，从 market_data_mcp/ifind_excel.py 复制，独立定位工作簿 |
| cli.py | 极薄入口，只有 lookup / run / text 三个命令 |
| formula_library/verified-formulas.jsonl | 已验证公式，人工锚定，AI 优先检索 |
| formula_library/catalog.jsonl | 全量30281条指标索引，脚本生成，未验证 |
| recipes/ | 高频场景脚本，初期为空 |
| data/ifind_workspace.xlsx | 专用工作簿 |

## 用法

AI 取数流程：

1. `lookup` 查已验证库，拿到公式模板和参数。
2. 命中：写一次性脚本调 engine.fetch_matrix（数值）或 fetch_formulas（文本）执行。
3. 未命中：查 catalog.jsonl 找候选，推测写法小批实测；可靠则追加进 verified，可疑则转人工。
4. 反复使用的场景才写成 recipes/ 下的固定脚本。

CLI 示例（stdin JSON → stdout JSON）：

```bat
echo {"cmd":"lookup","keyword":"市盈率"} | python ifind_excel_tool\cli.py
echo {"cmd":"run","matrix":[["=@thsiFinD(...)"]]} | python ifind_excel_tool\cli.py
echo {"cmd":"text","formulas":["=@thsiFinD(...)"]} | python ifind_excel_tool\cli.py
```

## 库维护

- 已验证库只追加经确认的记录，字段定义见 formula_library/README.md。
- catalog.jsonl 由 build_catalog.py 从插件 excel_description.dat 生成，不手工编辑。
- 新公式转入已验证库的标准：返回非空非零、量级合理、参数在枚举内、同类样本横比一致。
- 文本字段（简称、日期）用 reading_mode=text，走 fetch_formulas(text_ok=True)。
