"""Background embedding tasks."""

from __future__ import annotations

from typing import Any

from enterprise_rag.log import get_logger
from enterprise_rag.tasks import get_embedding_queue

logger = get_logger(__name__)


def enqueue_embed_batch(window_ids: list[int]) -> dict[str, Any]:
    """Queue a batch of windows for embedding.

    Returns:
        {"status": "queued", "job_id": "..."} if queued successfully
        {"status": "error", ...} if queuing failed
    """
    queue = get_embedding_queue()

    if queue is None:
        return {"status": "error", "message": "Embedding queue not available"}

    job = queue.enqueue(
        embed_batch_task,
        window_ids,
        job_timeout="10m",
        result_ttl=3600,  # Keep result for 1h
    )

    logger.info("embed_batch_queued", window_count=len(window_ids), job_id=job.id)
    return {"status": "queued", "job_id": job.id}


def embed_batch_task(window_ids: list[int]) -> dict[str, Any]:
    """Background task: embed a batch of windows.

    This runs in a worker process.
    """
    import numpy as np

    from enterprise_rag.db import get_conn, init_pool, close_pool
    from enterprise_rag.llm import embed_texts
    from enterprise_rag.log import setup_logging

    # Set up logging and DB pool for worker
    setup_logging()
    init_pool()

    try:
        logger.info("embed_batch_started", window_count=len(window_ids))

        # Fetch window texts
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT window_id, text
                    FROM windows
                    WHERE window_id = ANY(%s) AND embedding IS NULL
                    """,
                    (window_ids,),
                )
                rows = cur.fetchall()

        if not rows:
            logger.info("embed_batch_skipped", reason="no windows need embedding")
            return {"embedded": 0, "skipped": len(window_ids)}

        # Compute embeddings
        texts = [row["text"] for row in rows]
        embeddings = embed_texts(texts)

        # Binary quantize for storage
        def quantize(vec: list[float]) -> bytes:
            arr = np.array(vec, dtype=np.float32)
            return np.packbits((arr > 0).astype(np.uint8)).tobytes()

        # Update database
        with get_conn() as conn:
            with conn.cursor() as cur:
                for row, emb in zip(rows, embeddings):
                    bq = quantize(emb)
                    cur.execute(
                        """
                        UPDATE windows
                        SET embedding = %s, embedding_bq = %s
                        WHERE window_id = %s
                        """,
                        (emb, bq, row["window_id"]),
                    )
            conn.commit()

        logger.info("embed_batch_completed", embedded=len(rows))
        return {"embedded": len(rows), "skipped": len(window_ids) - len(rows)}

    except Exception as e:
        logger.error("embed_batch_failed", error=str(e))
        raise
    finally:
        close_pool()


def enqueue_all_pending_embeddings(batch_size: int = 64) -> list[dict[str, Any]]:
    """Queue all windows that need embeddings.

    Returns list of job info dicts.
    """
    from enterprise_rag.db import get_conn

    # Find windows without embeddings
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT window_id FROM windows
                WHERE embedding IS NULL
                ORDER BY window_id
                """
            )
            rows = cur.fetchall()

    if not rows:
        logger.info("no_pending_embeddings")
        return []

    # Queue in batches
    window_ids = [row["window_id"] for row in rows]
    jobs = []

    for i in range(0, len(window_ids), batch_size):
        batch = window_ids[i : i + batch_size]
        result = enqueue_embed_batch(batch)
        jobs.append(result)

    logger.info(
        "pending_embeddings_queued",
        total_windows=len(window_ids),
        batches=len(jobs),
    )
    return jobs
