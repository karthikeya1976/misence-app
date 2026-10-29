"""
Tests for the moderation pipeline's concurrency, retry / fail-closed behaviour,
dead-letter path, CloudWatch metrics and perceptual hashing.

No DB, Redis, S3 or network: db / dead_letter / metrics / pillars are monkeypatched.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
# config.py refuses to import without a Postgres URL; nothing here ever connects to it.
os.environ.setdefault("POSTGRES_URL", "postgresql://unused:unused@localhost:1/unused")

import pytest  # noqa: E402

from app import dead_letter, metrics, phash, tasks  # noqa: E402
from app.pillars import adult_content, ai_deepfake, duplicate_content, filmmaking_relevance  # noqa: E402
from app.pillars.common import PillarError  # noqa: E402

PILLARS = {
    "adult_content": adult_content,
    "ai_deepfake": ai_deepfake,
    "duplicate_content": duplicate_content,
    "filmmaking_relevance": filmmaking_relevance,
}


def _slow_pillar(name: str, delay: float):
    def fn(job_id: str) -> dict:
        time.sleep(delay)  # stands in for blocking S3 / OpenCV / HTTP work
        return {"pillar": name, "score": 0.0, "flags": []}
    return fn


# ── 1. Concurrency ───────────────────────────────────────────────────────────

def test_pillars_run_concurrently(monkeypatch):
    delay = 0.3
    for name, mod in PILLARS.items():
        monkeypatch.setattr(mod, "_check_blocking", _slow_pillar(name, delay))

    start = time.perf_counter()
    results = asyncio.run(tasks._run_pillars("job"))
    elapsed = time.perf_counter() - start

    assert [r["pillar"] for r in results] == list(PILLARS)
    # Sequential would be >= 4 * delay = 1.2s; concurrent is ~delay.
    assert elapsed < 2 * delay, f"pillars ran sequentially ({elapsed:.2f}s)"


def test_failing_pillar_raises_pillar_error(monkeypatch):
    for name, mod in PILLARS.items():
        monkeypatch.setattr(mod, "_check_blocking", _slow_pillar(name, 0))

    def boom(job_id):
        raise PillarError("duplicate_content: S3 timeout")
    monkeypatch.setattr(duplicate_content, "_check_blocking", boom)

    with pytest.raises(PillarError, match="S3 timeout"):
        asyncio.run(tasks._run_pillars("job"))


# ── 2. Retry config + fail-closed on exhaustion ──────────────────────────────

def test_task_retry_configuration():
    t = tasks.process_video
    assert PillarError in t.autoretry_for
    assert t.max_retries == 3
    assert t.retry_backoff is not False and t.retry_jitter is True


class _FakeDb:
    def __init__(self):
        self.updates = []

    def get_job(self, job_id):
        return {"_id": job_id, "created_at": datetime.now(timezone.utc)}

    def update_job(self, job_id, fields):
        self.updates.append((job_id, fields))


def test_on_failure_holds_job_for_review_and_dead_letters(monkeypatch):
    fake_db, pushed, depths = _FakeDb(), [], []
    monkeypatch.setattr(tasks, "db", fake_db)
    monkeypatch.setattr(dead_letter, "push", lambda j, e: pushed.append((j, e)))
    monkeypatch.setattr(dead_letter, "depth", lambda: 1)
    monkeypatch.setattr(metrics, "record_dead_letter_depth", depths.append)

    tasks.ModerationTask().on_failure(PillarError("adult_content: 503"), "tid", ["job-1"], {}, None)

    (job_id, fields), = fake_db.updates
    assert job_id == "job-1"
    assert fields["status"] == "failed"
    # Must stay outside the ('approved', 'flagged') filter used by every feed/search query.
    assert fields["overall_status"] == "needs_review"
    assert "adult_content: 503" in fields["reasons"][0]
    assert pushed == [("job-1", "PillarError: adult_content: 503")]
    assert depths == [1]


def test_persistent_pillar_failure_retries_then_never_approves(monkeypatch):
    fake_db, attempts, pushed = _FakeDb(), [], []
    monkeypatch.setattr(tasks, "db", fake_db)
    monkeypatch.setattr(tasks, "_queue_depth", lambda: 0)
    monkeypatch.setattr(tasks.storage, "get_video_path", lambda n: "/nonexistent")
    monkeypatch.setattr(dead_letter, "push", lambda j, e: pushed.append(j))
    monkeypatch.setattr(dead_letter, "depth", lambda: 1)
    monkeypatch.setattr(metrics, "_put", lambda *a, **k: None)

    async def always_fails(job_id):
        attempts.append(job_id)
        raise PillarError("filmmaking_relevance: Rekognition throttled")
    monkeypatch.setattr(tasks, "_run_pillars", always_fails)

    result = tasks.process_video.apply(args=["job-2"])

    assert result.failed()
    assert len(attempts) == 1 + tasks.MAX_RETRIES          # first try + 3 retries
    assert pushed == ["job-2"]
    assert not any(f.get("overall_status") == "approved" for _, f in fake_db.updates)
    assert fake_db.updates[-1][1]["overall_status"] == "needs_review"


def test_successful_job_records_verdict_and_latency(monkeypatch):
    fake_db, latencies = _FakeDb(), []
    monkeypatch.setattr(tasks, "db", fake_db)
    monkeypatch.setattr(tasks, "_queue_depth", lambda: 2)
    monkeypatch.setattr(tasks.storage, "get_video_path", lambda n: "/nonexistent")
    monkeypatch.setattr(metrics, "record_queue_depth", lambda d: None)
    monkeypatch.setattr(metrics, "record_verdict_latency", lambda s, v: latencies.append((s, v)))

    async def ok(job_id):
        return [
            {"pillar": "adult_content", "score": 0.0, "flags": []},
            {"pillar": "ai_deepfake", "score": 0.0, "flags": []},
            {"pillar": "duplicate_content", "score": 0.0, "flags": []},
            {"pillar": "filmmaking_relevance", "score": 1.0, "flags": []},
        ]
    monkeypatch.setattr(tasks, "_run_pillars", ok)

    tasks.process_video.apply(args=["job-3"])

    assert fake_db.updates[-1][1]["overall_status"] == "approved"
    assert fake_db.updates[-1][1]["status"] == "done"
    (secs, verdict), = latencies
    assert verdict == "approved" and 0 <= secs < 5


# ── 3. Dead-letter list ──────────────────────────────────────────────────────

class _FakeRedis:
    def __init__(self):
        self.items = []

    def lpush(self, key, value):
        assert key == dead_letter.KEY
        self.items.insert(0, value)

    def llen(self, key):
        return len(self.items)

    def rpop(self, key):
        return self.items.pop() if self.items else None


def test_dead_letter_push_depth_and_ordered_drain(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(dead_letter, "_client", lambda: fake)

    dead_letter.push("a", "boom-a")
    dead_letter.push("b", "boom-b")
    assert dead_letter.depth() == 2

    drained = dead_letter.pop_all()
    assert [e["job_id"] for e in drained] == ["a", "b"]      # oldest first
    assert drained[0]["error"] == "boom-a" and "failed_at" in drained[0]
    assert dead_letter.depth() == 0


# ── 4. CloudWatch metrics ────────────────────────────────────────────────────

class _FakeCloudWatch:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def put_metric_data(self, **kw):
        if self.fail:
            raise RuntimeError("AccessDenied")
        self.calls.append(kw)


def test_metrics_disabled_without_namespace(monkeypatch):
    fake = _FakeCloudWatch()
    monkeypatch.setattr(metrics, "_client", fake)
    monkeypatch.setattr(metrics.config, "CLOUDWATCH_NAMESPACE", "")
    metrics.record_verdict_latency(3.2, "approved")
    assert fake.calls == []


def test_metrics_emit_when_enabled(monkeypatch):
    fake = _FakeCloudWatch()
    monkeypatch.setattr(metrics, "_client", fake)
    monkeypatch.setattr(metrics.config, "CLOUDWATCH_NAMESPACE", "Misence/Moderation")
    metrics.record_verdict_latency(3.2, "approved")
    metrics.record_queue_depth(4)
    metrics.record_dead_letter_depth(1)

    names = [c["MetricData"][0]["MetricName"] for c in fake.calls]
    assert names == ["VerdictLatencySeconds", "QueueDepth", "DeadLetterDepth"]
    assert fake.calls[0]["Namespace"] == "Misence/Moderation"
    assert fake.calls[0]["MetricData"][0]["Dimensions"] == [{"Name": "Verdict", "Value": "approved"}]


def test_metrics_failure_never_propagates(monkeypatch):
    monkeypatch.setattr(metrics, "_client", _FakeCloudWatch(fail=True))
    monkeypatch.setattr(metrics.config, "CLOUDWATCH_NAMESPACE", "Misence/Moderation")
    metrics.record_queue_depth(1)  # must not raise


# ── 5. Perceptual hashing ────────────────────────────────────────────────────

def _gradient(rows=8, cols=9, flip=False):
    """Deterministic 'frame': brightness rises left->right (or falls, if flip)."""
    return [[(c if not flip else cols - c) * 10 + r for c in range(cols)] for r in range(rows)]


def _noisy(frame, amount):
    return [[v + amount * ((r + c) % 2) for c, v in enumerate(row)] for r, row in enumerate(frame)]


def test_dhash_is_64_bits_per_frame():
    assert len(phash.dhash_frame(_gradient())) == phash.HEX_PER_FRAME
    assert len(phash.fingerprint([_gradient()] * phash.FRAME_COUNT)) == phash.HEX_PER_FRAME * phash.FRAME_COUNT


def test_identical_and_reencoded_frames_match():
    base = [_gradient(flip=bool(i % 2)) for i in range(phash.FRAME_COUNT)]
    fp = phash.fingerprint(base)
    # A re-encode adds small brightness noise; dHash compares neighbours so the hash barely moves.
    reenc = phash.fingerprint([_noisy(f, 1) for f in base])
    assert phash.distance(fp, fp) == 0
    assert phash.distance(fp, reenc) <= phash.NEAR_DUPLICATE_MAX_DISTANCE


def test_unrelated_videos_do_not_match():
    a = phash.fingerprint([_gradient() for _ in range(phash.FRAME_COUNT)])
    b = phash.fingerprint([_gradient(flip=True) for _ in range(phash.FRAME_COUNT)])
    assert phash.distance(a, b) == 64
    assert phash.find_near_duplicate(a, [("other", b)]) is None


def test_distance_none_for_incomparable_fingerprints():
    fp = phash.fingerprint([_gradient()] * phash.FRAME_COUNT)
    assert phash.distance(fp, fp[:-16]) is None
    assert phash.distance("", fp) is None


def test_find_near_duplicate_returns_closest_match():
    base = [_gradient(flip=bool(i % 2)) for i in range(phash.FRAME_COUNT)]
    fp = phash.fingerprint(base)
    close = phash.fingerprint([_noisy(f, 1) for f in base])
    far = phash.fingerprint([_gradient(flip=not bool(i % 2)) for i in range(phash.FRAME_COUNT)])
    found = phash.find_near_duplicate(fp, [("far", far), ("close", close)])
    assert found is not None and found[0] == "close"
