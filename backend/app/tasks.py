from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import celery
from celery import Celery

from app import config, db, dead_letter, metrics, storage
from app.decision_engine import aggregate
from app.pillars import adult_content, ai_deepfake, duplicate_content, filmmaking_relevance
from app.pillars.common import PillarError

celery_app = Celery(
    "video_moderation",
    broker=config.REDIS_URL,
    backend=config.REDIS_URL,
)

# A worker once sat connected-but-dead for weeks after a Redis "connection reset by peer"
# (ElastiCache drops idle connections): keepalive + periodic PINGs make the dead socket surface
# so kombu reconnects, and retries on timeout instead of hanging.
celery_app.conf.broker_transport_options = {
    "socket_keepalive": True,
    "health_check_interval": 30,
    "retry_on_timeout": True,
}
celery_app.conf.broker_connection_retry_on_startup = True

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2   # 2s, 4s, 8s (+ jitter), capped at RETRY_BACKOFF_MAX
RETRY_BACKOFF_MAX = 60


async def _run_pillars(job_id: str) -> list[dict]:
    results = await asyncio.gather(
        adult_content.check(job_id),
        ai_deepfake.check(job_id),
        duplicate_content.check(job_id),
        filmmaking_relevance.check(job_id),
        return_exceptions=True,
    )
    failures = [r for r in results if isinstance(r, BaseException)]
    if failures:
        # Any single pillar failing means we cannot issue a trustworthy verdict.
        raise PillarError("; ".join(str(f) for f in failures))
    return results


def _seconds_since(created_at) -> float | None:
    if not isinstance(created_at, datetime):
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created_at).total_seconds()


class ModerationTask(celery.Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Retries exhausted (or a non-retryable bug). Fail closed: never approve, never publish.

        overall_status 'needs_review' is outside the ('approved', 'flagged') filter every feed and
        search query uses, so the video stays hidden until a human decides. The job id also goes
        to the dead-letter list for inspection / replay (scripts/replay_dlq.py).
        """
        job_id = args[0]
        error = f"{type(exc).__name__}: {exc}"
        db.update_job(job_id, {
            "status": "failed",
            "overall_status": "needs_review",
            "reasons": [f"moderation failed after {MAX_RETRIES} retries — held for human review ({error})"],
        })
        dead_letter.push(job_id, error)
        metrics.record_dead_letter_depth(dead_letter.depth())


@celery_app.task(
    name="process_video",
    base=ModerationTask,
    autoretry_for=(PillarError,),
    retry_backoff=RETRY_BACKOFF_SECONDS,
    retry_backoff_max=RETRY_BACKOFF_MAX,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
def process_video(job_id: str) -> None:
    job = db.get_job(job_id)
    if job is None:
        return

    metrics.publish_queue_depth()
    db.update_job(job_id, {"status": "processing"})

    object_name = f"{job_id}.mp4"

    # File is already on local disk — no download needed
    file_path = storage.get_video_path(object_name)
    size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0

    # The four pillars run concurrently (each one's blocking I/O is off the event loop)
    pillar_results = asyncio.run(_run_pillars(job_id))

    # Decision Engine: compile pillar scores → overall verdict
    verdict = aggregate(pillar_results)

    db.update_job(
        job_id,
        {
            "status": "done",
            "size_bytes": size_bytes,
            "overall_status": verdict["overall_status"],
            "reasons": verdict["reasons"],
            "pillar_results": pillar_results,
        },
    )

    latency = _seconds_since(job.get("created_at"))
    if latency is not None:
        metrics.record_verdict_latency(latency, verdict["overall_status"])

    # Note: S3 object is kept so the feed can stream the video via presigned URLs.
    # cleanup_video() would delete it — only call that if storage cost becomes a concern.
