"""Background task queue using RQ (Redis Queue)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings
from app.log import get_logger

if TYPE_CHECKING:
    from redis import Redis
    from rq import Queue

logger = get_logger(__name__)

# Global queue instances
_redis_conn: "Redis | None" = None
_default_queue: "Queue | None" = None
_embedding_queue: "Queue | None" = None


def init_queues() -> None:
    """Initialize RQ queues. Call once at startup."""
    global _redis_conn, _default_queue, _embedding_queue

    if not settings.REDIS_URL:
        logger.info("task_queues_disabled", reason="REDIS_URL not configured")
        return

    try:
        from redis import Redis
        from rq import Queue

        _redis_conn = Redis.from_url(settings.REDIS_URL)
        _default_queue = Queue("default", connection=_redis_conn)
        _embedding_queue = Queue("embeddings", connection=_redis_conn)

        logger.info(
            "task_queues_initialized",
            queues=["default", "embeddings"],
        )
    except ImportError as e:
        logger.warning("rq_import_error", error=str(e))
    except Exception as e:
        logger.error("queue_init_error", error=str(e))


def get_default_queue() -> "Queue | None":
    """Get the default task queue."""
    return _default_queue


def get_embedding_queue() -> "Queue | None":
    """Get the embedding-specific queue."""
    return _embedding_queue


def get_redis_connection() -> "Redis | None":
    """Get the Redis connection for RQ."""
    return _redis_conn


def is_queue_available() -> bool:
    """Check if task queues are available."""
    return _default_queue is not None
