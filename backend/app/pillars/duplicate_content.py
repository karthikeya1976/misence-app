"""Duplicate-content pillar — SHA-256 exact match plus perceptual (dHash) near-match.

Downloads the uploaded video, computes its SHA-256 and a perceptual fingerprint of
FRAME_COUNT evenly spaced frames, then compares both against earlier completed uploads.

Score: 0.0 (unique) -> 0.85 (near-duplicate: re-encoded / resized copy) -> 1.0 (byte-identical).
Thresholds: score >= 1.0 -> blocked, score >= 0.8 -> flagged (see decision_engine.py).

Near-duplicate comparison is a linear scan over stored fingerprints — fine at this scale;
move to an LSH / BK-tree index if the catalogue reaches the hundreds of thousands.
"""

import asyncio
import hashlib
import os
import tempfile

import boto3

from app import config
from app import db
from app import phash
from app.pillars.common import PillarError

_CHUNK = 8 * 1024 * 1024  # 8 MB chunks for large files
_NEAR_DUPLICATE_SCORE = 0.85


def _get_s3_client():
    creds = {}
    if config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY:
        creds = {
            "aws_access_key_id": config.AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": config.AWS_SECRET_ACCESS_KEY,
        }
    return boto3.client("s3", region_name=config.AWS_S3_REGION, **creds)


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _perceptual_fingerprint(path: str) -> str | None:
    """dHash fingerprint of evenly spaced frames, or None if OpenCV/decoding is unavailable."""
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(path)
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total < phash.FRAME_COUNT:
            return None
        grays = []
        for i in range(phash.FRAME_COUNT):
            # Positions are fractions of the video, so a re-encode of the same video lines up.
            cap.set(cv2.CAP_PROP_POS_FRAMES, (total * i) // phash.FRAME_COUNT)
            ok, frame = cap.read()
            if not ok:
                return None
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            grays.append(cv2.resize(gray, (phash.HASH_COLS, phash.HASH_ROWS), interpolation=cv2.INTER_AREA))
        return phash.fingerprint(grays)
    finally:
        cap.release()


def _check_blocking(job_id: str) -> dict:
    tmp_path = None
    try:
        s3 = _get_s3_client()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        s3.download_file(config.AWS_S3_BUCKET, f"{job_id}.mp4", tmp_path)
        file_hash = _sha256_of_file(tmp_path)
        fp = _perceptual_fingerprint(tmp_path)

        # Store both on the job row so future uploads can compare against this one
        db.update_job(job_id, {"file_hash": file_hash, **({"phash": fp} if fp else {})})

        if db.find_duplicate_hash(file_hash, exclude_job_id=job_id):
            return {"pillar": "duplicate_content", "score": 1.0, "flags": [{
                "label": "duplicate_video",
                "detail": f"identical content already exists on the platform (sha256: {file_hash[:16]}…)",
            }]}

        near = phash.find_near_duplicate(fp, db.list_phashes(exclude_job_id=job_id)) if fp else None
        if near:
            return {"pillar": "duplicate_content", "score": _NEAR_DUPLICATE_SCORE, "flags": [{
                "label": "near_duplicate_video",
                "detail": f"visually matches video {near[0][:8]} (mean frame distance {near[1]:.1f}/64)",
            }]}

        return {"pillar": "duplicate_content", "score": 0.0, "flags": []}

    except Exception as e:
        # A failed duplicate check must not read as "unique" — retry, then human review.
        raise PillarError(f"duplicate_content: {e}") from e
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def check(job_id: str) -> dict:
    # Blocking I/O (S3, OpenCV, Postgres) runs off the event loop so the four pillars truly overlap.
    return await asyncio.to_thread(_check_blocking, job_id)
