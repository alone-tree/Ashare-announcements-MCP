"""
高级公告工具
提供完整的公告获取、保存、读取和PDF处理功能
"""
import os
import json
from typing import List, Optional, Dict, Any

import pandas as pd

# 复用真实抓取与落盘能力
from .company_announcements import (
    fetch_all_pages_announcements,
    save_announcements_to_excel,
)


def fetch_and_save_announcements_to_excel(
    company_code: str,
    max_pages: int | None = None,
    page_size: int = 50,
    base_dir: str = "data/processed/announcements/excel",
) -> str:
    """
    抓取指定公司的公告"元数据"并保存为 Excel。
    max_pages 为 None 表示不限制页数（直到接口返回空列表）。
    返回 JSON 字符串：{"company_code", "count", "excel_path"}
    """
    if not company_code:
        return json.dumps({"error": "company_code 不能为空"}, ensure_ascii=False)

    try:
        items = fetch_all_pages_announcements(
            stock_code=company_code, page_size=page_size, max_pages=max_pages
        )
        if not items:
            return json.dumps(
                {
                    "company_code": company_code,
                    "count": 0,
                    "excel_path": "",
                    "message": "未获取到任何公告",
                },
                ensure_ascii=False,
            )

        path = save_announcements_to_excel(company_code, items, base_dir=base_dir)
        return json.dumps(
            {"company_code": company_code, "count": len(items), "excel_path": path},
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": f"抓取/保存失败: {str(e)}"}, ensure_ascii=False)


def _resolve_excel_path(company_code: Optional[str], excel_path: Optional[str], base_dir: str) -> str:
    """
    优先使用带后缀的文件名 {code}_announcements.xlsx；若不存在，兼容旧命名 {code}.xlsx。
    若传入 excel_path 则直接使用。
    """
    if excel_path:
        return excel_path
    if not company_code:
        return ""
    path_new = os.path.join(base_dir, f"{company_code}_announcements.xlsx")
    if os.path.exists(path_new):
        return path_new
    return os.path.join(base_dir, f"{company_code}.xlsx")


def read_announcements_from_excel(
    company_code: Optional[str] = None,
    excel_path: Optional[str] = None,
    base_dir: str = "data/processed/announcements/excel",
    offset: int = 0,
    limit: int = 50,
    keywords: Optional[List[str]] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> str:
    """
    从 Excel 读取公告元数据，支持分页与简单过滤。
    - company_code 或 excel_path 需提供其一；若两者皆给，优先 excel_path。
    - 返回 JSON：{"total", "returned", "offset", "limit", "items":[...], "excel_path"}
    """
    path = _resolve_excel_path(company_code, excel_path, base_dir)
    if not path:
        return json.dumps({"error": "必须提供 company_code 或 excel_path"}, ensure_ascii=False)
    if not os.path.exists(path):
        return json.dumps({"error": f"Excel 文件不存在: {path}"}, ensure_ascii=False)

    try:
        df = pd.read_excel(path)
    except Exception as e:
        return json.dumps({"error": f"读取Excel失败: {str(e)}"}, ensure_ascii=False)

    # 标准列名期望
    expected_cols = [
        "short_name",
        "stock_code",
        "display_time",
        "column_name",
        "title",
        "url",
        "code",
    ]
    # 兜底：仅保留存在的列
    cols = [c for c in expected_cols if c in df.columns]
    if cols:
        df = df[cols]

    # 解析时间，便于范围过滤与排序
    if "display_time" in df.columns:
        df["display_time_parsed"] = pd.to_datetime(df["display_time"], errors="coerce")
        df = df.sort_values("display_time_parsed", ascending=False)

    # 关键词过滤（title / column_name）
    if keywords:
        def _match_kw(row: Dict[str, Any]) -> bool:
            text = (
                (str(row.get("title", "")) + "\n" + str(row.get("column_name", ""))).lower()
            )
            return any(kw.lower() in text for kw in keywords)
        df = df[df.apply(_match_kw, axis=1)]

    # 日期范围过滤（闭区间）
    if (date_start or date_end) and "display_time_parsed" in df.columns:
        if date_start:
            try:
                start = pd.to_datetime(date_start)
                df = df[df["display_time_parsed"] >= start]
            except Exception:
                pass
        if date_end:
            try:
                end = pd.to_datetime(date_end)
                df = df[df["display_time_parsed"] <= end]
            except Exception:
                pass

    total = len(df)
    if limit is None or limit < 0:
        limit = total
    start_idx = max(0, int(offset))
    end_idx = start_idx + int(limit)
    df_slice = df.iloc[start_idx:end_idx]

    items = df_slice.drop(columns=[c for c in ["display_time_parsed"] if c in df_slice.columns]).to_dict(
        orient="records"
    )

    return json.dumps(
        {
            "excel_path": path,
            "total": int(total),
            "returned": int(len(items)),
            "offset": int(start_idx),
            "limit": int(limit),
            "items": items,
        },
        ensure_ascii=False,
    )


def read_pdf_text(
    file_path: str,
    start_page: int = 0,
    pages_read: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> str:
    """
    读取本地 PDF 文本（仅文本层），返回 JSON：包含文本与元信息。
    - start_page: 从第几页开始读取（0-based），默认 0（从头开始）。
    - pages_read: 本次读取多少页；None 表示读取到文档末尾。
    - max_chars: 返回文本的最大字符数；None 表示不限制（由调用者控制）。
    返回 JSON 字段示例：{"path", "start_page", "pages_read", "total_pages", "text", "chars_returned", "is_last_chunk"}
    """
    if not os.path.exists(file_path):
        return json.dumps({"error": f"文件不存在: {file_path}"}, ensure_ascii=False)

    try:
        import pdfplumber  # 轻量文本提取
    except Exception as e:
        return json.dumps({"error": f"缺少依赖 pdfplumber，请安装后再试: {str(e)}"}, ensure_ascii=False)

    texts: List[str] = []
    try:
        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            start_idx = max(0, int(start_page) if start_page is not None else 0)
            # 计算要读取的页数
            if pages_read is None:
                n = max(0, total_pages - start_idx)
            else:
                n = max(0, min(int(pages_read), max(0, total_pages - start_idx)))
            end_idx = start_idx + n
            for i in range(start_idx, end_idx):
                page = pdf.pages[i]
                txt = page.extract_text() or ""
                texts.append(txt)
    except Exception as e:
        return json.dumps({"error": f"读取PDF失败: {str(e)}"}, ensure_ascii=False)

    full = "\n\n".join(texts)
    if max_chars is not None:
        if len(full) > max_chars:
            full = full[: max(0, int(max_chars))]

    chars_returned = len(full)
    is_last_chunk = (start_idx + n) >= total_pages

    return json.dumps(
        {
            "path": file_path,
            "start_page": start_idx,
            "pages_read": n,
            "total_pages": total_pages,
            "text": full,
            "chars_returned": chars_returned,
            "is_last_chunk": is_last_chunk,
        },
        ensure_ascii=False,
    )


# --- OpenAI 工具描述 ---

FETCH_AND_SAVE_EXCEL_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch_and_save_announcements_to_excel",
        "description": "抓取指定公司的公告元数据（翻页）并保存为Excel；不下载PDF。",
        "parameters": {
            "type": "object",
            "properties": {
                "company_code": {"type": "string", "description": "六位股票代码，如 '688388'"},
                "max_pages": {"type": "integer", "description": "最大翻页数；可省略表示不限制(谨慎)"},
                "page_size": {"type": "integer", "description": "每页数量，默认50"},
                "base_dir": {"type": "string", "description": "Excel 保存目录，默认 'data/processed/announcements/excel'"},
            },
            "required": ["company_code"],
        },
    },
}

READ_ANNOUNCEMENTS_FROM_EXCEL_TOOL = {
    "type": "function",
    "function": {
        "name": "read_announcements_from_excel",
        "description": "从Excel读取公告元数据，支持分页与关键词/日期过滤。",
        "parameters": {
            "type": "object",
            "properties": {
                "company_code": {"type": "string", "description": "六位股票代码；与 excel_path 二选一"},
                "excel_path": {"type": "string", "description": "Excel 文件路径；与 company_code 二选一"},
                "base_dir": {"type": "string", "description": "默认 'data/processed/announcements/excel'"},
                "offset": {"type": "integer", "description": "起始偏移，默认0"},
                "limit": {"type": "integer", "description": "返回数量，默认50"},
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "关键字数组，匹配标题/分类"},
                "date_start": {"type": "string", "description": "起始日期（YYYY-MM-DD 可选时间）"},
                "date_end": {"type": "string", "description": "结束日期（YYYY-MM-DD 可选时间）"},
            },
            "required": [],
        },
    },
}

READ_PDF_TEXT_TOOL = {
    "type": "function",
    "function": {
        "name": "read_pdf_text",
        "description": (
            "读取本地PDF文本内容（仅文本层）。支持按页分块(chunking)读取，以便处理长文档。" 
            
            "返回值包含元信息：start_page、pages_read、total_pages、is_last_chunk、chars_returned 与 text。"
            "示例参数：{'file_path':'path/to.pdf','start_page':0,'pages_read':30,'max_chars':12000}。"
            "注意：max_chars 可为 null 表示不限制。"
            "在读取年度报告、半年报、审计报告等长文本时，建议先调用 read_pdf_text(file_path, start_page=0, pages_read=30, max_chars=12000) 读取第一块；"
            "若返回字段 is_last_chunk=false，则以 start_page += pages_read 继续读取下一块，直到 is_last_chunk=true。"
        ),
        "parameters": {
            "type": "object",
                "properties": {
                "file_path": {"type": "string", "description": "本地PDF路径"},
                "start_page": {"type": "integer", "description": "起始页 (0-based)，默认0"},
                "pages_read": {"type": "integer", "description": "本次读取页数；默认读取到文档末尾"},
                "max_chars": {"type": ["integer", "null"], "description": "返回文本的最大字符数，默认 null 表示不限制"},
            },
            "required": ["file_path"],
        },
    },
}
