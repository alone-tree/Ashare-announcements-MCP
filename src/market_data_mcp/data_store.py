"""市场数据独立批次的原子存储；读取与覆盖检查不联网、不建目录。"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


def path(root: str, code: str, domain: str, module: str) -> Path:
    return Path(root) / "cache" / code / domain / f"{module}.json"


def read(root: str, code: str, domain: str, module: str, source: str | None = None) -> dict | None:
    target = path(root, code, domain, module)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("meta", {}).get("schema_version") != 2:
            return None
        if source and payload.get("meta", {}).get("source") != source:
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None


def write(root: str, code: str, domain: str, module: str, payload: dict) -> None:
    target = path(root, code, domain, module)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        # 依据 docs/行为-财报工具.md §3，仅对已复现的Windows替换占用有限重试。
        retry_delays = (0.05, 0.10, 0.20)
        for attempt in range(len(retry_delays) + 1):
            try:
                os.replace(temporary, target)
                break
            except OSError as exc:
                if getattr(exc, "winerror", None) != 5 or attempt == len(retry_delays):
                    raise
                time.sleep(retry_delays[attempt])
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fresh(checked_at: str | None, days: int = 30) -> bool:
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(checked_at)
        return 0 <= age.total_seconds() < days * 86400
    except (ValueError, TypeError):
        return False
