"""Adult-content pillar — Sightengine nudity detection.

Extracts up to 5 evenly-spaced frames from the S3 video, sends each to
Sightengine's nudity model, and returns the worst-case nudity score.
Only explicit nudity triggers a flag — suggestive/romance scenes do not.

Score: 0.0 (clean) → 1.0 (explicit nudity detected).
Threshold: score >= 0.7 → flagged.
"""

import asyncio
import os
import tempfile
import urllib.request
import urllib.parse

import boto3

from app import config
from app.pillars.common import PillarError, score_from_seed

_NUDITY_THRESHOLD = 0.7

# Sightengine checks a single image URL — we extract frames as temp files
# and upload them to S3 with a short-lived presigned URL for Sightengine to fetch.

def _sightengine_check_url(image_url: str) -> float:
    """Call Sightengine nudity API on a single image URL. Returns nudity score 0-1."""
    params = urllib.parse.urlencode({
        "url": image_url,
        "models": "nudity-2.1",
        "api_user": config.SIGHTENGINE_USER,
        "api_secret": config.SIGHTENGINE_SECRET,
    })
    req_url = f"https://api.sightengine.com/1.0/check.json?{params}"
    with urllib.request.urlopen(req_url, timeout=10) as resp:
        import json
        data = json.loads(resp.read())
    # nudity-2.1 returns classes: raw, partial, safe
    nudity = data.get("nudity", {})
    # Only count explicit nudity (raw = fully nude)
    return float(nudity.get("raw", 0.0))


def _get_s3_client():
    creds = {}
    if config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY:
        creds = {
            "aws_access_key_id": config.AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": config.AWS_SECRET_ACCESS_KEY,
        }
    return boto3.client("s3", region_name=config.AWS_S3_REGION, **creds)


def _presigned_url_for_frame(s3, bucket: str, key: str) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=300,
    )


def _check_blocking(job_id: str) -> dict:
    # Local dev only: no Sightengine credentials configured -> deterministic mock score
    if not config.SIGHTENGINE_USER or not config.SIGHTENGINE_SECRET:
        score = score_from_seed(f"adult:{job_id}")
        flags = []
        if score >= _NUDITY_THRESHOLD:
            flags.append({"label": "explicit_nudity", "detail": "mock score"})
        return {"pillar": "adult_content", "score": round(score, 3), "flags": flags}

    try:
        import cv2  # OpenCV for frame extraction
        s3 = _get_s3_client()
        object_name = f"{job_id}.mp4"

        # Download video to a temp file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        s3.download_file(config.AWS_S3_BUCKET, object_name, tmp_path)

        cap = cv2.VideoCapture(tmp_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_count = min(5, max(1, total_frames))
        step = max(1, total_frames // sample_count)

        worst_score = 0.0
        frame_keys = []

        for i in range(sample_count):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
            ret, frame = cap.read()
            if not ret:
                continue
            frame_path = f"{tmp_path}_frame{i}.jpg"
            cv2.imwrite(frame_path, frame)
            frame_key = f"_frames/{job_id}/frame{i}.jpg"
            s3.upload_file(frame_path, config.AWS_S3_BUCKET, frame_key)
            frame_keys.append((frame_key, frame_path))

        cap.release()
        os.unlink(tmp_path)

        # Check each frame
        for frame_key, frame_path in frame_keys:
            url = _presigned_url_for_frame(s3, config.AWS_S3_BUCKET, frame_key)
            score = _sightengine_check_url(url)
            worst_score = max(worst_score, score)
            os.unlink(frame_path)
            # Clean up temp frame from S3
            s3.delete_object(Bucket=config.AWS_S3_BUCKET, Key=frame_key)

        flags = []
        if worst_score >= _NUDITY_THRESHOLD:
            flags.append({"label": "explicit_nudity", "detail": f"nudity score {round(worst_score, 3)}"})

        return {"pillar": "adult_content", "score": round(worst_score, 3), "flags": flags}

    except Exception as e:
        # Never substitute a made-up score for a real provider failure: let the task retry,
        # then send the job to human review (see tasks.ModerationTask.on_failure).
        raise PillarError(f"adult_content: {e}") from e


async def check(job_id: str) -> dict:
    # Blocking I/O (S3, OpenCV, HTTP) runs off the event loop so the four pillars truly overlap.
    return await asyncio.to_thread(_check_blocking, job_id)
