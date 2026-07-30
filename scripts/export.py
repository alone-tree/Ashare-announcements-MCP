"""把当前源码导出为可直接注册的用户版 MCP。"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "ashare_announcements_mcp"
REQUIREMENTS = (
    "mcp>=1.10,<2\n"
    "requests>=2.31,<3\n"
    "pymupdf>=1.28,<2\n"
    "pymupdf4llm>=1.28,<2\n"
    "pymupdf-layout>=1.28,<2\n"
    "rapidocr>=3.9,<4\n"
    "onnxruntime>=1.20,<2\n"
)
USER_README = """# A 股公告阅读 MCP（用户版）

MCP 入口：`ashare_announcements_mcp/server.py`

批处理 CLI 入口：

```bat
python ashare_announcements_mcp\cli.py
```

CLI 从 stdin 接收一个 JSON 请求，stdout 只返回一个 JSON 响应。支持 `query_batch`、`inspect_batch`、`read_batch`，与 MCP 共用公告档案和 PDF 缓存。

依赖安装：

```bat
python -m pip install -r requirements.txt
```

MCP 使用 stdio 传输，客户端 command 指向安装了上述依赖的 Python，args 指向入口文件。
运行缓存保存在本目录的 `cache/{股票代码}/`。

`query_announcements` 首次查询会建立该公司的完整公告档案，之后每次查询前自动补充最新公告。每页固定最多返回 50 条；关键词之间用空格表示 OR，用大写或小写 `AND` 表示 AND。

阅读长公告时先调用 `inspect_announcement`，再用 `search_announcement` 找到相关页，最后用 `read_announcement` 读取页段。原生页面使用 PyMuPDF Layout 分批转为 Markdown，并自动排除页眉页脚；扫描页按需使用 RapidOCR，结果会缓存。扫描页检索每次最多处理 3 页，若 `search_complete=false`，请用相同参数继续调用。
"""


def export(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    package_target = target / "ashare_announcements_mcp"
    package_target.mkdir(parents=True, exist_ok=True)
    for source_file in SOURCE.glob("*.py"):
        shutil.copy2(source_file, package_target / source_file.name)
    (target / "cache").mkdir(exist_ok=True)
    (target / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
    (target / "README.md").write_text(USER_README, encoding="utf-8")
    print(f"已导出用户版：{target.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 A 股公告阅读 MCP 用户版")
    parser.add_argument("target", type=Path, help="用户版目标目录")
    args = parser.parse_args()
    export(args.target)


if __name__ == "__main__":
    main()
