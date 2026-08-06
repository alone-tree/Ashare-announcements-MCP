"""导入本地 PDF 公告材料为本地公司档案。

用于未上市公司（如 IPO 终止）的申报稿、问询回复等本地材料：
扫描指定目录下的 PDF（文件名建议格式：YYYY-MM-DD：公司名：标题.pdf），
复制到缓存 cache/{code}/pdfs/，生成 announcements.json，并注册到 companies.json。

用法：
    python scripts/import_local.py --code LOCAL-YXG --name "大连优欣光" --dir "D:\\材料目录"
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ashare_announcements_mcp.cache import load_companies, pdf_dir, save_cache, save_companies

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[\s:：]*(.*)$")


def _parse_filename(filename: str) -> tuple[str | None, str]:
    """从文件名提取 (日期, 标题)。支持 '2021-05-25：优迅科技：xxx.pdf' 格式。"""
    stem = Path(filename).stem
    m = DATE_RE.match(stem)
    if not m:
        return None, stem
    date_part = m.group(1)
    title = m.group(2).strip()
    # 去掉 "公司名：" 前缀，保留标题主体
    if "：" in title:
        parts = title.split("：", 1)
        title = parts[1].strip() or parts[0].strip()
    return date_part, title


def _copy_name(source_dir: Path, pdf: Path) -> str:
    """缓存内目标文件名：子目录文件带父目录名前缀，避免重名覆盖。"""
    relative = pdf.relative_to(source_dir)
    parts = list(relative.parts)
    if len(parts) > 1:
        parts = [parts[-2], parts[-1]]
    name = "_".join(parts)
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def import_local(code: str, name: str, source_dir: Path, dry_run: bool = False) -> dict:
    code = code.upper()
    source_dir = Path(source_dir).resolve()
    if not source_dir.is_dir():
        raise ValueError(f"目录不存在：{source_dir}")

    pdfs = sorted(source_dir.rglob("*.pdf"))
    if not pdfs:
        raise ValueError(f"目录中没有 PDF 文件：{source_dir}")

    items = []
    copied: list[Path] = []
    for pdf in pdfs:
        # 日期优先级：文件名 → 父目录名 → 文件修改时间
        date_part, title = _parse_filename(pdf.name)
        if not date_part and pdf.parent != source_dir:
            date_part, _ = _parse_filename(pdf.parent.name)
        if not date_part:
            date_part = datetime.fromtimestamp(pdf.stat().st_mtime).strftime("%Y-%m-%d")
        target = pdf_dir(code) / _copy_name(source_dir, pdf)
        if not dry_run and not target.exists():
            shutil.copy2(pdf, target)
            copied.append(target)
        elif dry_run:
            copied.append(target)
        items.append(
            {
                "code": _copy_name(source_dir, pdf),
                "url": str(target),
                "title": title,
                "display_time": f"{date_part} 00:00:00",
                "column_name": "本地材料",
                "short_name": name,
            }
        )

    if not dry_run:
        save_cache(
            code,
            items,
            {"cache_complete": True, "local_import": True, "source_dir": str(source_dir)},
        )
        registry = load_companies()
        companies = registry["companies"]
        aliases = registry["aliases"]
        companies[code] = {
            "local": True,
            "name": name,
            "securities": [{"code": code, "market": "LOCAL", "name": name, "classify": "LOCAL", "inner_code": ""}],
        }
        aliases[code] = code
        aliases[name] = code
        save_companies({"companies": companies, "aliases": aliases})

    return {
        "code": code,
        "name": name,
        "source_dir": str(source_dir),
        "pdf_count": len(pdfs),
        "items": items,
        "copied": [str(p) for p in copied],
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="导入本地 PDF 公告材料为本地公司档案")
    parser.add_argument("--code", required=True, help="本地公司代码，如 LOCAL-YXG")
    parser.add_argument("--name", required=True, help="公司名称，如 大连优欣光")
    parser.add_argument("--dir", required=True, help="PDF 材料目录")
    parser.add_argument("--dry-run", action="store_true", help="只扫描不写入")
    args = parser.parse_args()

    result = import_local(args.code, args.name, args.dir, dry_run=args.dry_run)
    print(
        f"导入 {result['pdf_count']} 个 PDF → {result['code']}（{'dry-run' if result['dry_run'] else '已写入'}）"
    )
    for item in result["items"]:
        print(f"  {item['display_time'][:10]}  {item['title']}")


if __name__ == "__main__":
    main()
