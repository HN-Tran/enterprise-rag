"""Migrate feedback from JSONL file to PostgreSQL."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from enterprise_rag.db import get_conn


def parse_timestamp(ts: str) -> datetime:
    """Parse ISO timestamp, handling various formats."""
    # Handle with or without microseconds
    for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    # Fallback: let Python try to parse it
    return datetime.fromisoformat(ts)


def migrate(jsonl_path: Path, dry_run: bool = False) -> None:
    """Migrate feedback entries from JSONL to database."""
    if not jsonl_path.exists():
        print(f"File not found: {jsonl_path}")
        return

    entries = []
    errors = []

    with open(jsonl_path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries.append(entry)
            except json.JSONDecodeError as e:
                errors.append((line_no, str(e)))

    if errors:
        print(f"Found {len(errors)} parse errors:")
        for line_no, err in errors[:5]:
            print(f"  Line {line_no}: {err}")
        if len(errors) > 5:
            print(f"  ... and {len(errors) - 5} more")

    print(f"Found {len(entries)} feedback entries to migrate")

    if dry_run:
        print("Dry run - no changes made")
        return

    if not entries:
        return

    migrated = 0
    skipped = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            for entry in entries:
                try:
                    # Parse timestamp if present
                    created_at = None
                    if "timestamp" in entry:
                        created_at = parse_timestamp(entry["timestamp"])

                    cur.execute(
                        """
                        INSERT INTO feedback (
                            created_at, query, answer, rating, comment,
                            category, embedding_model, sources, history, settings
                        )
                        VALUES (
                            COALESCE(%(created_at)s, now()),
                            %(query)s, %(answer)s, %(rating)s, %(comment)s,
                            %(category)s, %(embedding_model)s,
                            %(sources)s::jsonb, %(history)s::jsonb, %(settings)s::jsonb
                        )
                        """,
                        {
                            "created_at": created_at,
                            "query": entry.get("query", ""),
                            "answer": entry.get("answer", ""),
                            "rating": entry.get("feedback", "unknown"),
                            "comment": entry.get("comment"),
                            "category": entry.get("category"),
                            "embedding_model": entry.get("embedding_model"),
                            "sources": json.dumps(entry["sources"]) if entry.get("sources") else None,
                            "history": json.dumps(entry["history"]) if entry.get("history") else None,
                            "settings": json.dumps(entry["settings"]) if entry.get("settings") else None,
                        },
                    )
                    migrated += 1
                except Exception as e:
                    print(f"Error migrating entry: {e}")
                    skipped += 1

        conn.commit()

    print(f"Migrated {migrated} entries, skipped {skipped}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Migrate feedback from JSONL to PostgreSQL")
    ap.add_argument(
        "--file",
        type=Path,
        default=Path("feedback.jsonl"),
        help="Path to feedback.jsonl file (default: feedback.jsonl)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without making changes",
    )
    args = ap.parse_args()

    migrate(args.file, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
