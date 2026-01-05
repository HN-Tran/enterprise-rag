#!/usr/bin/env python3
"""RQ worker script for background task processing.

Usage:
    python scripts/worker.py                    # Process all queues
    python scripts/worker.py default            # Process only default queue
    python scripts/worker.py embeddings         # Process only embeddings queue
    python scripts/worker.py default embeddings # Process specific queues

Or use rq directly:
    rq worker default embeddings --url redis://localhost:6379/0
"""

from __future__ import annotations

import sys

from redis import Redis
from rq import Worker

from enterprise_rag.config import settings
from enterprise_rag.log import setup_logging, get_logger

# Set up logging before anything else
setup_logging()
logger = get_logger(__name__)


def main() -> None:
    if not settings.REDIS_URL:
        logger.error("worker_error", message="REDIS_URL not configured")
        sys.exit(1)

    # Parse queue names from command line
    queues = sys.argv[1:] if len(sys.argv) > 1 else ["default", "embeddings"]

    logger.info("worker_starting", queues=queues, redis_url=settings.REDIS_URL)

    # Connect to Redis
    redis_conn = Redis.from_url(settings.REDIS_URL)

    # Start worker
    worker = Worker(queues, connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
