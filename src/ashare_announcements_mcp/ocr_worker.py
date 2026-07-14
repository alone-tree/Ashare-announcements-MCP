"""RapidOCR 独立工作进程，只通过 stdout 返回一行 JSON。"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any

import pymupdf


def _format_result(result: Any) -> str:
    if not result or not result.txts:
        return ""
    entries = []
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        if not text or score < 0.5:
            continue
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        entries.append(
            {
                "text": text.strip(),
                "x": min(xs),
                "y": sum(ys) / len(ys),
                "height": max(ys) - min(ys),
            }
        )
    entries.sort(key=lambda item: (item["y"], item["x"]))

    rows: list[list[dict[str, Any]]] = []
    for entry in entries:
        if not rows:
            rows.append([entry])
            continue
        row_y = sum(item["y"] for item in rows[-1]) / len(rows[-1])
        tolerance = max(10.0, entry["height"] * 0.65)
        if abs(entry["y"] - row_y) <= tolerance:
            rows[-1].append(entry)
        else:
            rows.append([entry])

    lines = []
    for row in rows:
        row.sort(key=lambda item: item["x"])
        texts = [item["text"] for item in row if item["text"]]
        if texts:
            lines.append(" | ".join(texts) if len(texts) > 1 else texts[0])
    return "\n".join(lines)


def main() -> None:
    try:
        pdf_path = Path(sys.argv[1])
        page_numbers = [int(value) for value in sys.argv[2].split(",") if value]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from rapidocr import RapidOCR

            engine = RapidOCR()
            with pymupdf.open(pdf_path) as document:
                pages = {}
                for page_number in page_numbers:
                    pixmap = document[page_number - 1].get_pixmap(
                        matrix=pymupdf.Matrix(2, 2),
                        alpha=False,
                    )
                    pages[str(page_number)] = _format_result(engine(pixmap.tobytes("png")))
        print(json.dumps({"ok": True, "pages": pages}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
