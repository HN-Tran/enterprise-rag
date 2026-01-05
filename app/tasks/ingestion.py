"""Background ingestion tasks."""

from __future__ import annotations

from typing import Any

from app.log import get_logger
from app.tasks import get_default_queue, is_queue_available

logger = get_logger(__name__)


def enqueue_ingest(file_path: str) -> dict[str, Any]:
    """Queue a file for ingestion.

    Returns:
        {"status": "queued", "job_id": "..."} if queued successfully
        {"status": "sync", ...} if queuing not available (falls back to sync)
    """
    queue = get_default_queue()

    if queue is None:
        # Fall back to synchronous ingestion
        logger.info("ingest_sync_fallback", path=file_path)
        from app.ingestion.ingest import ingest_path

        return {"status": "sync", **ingest_path(file_path)}

    job = queue.enqueue(
        ingest_file_task,
        file_path,
        job_timeout="30m",  # Large files can take a while
        result_ttl=86400,  # Keep result for 24h
    )

    logger.info("ingest_queued", path=file_path, job_id=job.id)
    return {"status": "queued", "job_id": job.id}


def ingest_file_task(file_path: str) -> dict[str, Any]:
    """Background task: ingest a file.

    This runs in a worker process.
    """
    from app.db import init_pool, close_pool
    from app.ingestion.ingest import ingest_path
    from app.log import setup_logging

    # Set up logging and DB pool for worker
    setup_logging()
    init_pool()

    try:
        logger.info("ingest_started", path=file_path)
        result = ingest_path(file_path)
        logger.info(
            "ingest_completed",
            path=file_path,
            doc_id=result.get("doc_id"),
            pages=result.get("pages"),
            windows=result.get("windows"),
        )
        return result
    except Exception as e:
        logger.error("ingest_failed", path=file_path, error=str(e))
        raise
    finally:
        close_pool()


def get_job_status(job_id: str) -> dict[str, Any]:
    """Get the status of an ingestion job."""
    from app.tasks import get_redis_connection

    redis_conn = get_redis_connection()
    if redis_conn is None:
        return {"status": "error", "message": "Queue not available"}

    try:
        from rq.job import Job

        job = Job.fetch(job_id, connection=redis_conn)
        return {
            "job_id": job_id,
            "status": job.get_status(),
            "result": job.result if job.is_finished else None,
            "error": str(job.exc_info) if job.is_failed else None,
            "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
