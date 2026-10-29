"""Dead-letter list for jobs whose moderation failed after all retries.

A Redis list (not Celery's broker queue) so entries survive for inspection and replay:
  redis-cli -u $REDIS_URL LRANGE dlq:process_video 0 -1
  python scripts/replay_dlq.py
"""

import json
from datetime import datetime, timezone

import redis

from app import config

KEY = "dlq:process_video"


def _client() -> "redis.Redis":
    return redis.Redis.from_url(config.REDIS_URL)


def push(job_id: str, error: str) -> None:
    entry = {"job_id": job_id, "error": error, "failed_at": datetime.now(timezone.utc).isoformat()}
    _client().lpush(KEY, json.dumps(entry))


def depth() -> int:
    return int(_client().llen(KEY))


def pop_all() -> list[dict]:
    """Atomically drain the list (oldest first) so a replay never double-processes an entry."""
    r = _client()
    entries = []
    while (raw := r.rpop(KEY)) is not None:
        entries.append(json.loads(raw))
    return entries
