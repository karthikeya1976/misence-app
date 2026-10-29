"""CloudWatch custom metrics. Disabled unless CLOUDWATCH_NAMESPACE is set (local dev, CI).

Metrics must never break moderation: every failure here is logged and swallowed.
EC2 needs cloudwatch:PutMetricData (granted in infra/cloudformation.yml).
"""

from __future__ import annotations

import logging

import boto3
import redis

from app import config

log = logging.getLogger(__name__)
_client = None


def _put(name: str, value: float, unit: str, dimensions: dict | None = None) -> None:
    global _client
    if not config.CLOUDWATCH_NAMESPACE:
        return
    try:
        if _client is None:
            _client = boto3.client("cloudwatch", region_name=config.AWS_S3_REGION)
        datum = {"MetricName": name, "Value": value, "Unit": unit}
        if dimensions:
            datum["Dimensions"] = [{"Name": k, "Value": v} for k, v in dimensions.items()]
        _client.put_metric_data(Namespace=config.CLOUDWATCH_NAMESPACE, MetricData=[datum])
    except Exception:
        log.warning("CloudWatch put_metric_data failed for %s", name, exc_info=True)


def record_verdict_latency(seconds: float, overall_status: str) -> None:
    """Job creation -> verdict, i.e. what the uploader actually waits for."""
    _put("VerdictLatencySeconds", seconds, "Seconds", {"Verdict": overall_status})


def record_queue_depth(depth: int) -> None:
    _put("QueueDepth", depth, "Count")


def record_dead_letter_depth(depth: int) -> None:
    _put("DeadLetterDepth", depth, "Count")


def publish_queue_depth() -> None:
    """Jobs waiting in the default Celery queue (a Redis list named after the queue).

    Called by the API on every enqueue as well as by the worker: a dead worker publishes
    nothing, so the API is the only reliable source of a backlog signal.
    """
    if not config.CLOUDWATCH_NAMESPACE:
        return
    try:
        depth = int(redis.Redis.from_url(config.REDIS_URL).llen("celery"))
    except Exception:
        log.warning("could not read queue depth from Redis", exc_info=True)
        return
    record_queue_depth(depth)
