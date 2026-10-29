import hashlib


def score_from_seed(seed: str) -> float:
    """Derive a deterministic pseudo-random score in [0, 1] from a seed string.

    Lets mock pillars return varied-but-reproducible results per video,
    without needing a real ML model.
    """
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


class PillarError(Exception):
    """A pillar could not produce a trustworthy score (provider error, unreadable media, ...).

    Raised instead of returning a made-up score so the Celery task can retry the job
    and, once retries are exhausted, send it to human review rather than approving it.
    """
