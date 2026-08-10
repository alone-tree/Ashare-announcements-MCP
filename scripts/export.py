"""把当前源码导出为可直接注册的用户版（一次导出两个 MCP 到同一目录）。

- ashare_announcements_mcp：A股/港股/美股公告阅读（东财 + SEC EDGAR）
- market_data_mcp：三市场行情/财报/指标/概况（新浪/iFinD/东财）

两者共用同一数据根目录（用户版目录本身）：公告用 ASHARE_ANNOUNCEMENTS_ROOT、
market-data 用 MARKET_DATA_ROOT 环境变量控制（不设时默认当前目录=用户版目录）。
market-data 需要用户版根目录 config.yaml（iFinD 凭据等，模板 config.example.yaml，不进 git）。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PACKAGES = {
    "ashare_announcements_mcp": {
        "source": ROOT / "src" / "ashare_announcements_mcp",
        "requirements": (
            "mcp>=1.10,<2\n"
            "requests>=2.31,<3\n"
            "pymupdf>=1.28,<2\n"
            "pymupdf4llm>=1.28,<2\n"
            "pymupdf-layout>=1.28,<2\n"
            "rapidocr>=3.9,<4\n"
            "onnxruntime>=1.20,<2\n"
            "markdownify>=0.13,<1\n"
        ),
    },
    "market_data_mcp": {
        "source": ROOT / "src" / "market_data_mcp",
        "requirements": (
            "mcp>=1.10,<2\n"
            "akshare>=1.18.83,<2\n"
            "pandas>=2.0,<3\n"
            "yfinance>=1.5,<2\n"
            "pyyaml>=6.0,<7\n"
        ),
    },
}

USER_README = """# 投资数据 MCP（用户版）：公告阅读 + market-data

本目录包含两个可独立注册的 MCP，共用同一数据根目录（本目录）：

| MCP | 包 | 入口 | 能力 |
|---|---|---|---|
| A股公告阅读 | `ashare_announcements_mcp` | `ashare_announcements_mcp/server.py` | A/H/B 股公告（东财）+ 美股公告（SEC EDGAR）+ 互动问答；建档/查询/阅读/检索 |
| market-data | `market_data_mcp` | `market_data_mcp/server.py` | 三市场行情（新浪单源 + 美股 iFinD 后复权/成交额）、股本、市值估算；财报/比率/概况 |

## MCP 注册（stdio）

command 指向安装了依赖的 Python（本机 `D:\\venvs\\a-share-announcements\\Scripts\\python.exe`），
args 指向对应包入口 `server.py`，cwd 设为**本目录**（缓存落在本目录 `cache/`）。

market-data 建议显式设置环境变量 `MARKET_DATA_ROOT` 为本目录绝对路径
（不设时以 cwd 为准，缓存与自动导出均在本目录下）。

## 批处理 CLI（stdin JSON → stdout JSON）

```bat
echo {"tool": "query_batch", "stock_codes": ["600519"]} | python ashare_announcements_mcp\\cli.py
echo {"tool": "get_quote_batch", "codes": ["600519.SH"], "vars": ["close"]} | python market_data_mcp\\cli.py
```

CLI 顶层请求字段是 `tool`，与 MCP 工具一一对应；market-data 代码必须带市场后缀
（600519.SH / 920002.BJ / 00700.HK / AAPL.US）。

## 依赖安装

```bat
python -m pip install -r requirements.txt
```

market-data 的 iFinD 通道（美股后复权/成交额/股本）需要 iFinDPy 官方 SDK：
按官方安装包在 venv site-packages 写入 `iFinDPy.pth` 指向 SDK 目录（本机已装）。

## 用户配置（config.yaml）

本目录的 `config.example.yaml` 是配置模板：复制为 `config.yaml` 后填入你拥有的凭据，
放进去就能用（没有的数据源留空自动跳过）。支持：

- `ifind.accounts`：同花顺 iFinD 账号列表（多账号按顺序尝试登录，第一个成功即用；
  美股后复权/成交额/股本需要它）
- `eodhd.api_key`：EODHD API key（可选）

`config.yaml` 含真实凭据，不会随 export 覆盖（export 只更新模板）。

## 缓存与导出位置

- 公告缓存：`cache/{股票代码}/`
- market-data 缓存：`cache/{代码}/`（quote_daily_raw / quote_daily_hfq / quote_daily_amount / shares）
- 超长行情自动导出：`cache/_auto_export/`
- 审计日志：`logs/requests.jsonl`（market-data 每次上游请求）
"""


def export(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name, pkg in PACKAGES.items():
        package_target = target / name
        package_target.mkdir(parents=True, exist_ok=True)
        for source_file in pkg["source"].rglob("*.py"):  # 递归：market-data 含 providers/ 子目录
            rel = source_file.relative_to(pkg["source"])
            dest = package_target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, dest)
    (target / "cache").mkdir(exist_ok=True)
    # 配置模板：用户版带一份 config.example.yaml（真实凭据由用户复制为 config.yaml 后填写；
    # 不覆盖用户已有的 config.yaml）
    example = ROOT / "config.example.yaml"
    if example.exists():
        shutil.copy2(example, target / "config.example.yaml")
    requirements = "".join(pkg["requirements"] for pkg in PACKAGES.values())
    (target / "requirements.txt").write_text(requirements, encoding="utf-8")
    (target / "README.md").write_text(USER_README, encoding="utf-8")
    print(f"已导出用户版（两个 MCP）：{target.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="导出公告阅读 + market-data 双 MCP 用户版")
    parser.add_argument("target", type=Path, help="用户版目标目录")
    args = parser.parse_args()
    export(args.target)


if __name__ == "__main__":
    main()
