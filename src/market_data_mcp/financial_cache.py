# -*- coding: utf-8 -*-
"""财报缓存：四文件路径、版本合并和同批次提交。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


FINANCIAL_FILES = {
    "metadata": "metadata.json",
    "balance": "balance.json",
    "income": "income.json",
    "cash_flow": "cash_flow.json",
}
FRESH_FOR = timedelta(days=30)


def financial_dir(root: str, code: str) -> Path:
    return Path(root) / "cache" / code / "financial_statements"


def financial_path(root: str, code: str, name: str) -> Path:
    if name not in FINANCIAL_FILES:
        raise ValueError(f"未知财报缓存文件：{name}")
    return financial_dir(root, code) / FINANCIAL_FILES[name]


def read_bundle(root: str, code: str) -> dict[str, dict[str, Any]] | None:
    """读取四个缓存文件；缺失、损坏或批次不一致都视为无可用完整缓存。"""
    bundle: dict[str, dict[str, Any]] = {}
    try:
        for name in FINANCIAL_FILES:
            with financial_path(root, code, name).open(encoding="utf-8") as f:
                bundle[name] = json.load(f)
    except (OSError, ValueError, TypeError):
        return None
    batch_ids = {payload.get("meta", {}).get("update_batch_id") for payload in bundle.values()}
    if None in batch_ids or len(batch_ids) != 1:
        return None
    return bundle


def commit_bundle(
    root: str,
    code: str,
    metadata: dict[str, Any],
    statements: dict[str, dict[str, Any]],
) -> None:
    """四文件先全部写临时文件，再替换正式文件；进程内失败时回滚旧文件。"""
    payloads = {"metadata": metadata, **statements}
    if set(payloads) != set(FINANCIAL_FILES):
        raise ValueError("财报批次必须同时包含 metadata/balance/income/cash_flow")
    batch_ids = {payload.get("meta", {}).get("update_batch_id") for payload in payloads.values()}
    if None in batch_ids or len(batch_ids) != 1:
        raise ValueError("财报四文件 update_batch_id 必须一致")

    directory = financial_dir(root, code)
    directory.mkdir(parents=True, exist_ok=True)
    temporary: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    replaced: list[str] = []
    try:
        for name, payload in payloads.items():
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=f".{name}.tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, allow_nan=False)
            temporary[name] = Path(tmp)
        for name in FINANCIAL_FILES:
            target = financial_path(root, code, name)
            backup = target.with_suffix(target.suffix + ".bak")
            if target.exists():
                os.replace(target, backup)
                backups[name] = backup
            os.replace(temporary[name], target)
            replaced.append(name)
    except BaseException:
        for name in replaced:
            target = financial_path(root, code, name)
            if target.exists():
                target.unlink()
        for name, backup in backups.items():
            os.replace(backup, financial_path(root, code, name))
        raise
    finally:
        for tmp in temporary.values():
            if tmp.exists():
                tmp.unlink()
        for backup in backups.values():
            if backup.exists():
                backup.unlink()


def is_fresh(metadata: dict[str, Any], now: datetime | None = None) -> bool:
    text = metadata.get("meta", {}).get("last_successful_update")
    if not text:
        return False
    try:
        updated = datetime.fromisoformat(str(text))
    except ValueError:
        return False
    return (now or datetime.now()) - updated < FRESH_FOR


def _version_id(report: dict[str, Any]) -> str:
    semantic = {
        "report_date": report["report_date"],
        "metadata": report.get("metadata") or {},
        "items": sorted(
            report.get("items") or [],
            key=lambda item: (str(item.get("item_code") or ""), str(item.get("item_name") or "")),
        ),
    }
    raw = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _change_summary(previous: dict[str, Any] | None, fresh: dict[str, Any]) -> dict[str, Any] | None:
    if previous is None:
        return None
    old_items = {
        (str(item.get("item_code") or ""), str(item.get("item_name") or "")): item
        for item in previous.get("items") or []
    }
    new_items = {
        (str(item.get("item_code") or ""), str(item.get("item_name") or "")): item
        for item in fresh.get("items") or []
    }
    old_keys = set(old_items)
    new_keys = set(new_items)
    changed_keys = sorted(key for key in old_keys & new_keys if old_items[key] != new_items[key])
    old_metadata = previous.get("metadata") or {}
    new_metadata = fresh.get("metadata") or {}
    metadata_keys = sorted(
        key for key in set(old_metadata) | set(new_metadata) if old_metadata.get(key) != new_metadata.get(key)
    )
    return {
        "added_item_codes": sorted({code for code, _ in new_keys - old_keys}),
        "removed_item_codes": sorted({code for code, _ in old_keys - new_keys}),
        "changed_item_codes": sorted({code for code, _ in changed_keys}),
        "changed_metadata_keys": metadata_keys,
    }


def merge_statement(
    existing: dict[str, Any] | None,
    fresh_reports: list[dict[str, Any]],
    *,
    code: str,
    market: str,
    statement: str,
    source: str,
    observed_at: str,
    batch_id: str,
) -> dict[str, Any]:
    """把一次全历史刷新合并进单张报表缓存，同报告期内容变化时保留新旧版本。"""
    old_by_date = {report["report_date"]: report for report in (existing or {}).get("reports", [])}
    fresh_dates: set[str] = set()
    ordered_fresh = sorted(fresh_reports, key=lambda report: report["report_date"])

    catalog: dict[tuple[str, str], dict[str, str]] = {}
    for item in (existing or {}).get("item_catalog") or []:
        key = (str(item.get("item_code") or ""), str(item.get("item_name") or ""))
        catalog[key] = {"item_code": key[0], "item_name": key[1]}
    if not catalog:
        for report in old_by_date.values():
            for version in report.get("versions") or []:
                for item in version.get("items") or []:
                    key = (str(item.get("item_code") or ""), str(item.get("item_name") or ""))
                    catalog[key] = {"item_code": key[0], "item_name": key[1]}

    for fresh in ordered_fresh:
        report_date = fresh["report_date"]
        fresh_dates.add(report_date)
        for item in fresh.get("items") or []:
            key = (str(item.get("item_code") or ""), str(item.get("item_name") or ""))
            catalog[key] = {"item_code": key[0], "item_name": key[1]}
        entry = old_by_date.setdefault(
            report_date,
            {"report_date": report_date, "current_version_id": None, "present_in_latest_refresh": True, "versions": []},
        )
        version_id = _version_id(fresh)
        known = next((version for version in entry["versions"] if version["version_id"] == version_id), None)
        if known is None:
            previous = next(
                (
                    version
                    for version in entry["versions"]
                    if version.get("version_id") == entry.get("current_version_id")
                ),
                None,
            )
            known = {
                "version_id": version_id,
                "first_seen_at": observed_at,
                "last_seen_at": observed_at,
                "metadata": fresh.get("metadata") or {},
                "items": fresh.get("items") or [],
                "change_summary": _change_summary(previous, fresh),
            }
            entry["versions"].append(known)
        else:
            known["last_seen_at"] = observed_at
        entry["current_version_id"] = version_id
        entry["present_in_latest_refresh"] = True

    for report_date, entry in old_by_date.items():
        if report_date not in fresh_dates:
            entry["present_in_latest_refresh"] = False

    reports = sorted(old_by_date.values(), key=lambda report: report["report_date"])
    return {
        "meta": {
            "schema_version": 1,
            "code": code,
            "market": market,
            "statement": statement,
            "source": source,
            "last_successful_update": observed_at,
            "last_refresh_attempt": observed_at,
            "update_batch_id": batch_id,
            "date_range": {
                "start": ordered_fresh[0]["report_date"] if ordered_fresh else None,
                "end": ordered_fresh[-1]["report_date"] if ordered_fresh else None,
            },
            "shape": {"reports": len(ordered_fresh)},
        },
        "item_catalog": [catalog[key] for key in sorted(catalog)],
        "reports": reports,
    }
