"""面向 AI 的 PDF 结构检查、检索、表格提取和 OCR 阅读。"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pymupdf

from ashare_announcements_mcp.cache import extraction_dir


INDEX_VERSION = 4
OCR_BATCH_SIZE = 3
NATIVE_MARKDOWN_BATCH_SIZE = 8
_PYMUPDF4LLM: Any = None


def _index_path(stock_code: str, pdf_path: Path) -> Path:
    return extraction_dir(stock_code) / f"{pdf_path.stem}.json"


def _save_index(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _build_index(pdf_path: Path) -> dict[str, Any]:
    """快速扫描全部页面，只提取原生文本并识别需要 OCR 的页面。"""
    pages: list[dict[str, Any]] = []
    with pymupdf.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text", sort=True).strip()
            compact = re.sub(r"\s+", "", text)
            image_count = len(page.get_images(full=True))
            replacement_ratio = text.count("\ufffd") / max(len(text), 1)
            needs_ocr = (len(compact) < 40 and image_count > 0) or replacement_ratio > 0.1
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            pages.append(
                {
                    "page": page_number,
                    "native_text": text,
                    "native_chars": len(text),
                    "image_count": image_count,
                    "needs_ocr": needs_ocr,
                    "heading": " ".join(lines[:2])[:160],
                }
            )
        metadata = {key: value for key, value in document.metadata.items() if value}
        toc = [
            {"level": level, "title": title, "page": page}
            for level, title, page, *_ in document.get_toc(simple=False)
        ]
    stat = pdf_path.stat()
    return {
        "version": INDEX_VERSION,
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "metadata": metadata,
        "toc": toc,
        "pages": pages,
    }


def _load_index(stock_code: str, pdf_path: Path) -> tuple[Path, dict[str, Any]]:
    path = _index_path(stock_code, pdf_path)
    stat = pdf_path.stat()
    previous: dict[str, Any] | None = None
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (
                data.get("version") == INDEX_VERSION
                and data.get("source_size") == stat.st_size
                and data.get("source_mtime_ns") == stat.st_mtime_ns
            ):
                return path, data
            if (
                data.get("source_size") == stat.st_size
                and data.get("source_mtime_ns") == stat.st_mtime_ns
            ):
                previous = data
        except (OSError, json.JSONDecodeError):
            pass
    data = _build_index(pdf_path)
    if previous:
        for page, old_page in zip(
            data["pages"],
            previous.get("pages") or [],
        ):
            for key in ("ocr_text", "ocr_attempted"):
                if key in old_page:
                    page[key] = old_page[key]
    _save_index(path, data)
    return path, data


def _page_ranges(page_numbers: list[int]) -> str:
    if not page_numbers:
        return ""
    ranges: list[str] = []
    start = previous = page_numbers[0]
    for number in page_numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)


def _load_pymupdf4llm() -> Any:
    global _PYMUPDF4LLM
    if _PYMUPDF4LLM is None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import pymupdf4llm
            from pymupdf import layout as pymupdf_layout

            pymupdf_layout.activate()
        _PYMUPDF4LLM = pymupdf4llm
    return _PYMUPDF4LLM


def initialize_pdf_engine() -> None:
    """在 stdio 事件循环启动前初始化 Windows Layout 运行时。"""
    _load_pymupdf4llm()


def _native_markdown_pages(pdf_path: Path, page_numbers: list[int]) -> dict[int, str]:
    """批量转换指定页面，让 Layout 保留结构并控制长文档单次耗时。"""
    if not page_numbers:
        return {}
    converter = _load_pymupdf4llm()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        chunks = converter.to_markdown(
            str(pdf_path),
            pages=[page_number - 1 for page_number in page_numbers],
            page_chunks=True,
            header=False,
            footer=False,
            use_ocr=False,
            ignore_images=True,
            table_strategy="lines_strict",
            show_progress=False,
        )
    if not isinstance(chunks, list) or len(chunks) != len(page_numbers):
        raise RuntimeError("PyMuPDF4LLM 未返回完整的逐页 Markdown")
    result: dict[int, str] = {}
    for fallback_page, chunk in zip(page_numbers, chunks, strict=True):
        if not isinstance(chunk, dict):
            raise RuntimeError("PyMuPDF4LLM 返回了无效的页面结果")
        metadata = chunk.get("metadata") or {}
        page_number = int(metadata.get("page_number") or fallback_page)
        if page_number not in page_numbers or page_number in result:
            page_number = fallback_page
        result[page_number] = str(chunk.get("text") or "").strip()
    return result


def _cache_native_markdown(
    pdf_path: Path,
    index_path: Path,
    index: dict[str, Any],
    page_numbers: list[int],
) -> None:
    pending = [
        page_number
        for page_number in page_numbers
        if not index["pages"][page_number - 1]["needs_ocr"]
        and not index["pages"][page_number - 1].get("markdown_attempted")
    ]
    if not pending:
        return
    extracted = _native_markdown_pages(pdf_path, pending)
    for page_number in pending:
        page = index["pages"][page_number - 1]
        page["markdown"] = extracted.get(page_number, "")
        page["markdown_attempted"] = True
    _save_index(index_path, index)


def _ocr_pages(pdf_path: Path, page_numbers: list[int]) -> dict[int, str]:
    """在独立进程中批量 OCR，避免 ONNX Runtime 阻塞 MCP 服务进程。"""
    if not page_numbers:
        return {}
    worker = Path(__file__).with_name("ocr_worker.py")
    completed = subprocess.run(
        [sys.executable, str(worker), str(pdf_path), ",".join(map(str, page_numbers))],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"OCR 工作进程失败：{completed.stderr.strip() or completed.stdout.strip()}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OCR 工作进程返回了无效结果") from exc
    if not payload.get("ok"):
        raise RuntimeError(f"OCR 失败：{payload.get('error', '未知错误')}")
    return {int(page): text for page, text in payload.get("pages", {}).items()}


def _ocr_markdown(pdf_path: Path, page_number: int) -> str:
    return _ocr_pages(pdf_path, [page_number]).get(page_number, "")


def _ensure_page_text(
    pdf_path: Path,
    index_path: Path,
    index: dict[str, Any],
    page_number: int,
    *,
    rich: bool,
    ocr: bool,
) -> tuple[str, str, bool]:
    page = index["pages"][page_number - 1]
    changed = False
    if page["needs_ocr"]:
        if ocr and not page.get("ocr_attempted") and not page.get("ocr_text"):
            page["ocr_text"] = _ocr_markdown(pdf_path, page_number)
            page["ocr_attempted"] = True
            changed = True
        text = page.get("ocr_text") or page.get("native_text") or ""
        if page.get("ocr_text"):
            extraction = "ocr"
        elif page.get("ocr_attempted"):
            extraction = "ocr_empty"
        else:
            extraction = "native_incomplete"
    else:
        if rich and not page.get("markdown_attempted"):
            _cache_native_markdown(pdf_path, index_path, index, [page_number])
        text = page.get("markdown") or page.get("native_text") or ""
        extraction = "native_markdown" if page.get("markdown") else "native_text"
    if changed:
        _save_index(index_path, index)
    return text, extraction, "|---" in text


def _build_profile(index: dict[str, Any]) -> dict[str, Any]:
    """从逐页索引计算文档画像和推荐动作。"""
    pages = index["pages"]
    scanned = [page["page"] for page in pages if page["needs_ocr"]]
    total_pages = len(pages)
    if total_pages <= 10:
        profile = "short"
        workflow = "公告较短，已直接返回全文。"
    elif scanned:
        profile = "long_mixed_scan"
        workflow = (
            f"文档共 {total_pages} 页，含扫描页。有明确问题时，"
            "先用 search_announcement 定位关键词页，再精读命中页；"
            "没有明确问题，用 read 从第 4 页开始通读，next_page 续读。"
            "扫描页会在精读时自动 OCR。"
        )
    else:
        profile = "long_structured"
        workflow = (
            f"文档共 {total_pages} 页。有明确问题时，"
            "先用 search_announcement 定位关键词页，再精读命中页；"
            "没有明确问题，用 read 从第 4 页开始通读，next_page 续读。"
        )
    return {
        "profile": profile,
        "total_pages": total_pages,
        "native_text_chars": sum(page["native_chars"] for page in pages),
        "native_text_coverage": round((total_pages - len(scanned)) / max(total_pages, 1), 4),
        "scanned_pages": _page_ranges(scanned),
        "scanned_page_count": len(scanned),
        "recommended_workflow": workflow,
    }


def _query_terms(query: str) -> tuple[list[str], bool]:
    text = query.strip().lower()
    if not text:
        raise ValueError("query 不能为空")
    is_and = bool(re.search(r"\s+and\s+", text, flags=re.IGNORECASE))
    if is_and:
        terms = [part.strip() for part in re.split(r"\s+and\s+", text, flags=re.IGNORECASE)]
    else:
        terms = [part for part in text.split() if part]
    return [term for term in terms if term], is_and


def search_pdf(
    pdf_path: Path,
    stock_code: str,
    query: str,
    max_results: int = 20,
    ocr_scanned: bool = True,
) -> dict[str, Any]:
    index_path, index = _load_index(stock_code, pdf_path)
    terms, is_and = _query_terms(query)
    hits = []
    pending_ocr_pages = [
        page["page"]
        for page in index["pages"]
        if page["needs_ocr"]
        and ocr_scanned
        and not page.get("ocr_attempted")
        and not page.get("ocr_text")
    ]
    ocr_pages = pending_ocr_pages[:OCR_BATCH_SIZE]
    remaining_ocr_pages = pending_ocr_pages[OCR_BATCH_SIZE:]
    if ocr_pages:
        extracted = _ocr_pages(pdf_path, ocr_pages)
        for page_number in ocr_pages:
            text = extracted.get(page_number, "")
            index["pages"][page_number - 1]["ocr_text"] = text
            index["pages"][page_number - 1]["ocr_attempted"] = True
        _save_index(index_path, index)
    for page in index["pages"]:
        page_number = page["page"]
        text = page.get("ocr_text") or page.get("native_text") or ""
        lowered = text.lower()
        matched = all(term in lowered for term in terms) if is_and else any(
            term in lowered for term in terms
        )
        if not matched:
            continue
        score = sum(lowered.count(term) for term in terms)
        positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
        position = min(positions, default=0)
        start = max(0, position - 180)
        end = min(len(text), position + 360)
        hits.append(
            {
                "page": page_number,
                "score": score,
                "extraction": "ocr" if page.get("ocr_text") else "native_text",
                "snippet": re.sub(r"\s+", " ", text[start:end]).strip(),
            }
        )
    hits.sort(key=lambda item: (-item["score"], item["page"]))
    return {
        "query": query,
        "logic": "AND" if is_and else "OR",
        "matched_pages": len(hits),
        "search_complete": not remaining_ocr_pages,
        "ocr_pages_processed": _page_ranges(ocr_pages),
        "ocr_pending_pages": _page_ranges(remaining_ocr_pages),
        "recommended_next_action": (
            "再次使用相同参数调用 search_announcement，继续建立扫描页索引。"
            if remaining_ocr_pages
            else "根据命中页调用 read_announcement。"
        ),
        "results": hits[:max_results],
    }


def read_pdf(
    pdf_path: Path,
    stock_code: str,
    start_page: int | None = None,
    end_page: int | None = None,
    max_pages: int = 20,
    ocr: bool = True,
) -> dict[str, Any]:
    """阅读公告；start_page 缺省时自动检测并预览，带页码时精读指定页段。

    检测模式（start_page=None）：
      - short（≤10 页）：直接返回全文；
      - long：返回文档画像（profile/扫描页/覆盖率/推荐动作）+ 前 3 页正文预览。
    精读模式（start_page 指定）：从 start_page 起最多返回 max_pages 页，
    未读完时用 next_page 续读；不设页数上限，可传任意大的 max_pages。
    """
    index_path, index = _load_index(stock_code, pdf_path)
    profile = _build_profile(index)
    total_pages = profile["total_pages"]

    if max_pages < 1:
        raise ValueError("max_pages 必须大于等于 1")

    detect_mode = start_page is None
    if detect_mode:
        if profile["profile"] == "short":
            start_page, end_page = 1, total_pages
        else:
            start_page, end_page = 1, 3
    else:
        if start_page < 1 or start_page > total_pages:
            raise ValueError(f"start_page 必须在 1 到 {total_pages} 之间")
        target_end = total_pages if end_page is None else end_page
        if target_end < start_page or target_end > total_pages:
            raise ValueError(f"end_page 必须在 {start_page} 到 {total_pages} 之间")
        end_page = min(target_end, start_page + max_pages - 1)

    blocks: list[str] = []
    page_details = []
    next_page: int | None = None
    for page_number in range(start_page, end_page + 1):
        page = index["pages"][page_number - 1]
        if not page["needs_ocr"] and not page.get("markdown_attempted"):
            batch_end = min(
                end_page,
                page_number + NATIVE_MARKDOWN_BATCH_SIZE - 1,
            )
            batch_pages = [
                candidate
                for candidate in range(page_number, batch_end + 1)
                if not index["pages"][candidate - 1]["needs_ocr"]
                and not index["pages"][candidate - 1].get("markdown_attempted")
            ]
            _cache_native_markdown(
                pdf_path,
                index_path,
                index,
                batch_pages,
            )
        if (
            page["needs_ocr"]
            and ocr
            and not page.get("ocr_attempted")
            and not page.get("ocr_text")
        ):
            pending = []
            for candidate in range(
                page_number,
                min(end_page, page_number + OCR_BATCH_SIZE - 1) + 1,
            ):
                candidate_page = index["pages"][candidate - 1]
                if not candidate_page["needs_ocr"]:
                    break
                if not candidate_page.get("ocr_attempted") and not candidate_page.get(
                    "ocr_text"
                ):
                    pending.append(candidate)
            extracted = _ocr_pages(pdf_path, pending)
            for candidate in pending:
                text = extracted.get(candidate, "")
                index["pages"][candidate - 1]["ocr_text"] = text
                index["pages"][candidate - 1]["ocr_attempted"] = True
            _save_index(index_path, index)
        text, extraction, has_table = _ensure_page_text(
            pdf_path,
            index_path,
            index,
            page_number,
            rich=True,
            ocr=ocr,
        )
        block = f"## 第 {page_number} 页\n\n{text.strip()}".strip()
        blocks.append(block)
        page_details.append(
            {
                "page": page_number,
                "extraction": extraction,
                "chars": len(text),
                "table_detected": has_table,
            }
        )
    else:
        next_page = end_page + 1 if end_page < total_pages else None

    text = "\n\n".join(blocks)
    result = {
        "text": text,
        "total_pages": total_pages,
        "pages_returned": [item["page"] for item in page_details],
        "page_details": page_details,
        "chars_returned": len(text),
        "next_page": next_page,
        "is_last_chunk": next_page is None,
        "profile": profile["profile"],
        "native_text_coverage": profile["native_text_coverage"],
        "scanned_pages": profile["scanned_pages"],
    }
    if detect_mode:
        result.update(
            {
                "native_text_chars": profile["native_text_chars"],
                "scanned_page_count": profile["scanned_page_count"],
                "recommended_workflow": profile["recommended_workflow"],
            }
        )
    return result
