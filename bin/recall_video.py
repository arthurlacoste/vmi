#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

import yaml


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def resolve(base: Path, value: str) -> Path:
    p = Path(os.path.expanduser(value))
    return p if p.is_absolute() else base / p


def json_dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_selectors(selector: str) -> list[str]:
    values = [selector]
    path = Path(selector).expanduser()
    values.append(path.name)
    if path.exists():
        resolved = str(path.resolve())
        values.extend([resolved, f"file:{resolved}"])
    return list(dict.fromkeys(v for v in values if v))


def recall(con: sqlite3.Connection, selector: str) -> dict | None:
    selectors = build_selectors(selector)

    for value in selectors:
        row = con.execute(
            """
            SELECT source_id, source_kind, original_filename, exported_path, sha256,
                   duration_seconds, status, transcript_json, transcript_txt,
                   transcript_srt, error, created_at, updated_at
            FROM assets
            WHERE source_id=? OR exported_path=? OR original_filename=? OR sha256=?
            LIMIT 1
            """,
            (value, value, value, value),
        ).fetchone()
        if row:
            return {
                "source_id": row[0],
                "source_kind": row[1],
                "filename": row[2],
                "source_path": row[3],
                "sha256": row[4],
                "duration_seconds": row[5],
                "status": row[6],
                "transcript_json": row[7],
                "transcript_txt": row[8],
                "transcript_srt": row[9],
                "error": row[10],
                "created_at": row[11],
                "updated_at": row[12],
            }

    for value in selectors:
        row = con.execute(
            """
            SELECT v.source_id, v.source_kind, v.filename, v.source_path, v.sha256,
                   v.duration_seconds, v.status, v.transcript_json, v.transcript_txt,
                   v.transcript_srt, v.created_at, v.transcribed_at
            FROM videos v
            WHERE v.source_id=? OR v.source_path=? OR v.filename=? OR v.sha256=?
            LIMIT 1
            """,
            (value, value, value, value),
        ).fetchone()
        if row:
            return {
                "source_id": row[0],
                "source_kind": row[1],
                "filename": row[2],
                "source_path": row[3],
                "sha256": row[4],
                "duration_seconds": row[5],
                "status": row[6],
                "transcript_json": row[7],
                "transcript_txt": row[8],
                "transcript_srt": row[9],
                "created_at": row[10],
                "transcribed_at": row[11],
            }

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Recall an already scanned VMI video without a full search")
    parser.add_argument("selector", help="source_id, file path, filename, or sha256")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    cfg = load_config(Path(args.config).resolve())
    base = Path(cfg["paths"]["project_dir"]).expanduser()
    db = resolve(base, cfg["paths"]["state_db"])
    con = sqlite3.connect(db)

    result = recall(con, args.selector)
    if not result:
        raise SystemExit(f"Video not found: {args.selector}")

    print(json_dumps(result))


if __name__ == "__main__":
    main()
