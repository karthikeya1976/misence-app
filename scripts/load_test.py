"""Burst load test for the moderation pipeline (stdlib only).

Fires N uploads at the same instant, then polls each job to a verdict, and reports:
  - ack latency  : POST /videos return time (does the API stay responsive while the queue is full?)
  - verdict latency (p50 / p95 / max): upload start -> verdict, i.e. what a creator waits
  - throughput   : completed jobs per minute over the whole burst
  - outcomes     : verdict counts, failures, needs_review (a pillar failed after retries)

  python scripts/load_test.py --api URL --email E --password P --clips a.mp4 b.mp4 --uploads 12

WARNING: every upload is a real job on whatever API you point it at (S3 + Sightengine + Rekognition
quota, rows in the DB). Re-uploading the same file is blocked as an exact duplicate (hidden from feeds)
but still runs all four pillars, which is what is being timed. Point it at staging when you have one.
"""

import argparse
import json
import mimetypes
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid


def _request(method, url, headers=None, body=None, timeout=60):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _multipart(path):
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path)[0] or "video/mp4"
    with open(path, "rb") as f:
        data = f.read()
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{os.path.basename(path)}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n").encode()
    tail = (f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="departments"\r\n\r\n\r\n--{boundary}--\r\n').encode()
    return {"Content-Type": f"multipart/form-data; boundary={boundary}"}, head + data + tail


def _pct(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def run(args) -> dict:
    api = args.api.rstrip("/")
    token = _request("POST", f"{api}/auth/login", {"Content-Type": "application/json"},
                     json.dumps({"email": args.email, "password": args.password}).encode())["access_token"]
    # Pre-read the request bodies so every thread starts uploading at the same instant.
    bodies = [_multipart(p) for p in args.clips]
    barrier = threading.Barrier(args.uploads)
    results = [None] * args.uploads

    def worker(i):
        hdr, body = bodies[i % len(bodies)]
        hdr = {**hdr, "Authorization": f"Bearer {token}"}
        row = {"clip": os.path.basename(args.clips[i % len(args.clips)])}
        try:
            barrier.wait()
            t0 = time.time()
            job_id = _request("POST", f"{api}/videos", hdr, body, timeout=300)["task_id"]
            row["ack_s"] = time.time() - t0
            st = {}
            while time.time() - t0 < args.timeout:
                st = _request("GET", f"{api}/videos/{job_id}/status")
                if st.get("status") in ("done", "failed"):
                    break
                time.sleep(0.5)
            row.update(total_s=time.time() - t0, status=st.get("status"), verdict=st.get("overall_status"))
        except Exception as e:  # noqa: BLE001 - report every failure mode, don't crash the burst
            row["error"] = f"{type(e).__name__}: {e}"
        results[i] = row

    start = time.time()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.uploads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - start

    done = [r for r in results if r and r.get("status") == "done"]
    acks = [r["ack_s"] for r in results if r and "ack_s" in r]
    totals = [r["total_s"] for r in done]
    out = {
        "uploads": args.uploads,
        "completed": len(done),
        "errors": [r["error"] for r in results if r and "error" in r],
        "not_finished": sum(1 for r in results if r and "error" not in r and r.get("status") not in ("done", "failed")),
        "failed_or_needs_review": sum(1 for r in results if r and (r.get("status") == "failed" or r.get("verdict") == "needs_review")),
        "verdicts": {v: sum(1 for r in done if r["verdict"] == v) for v in {r["verdict"] for r in done}},
        "wall_clock_s": round(wall, 1),
    }
    if acks:
        out["ack_latency_s"] = {"median": round(statistics.median(acks), 2), "p95": round(_pct(acks, 0.95), 2), "max": round(max(acks), 2)}
    if totals:
        out["verdict_latency_s"] = {"median": round(statistics.median(totals), 1), "p95": round(_pct(totals, 0.95), 1), "max": round(max(totals), 1)}
        out["throughput_jobs_per_min"] = round(len(done) / (max(totals) / 60), 1)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--clips", nargs="+", required=True, help="video files, used round-robin")
    ap.add_argument("--uploads", type=int, default=10, help="simultaneous uploads in the burst")
    ap.add_argument("--timeout", type=float, default=600, help="per-job seconds before giving up")
    args = ap.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    sys.exit(main())
