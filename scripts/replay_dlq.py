"""Inspect or replay jobs that failed moderation after all retries (dead-letter list in Redis).

  python scripts/replay_dlq.py            # list entries (non-destructive)
  python scripts/replay_dlq.py --replay   # drain the list, reset each job, and re-enqueue it

Run from the project root with the same .env the worker uses (needs POSTGRES_URL and REDIS_URL).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import dead_letter, db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", action="store_true", help="drain the list and re-enqueue every job")
    args = ap.parse_args()

    if not args.replay:
        client = dead_letter._client()
        entries = [__import__("json").loads(raw) for raw in reversed(client.lrange(dead_letter.KEY, 0, -1))]
        print(f"{len(entries)} dead-lettered job(s)")
        for e in entries:
            print(f"  {e['failed_at']}  {e['job_id']}  {e['error']}")
        return

    from app.tasks import process_video  # imported late: pulls in Celery + all pillars

    entries = dead_letter.pop_all()
    for e in entries:
        db.update_job(e["job_id"], {"status": "pending", "overall_status": None, "reasons": []})
        process_video.delay(e["job_id"])
        print(f"re-enqueued {e['job_id']}")
    print(f"{len(entries)} job(s) replayed")


if __name__ == "__main__":
    main()
