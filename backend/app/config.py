import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file: app/ -> backend/app -> backend -> project root)
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6380/0")

POSTGRES_URL = os.environ.get("POSTGRES_URL", "")
if not POSTGRES_URL:
    raise RuntimeError(
        "POSTGRES_URL env var is required. "
        "Copy .env.example to .env at the project root and fill in credentials."
    )

# Local temp directory for uploaded video files (fallback when S3 not configured)
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "C:/tmp/video_uploads")

# AWS S3 — required for Day 2+ storage
AWS_ACCESS_KEY_ID     = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_S3_BUCKET         = os.environ.get("AWS_S3_BUCKET", "")
AWS_S3_REGION         = os.environ.get("AWS_S3_REGION", "us-east-2")

# Sightengine — adult content + deepfake detection
SIGHTENGINE_USER   = os.environ.get("SIGHTENGINE_USER", "")
SIGHTENGINE_SECRET = os.environ.get("SIGHTENGINE_SECRET", "")

# AWS Rekognition — filmmaking relevance (uses same IAM role as S3 on EC2)
# No extra keys needed on EC2; local dev can reuse AWS_ACCESS_KEY_ID/SECRET above.

# CloudWatch custom metrics (verdict latency, queue depth, dead-letter depth).
# Empty = metrics disabled (local dev, CI). EC2 sets Misence/Moderation via the CloudFormation UserData.
CLOUDWATCH_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "")
