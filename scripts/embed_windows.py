from __future__ import annotations

import argparse
from typing import Any

from tqdm import tqdm

from app.db import get_conn
from app.llm import embed_texts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=64)
    args = ap.parse_args()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT window_id, text
                FROM windows
                WHERE embedding IS NULL
                ORDER BY window_id ASC
                """
            )
            rows = cur.fetchall()

    if not rows:
        print("No windows missing embeddings.")
        return

    batch_size = max(1, args.batch_size)
    total = 0
    for i in tqdm(range(0, len(rows), batch_size), desc="Embedding windows", unit="batch"):
        batch = rows[i : i + batch_size]
        ids = [int(r["window_id"]) for r in batch]
        texts = [r["text"] for r in batch]
        vecs = embed_texts(texts)

        with get_conn() as conn:
            with conn.cursor() as cur:
                for wid, v in zip(ids, vecs):
                    cur.execute(
                        "UPDATE windows SET embedding = %s WHERE window_id = %s",
                        (v, wid),
                    )
            conn.commit()
        total += len(batch)

    print(f"Embedded {total} windows.")


if __name__ == "__main__":
    main()
