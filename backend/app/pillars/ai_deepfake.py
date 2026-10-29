"""AI/deepfake-detection pillar — Sightengine AI-generated content detection.

Extracts frames from the S3 video and checks each against Sightengine's
ai-generated-text and genai models to detect synthetically created or
deepfake video content.

Score: 0.0 (real) → 1.0 (AI-generated / deepfake).
Threshold: score >= 0.7 → flagged.
"""

import asyncio
import os
import tempfile
import urllib.request
import urllib.parse
import json

import boto3

from app import config
from app.pillars.common import PillarError, score_from_seed

_DEEPFAKE_THRESHOLD = 0.7


def _sightengine_check_url(image_url: str) -> float:
    """Call Sightengine genai model on a single image URL. Returns AI-generated score 0-1."""
    params = urllib.parse.urlencode({
        "url": image_url,
        "models": "genai",
        "api_user": config.SIGHTENGINE_USER,
        "api_secret": config.SIGHTENGINE_SECRET,
    })
    req_url = f"https://api.sightengine.com/1.0/check.json?{params}"
    with urllib.request.urlopen(req_url, timeout=10) as resp:
        data = json.loads(resp.read())
    # genai model returns type.ai score
    return float(data.get("type", {}).get("ai", 0.0))


def _get_s3_client():
    creds = {}
    if config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY:
        creds = {
            "aws_access_key_id": config.AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": config.AWS_SECRET_ACCESS_KEY,
        }
    return boto3.client("s3", region_name=config.AWS_S3_REGION, **creds)


def _check_blocking(job_id: str) -> dict:
    # Local dev only: no Sightengine credentials configured -> deterministic mock score
    if not config.SIGHTENGINE_USER or not config.SIGHTENGINE_SECRET:
        score = score_from_seed(f"deepfake:{job_id}")
        flags = []
        if score >= _DEEPFAKE_THRESHOLD:
            flags.append({"label": "ai_generated_content", "detail": "mock score"})
        return {"pillar": "ai_deepfake", "score": round(score, 3), "flags": flags}

    try:
        import cv2
        s3 = _get_s3_client()
        object_name = f"{job_id}.mp4"

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
            frame_key = f"_frames/{job_id}/df_frame{i}.jpg"
            s3.upload_file(frame_path, config.AWS_S3_BUCKET, frame_key)
            frame_keys.append((frame_key, frame_path))

        cap.release()
        os.unlink(tmp_path)

        for frame_key, frame_path in frame_keys:
            url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": config.AWS_S3_BUCKET, "Key": frame_key},
                ExpiresIn=300,
            )
            score = _sightengine_check_url(url)
            worst_score = max(worst_score, score)
            os.unlink(frame_path)
            s3.delete_object(Bucket=config.AWS_S3_BUCKET, Key=frame_key)

        flags = []
        if worst_score >= _DEEPFAKE_THRESHOLD:
            flags.append({"label": "ai_generated_content", "detail": f"genai score {round(worst_score, 3)}"})

        return {"pillar": "ai_deepfake", "score": round(worst_score, 3), "flags": flags}

    except Exception as e:
        raise PillarError(f"ai_deepfake: {e}") from e


async def check(job_id: str) -> dict:
    # Blocking I/O (S3, OpenCV, HTTP) runs off the event loop so the four pillars truly overlap.
    return await asyncio.to_thread(_check_blocking, job_id)
