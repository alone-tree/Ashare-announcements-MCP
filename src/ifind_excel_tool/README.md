# ifind_excel_tool：iFinD Excel 插件取数工作台

纯 CLI、公式库驱动、随用随开发。与 market_data_mcp 平级，零 import 依赖。

## 组成

| 部分 | 内容 |
|---|---|
| engine.py | Excel COM 执行层，从 market_data_mcp/ifind_excel.py 复制，独立定位工作簿；启动前自动清除本工作簿的崩溃恢复残留 |
| cli.py | 极薄入口，只有 lookup / run / text / close 四个命令 |
| formula_library/verified-formulas.jsonl | 已验证公式，人工锚定，AI 优先检索 |
| formula_library/catalog.jsonl | 全量30281条指标索引，脚本生成，未验证 |
| recipes/ | 高频场景脚本，初期为空 |
| data/ifind_workspace.xlsx | 专用工作簿，只含 data 页（纯取数通道，永不保存） |

## 用法

AI 取数流程：

1. `lookup` 查已验证库，拿到公式模板和参数。
2. 命中：写一次性脚本调 engine.fetch_matrix（数值）或 fetch_formulas（文本）执行。
3. 未命中：按[公式来源与录入流程](formula_library/README.md#批量公式录入与验证流程)核对插件原文。
4. 反复使用的场景才写成 recipes/ 下的固定脚本。

CLI 示例（stdin JSON → stdout JSON）：

在仓库根目录执行（必须设 PYTHONPATH=src 并用项目 venv）：

```bash
echo '{"cmd":"lookup","keyword":"净利润","limit":5}' | PYTHONPATH=src D:/venvs/a-share-announcements/Scripts/python.exe src/ifind_excel_tool/cli.py
```

`run`/`text` 同理，把上面 JSON 换成 `{"cmd":"run","matrix":[...]}` 或 `{"cmd":"text","formulas":[...]}`；用完可发 `{"cmd":"close"}` 不保存关闭专用 Excel。

一次性脚本示例（写到 `.codex-temp/` 用完即删）：

```python
import sys
sys.path.insert(0, 'src')
from ifind_excel_tool import engine

# 先用 lookup 拿 formula_template，替换 {code}/{date}/{type} 占位符后填入完整公式
matrix = [
    ['=@thsiFinD("ths_revenue_stock","600519.SH","2025-12-31",100)'],
    ['=@thsiFinD("ths_np_stock","600519.SH","2025-12-31",100)'],
]
r = engine.fetch_matrix(matrix, timeout=300)
print(r['values'], r.get('errors'))
# engine 返回裸数值二维数组；单位取 lookup 的 unit 字段（注意 EPS 为元/股，与金额元不同）
```

公式模板里的占位符有 `{code}`、`{date}`、`{type}` 三种，需自行替换成完整公式；engine 只接受以 `=@thsiFinD(` 开头或 `=thsiFinD(` 开头的完整公式。

## 库维护

- 公式来源、字段定义和验收标准见[公式库说明](formula_library/README.md)。
- catalog.jsonl 由 build_catalog.py 从插件 excel_description.dat 生成，不手工编辑。
- 文本字段（简称、日期）用 reading_mode=text，走 fetch_formulas(text_ok=True)。
