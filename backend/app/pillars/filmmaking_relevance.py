"""Filmmaking-relevance pillar — AWS Rekognition label detection.

Extracts a mid-video frame, sends it to Rekognition DetectLabels, and scores
relevance based on whether filmmaking-related labels are detected (camera,
film, director, cinematography, movie, crew, tripod, lighting, etc.).

Score: 0.0 (not filmmaking) → 1.0 (clearly filmmaking content).
Threshold: score < 0.3 → blocked (inverse scoring — low score is bad).
"""

import asyncio
import os
import tempfile

import boto3

from app import config
from app.pillars.common import PillarError, score_from_seed

_RELEVANCE_THRESHOLD = 0.3

# Labels Rekognition may return that indicate filmmaking or creative content.
# Broad set covers: film gear, performance, narrative, creative arts, and
# general human storytelling — all valid content for the Misence platform.
_FILMMAKING_LABELS = {
    # Film & production gear
    "camera", "film", "movie", "cinema", "director", "cinematography",
    "tripod", "lighting", "crew", "studio", "clapperboard", "clapper",
    "microphone", "boom", "set", "production", "equipment", "lens",
    "monitor", "screen", "projector", "reel", "photography", "video",
    "recording", "television", "broadcast",
    # Performance & acting
    "actor", "actress", "person", "people", "human", "face", "portrait",
    "performance", "theatre", "theater", "stage", "dance", "dancing",
    "music", "musician", "concert", "singer", "band",
    # Narrative & creative arts
    "art", "artistic", "creative", "animation", "cartoon", "drawing",
    "painting", "illustration", "design", "graphic",
    # Sports & action (sports docs, action sequences)
    "sport", "sports", "action", "athlete", "athletics", "competition",
    "race", "game", "match",
    # Nature & landscape (valid for cinematography)
    "nature", "landscape", "outdoors", "sky", "sunset", "sunrise",
    "urban", "city", "architecture", "street",
}


def _get_boto_clients():
    creds = {}
    if config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY:
        creds = {
            "aws_access_key_id": config.AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": config.AWS_SECRET_ACCESS_KEY,
        }
    s3 = boto3.client("s3", region_name=config.AWS_S3_REGION, **creds)
    rek = boto3.client("rekognition", region_name=config.AWS_S3_REGION, **creds)
    return s3, rek


def _check_blocking(job_id: str) -> dict:
    try:
        import cv2
    except ImportError as e:
        if config.AWS_S3_BUCKET:
            # Real deployment without OpenCV is a broken install, not a reason to guess a score.
            raise PillarError(f"filmmaking_relevance: OpenCV not installed ({e})") from e
        # Local dev without S3/OpenCV -> deterministic mock score
        score = score_from_seed(f"filmmaking:{job_id}")
        flags = []
        if score < _RELEVANCE_THRESHOLD:
            flags.append({"label": "not_filmmaking_content", "detail": "mock score (cv2 not installed)"})
        return {"pillar": "filmmaking_relevance", "score": round(score, 3), "flags": flags}

    try:
        s3, rek = _get_boto_clients()
        object_name = f"{job_id}.mp4"

        # Download video and extract one frame from the middle
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        s3.download_file(config.AWS_S3_BUCKET, object_name, tmp_path)

        cap = cv2.VideoCapture(tmp_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
        ret, frame = cap.read()
        cap.release()
        os.unlink(tmp_path)

        if not ret:
            raise RuntimeError("Could not extract frame from video")

        # Encode frame as JPEG bytes for Rekognition
        import cv2 as _cv2
        _, buf = _cv2.imencode(".jpg", frame)
        image_bytes = buf.tobytes()

        # Call Rekognition DetectLabels directly on image bytes (no S3 needed)
        response = rek.detect_labels(
            Image={"Bytes": image_bytes},
            MaxLabels=30,
            MinConfidence=60.0,
        )

        detected = {lbl["Name"].lower() for lbl in response.get("Labels", [])}
        matches = detected & _FILMMAKING_LABELS

        # Score = fraction of filmmaking labels found, capped at 1.0
        # 1 match → 0.5, 2 matches → 1.0 (generous scoring for creative content)
        score = min(1.0, len(matches) / 2.0)

        flags = []
        if score < _RELEVANCE_THRESHOLD:
            flags.append({
                "label": "not_filmmaking_content",
                "detail": f"no filmmaking labels detected (found: {', '.join(detected) or 'none'})",
            })

        return {"pillar": "filmmaking_relevance", "score": round(score, 3), "flags": flags}

    except Exception as e:
        raise PillarError(f"filmmaking_relevance: {e}") from e


async def check(job_id: str) -> dict:
    # Blocking I/O (S3, OpenCV, HTTP) runs off the event loop so the four pillars truly overlap.
    return await asyncio.to_thread(_check_blocking, job_id)
