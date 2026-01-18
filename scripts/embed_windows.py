from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from tqdm import tqdm

from enterprise_rag.config import EMBEDDING_PROFILES, get_embedding_profile
from enterprise_rag.db import get_conn
from enterprise_rag.llm import embed_texts


def process_batch(batch: list[dict], col: str) -> int:
    """Embed a batch and write to DB. Returns count of processed rows."""
    ids = [int(r["window_id"]) for r in batch]
    texts = [r["text"] for r in batch]
    vecs = embed_texts(texts)

    with get_conn() as conn:
        with conn.cursor() as cur:
            params = [([float(x) for x in v], wid) for wid, v in zip(ids, vecs)]
            cur.executemany(
                f"UPDATE windows SET {col} = %s WHERE window_id = %s",
                params,
            )
        conn.commit()
    return len(batch)


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill embeddings for windows")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument(
        "--model",
        choices=list(EMBEDDING_PROFILES.keys()),
        help="Embedding model to use (default: from EMBEDDING_PROFILE env var)",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Re-embed all windows (not just missing)",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    args = ap.parse_args()

    # Get embedding profile (from --model arg or env var)
    if args.model:
        # Override the environment variable so embed_texts uses the correct model
        os.environ["EMBEDDING_PROFILE"] = args.model
        # Reload settings to pick up the change
        from enterprise_rag.config import Settings
        import enterprise_rag.config as config_module
        config_module.settings = Settings()
        profile = EMBEDDING_PROFILES[args.model]
    else:
        profile = get_embedding_profile()

    col = profile.db_column
    print(f"Using embedding model: {profile.model} ({profile.dim} dims)")
    print(f"Target column: {col}")

    # Find windows to embed
    with get_conn() as conn:
        with conn.cursor() as cur:
            if args.all:
                cur.execute("SELECT window_id, text FROM windows ORDER BY window_id ASC")
            else:
                cur.execute(
                    f"""
                    SELECT window_id, text
                    FROM windows
                    WHERE {col} IS NULL
                    ORDER BY window_id ASC
                    """
                )
            rows = cur.fetchall()

    if not rows:
        print(f"No windows missing embeddings in column '{col}'.")
        return

    print(f"Found {len(rows)} windows to embed.")

    batch_size = max(1, args.batch_size)
    batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]

    print(f"Processing {len(batches)} batches with {args.workers} workers...")

    total = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_batch, batch, col): batch for batch in batches}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Embedding", unit="batch"):
            total += future.result()

    print(f"Embedded {total} windows into column '{col}'.")


if __name__ == "__main__":
    main()
