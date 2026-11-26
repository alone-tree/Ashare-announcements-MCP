# -*- coding: utf-8 -*-
"""修正 verified-formulas.jsonl 中已有记录（按 name 定位，可改任意字段）。

用法：
  python update_verified.py --dry-run patch.json
  python update_verified.py patch.json

patch.json 格式：
  {"updates": [
    {"match": {"name": "开盘价"}, "set": {"verification": "verified_with_caveat",
      "notes": "原式来自Xmind，示例值待实测"}, "reason": "修正虚高状态"}
  ]}

只改命中的记录，未命中即报错停止。每次修正追加修正历史到 correction-log.jsonl。
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE / "verified-formulas.jsonl"
LOG = HERE / "correction-log.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("patch")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    patch = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in TARGET.read_text(encoding="utf-8").splitlines() if l.strip()]
    changes = []
    for upd in patch.get("updates", []):
        match = upd["match"]
        hits = [i for i, r in enumerate(rows) if all(r.get(k) == v for k, v in match.items())]
        if len(hits) != 1:
            raise SystemExit(f"修正目标不唯一：{match} 命中 {len(hits)} 条")
        i = hits[0]
        before = {k: rows[i].get(k) for k in upd["set"]}
        if upd.get("append_notes"):
            old = rows[i].get("notes") or ""
            rows[i]["notes"] = (old + "；" if old else "") + upd["append_notes"]
        rows[i].update(upd["set"])
        changes.append({"match": match, "before": before, "after": upd["set"],
                        "reason": upd.get("reason", "")})

    if args.dry_run:
        for c in changes:
            print(json.dumps(c, ensure_ascii=False))
        print(f"dry-run: {len(changes)} 条待修正")
        return

    NL = chr(10)
    TARGET.write_text(NL.join(json.dumps(r, ensure_ascii=False) for r in rows) + NL,
                      encoding="utf-8")
    with LOG.open("a", encoding="utf-8") as f:
        for c in changes:
            f.write(json.dumps({**c, "at": date.today().isoformat()},
                               ensure_ascii=False) + NL)
    print(f"已修正 {len(changes)} 条，记录写入 {LOG}")


if __name__ == "__main__":
    main()
