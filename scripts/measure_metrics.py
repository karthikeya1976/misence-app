"""Measure honest, defensible project metrics. Never fills in a number it did not measure.

  python scripts/measure_metrics.py tests
      Runs pytest + vitest; reports test counts, pass/fail, wall time.

  python scripts/measure_metrics.py bench --api URL --email E --password P --manifest clips.json
      Uploads each labeled clip to a live API, polls /videos/{id}/status until done, reports:
        - upload->verdict latency (median / p95), and POST-return->verdict (queue + processing)
        - how many pillar results were check_error / mock fallbacks (those runs are NOT real-API data)
        - verdict accuracy vs your labels, false-positive / false-negative rates, with sample size

  manifest (JSON list):  [{"path": "clips/ok1.mp4", "expected": "approved"}, ...]
  expected is one of approved | flagged | blocked.
  The account must be a creator (POST /videos requires it).
"""

import argparse
import json
import mimetypes
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NPX = "npx.cmd" if os.name == "nt" else "npx"


def _run(cmd, cwd):
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p, time.time() - t0


def measure_tests() -> dict:
    out = {}

    p, secs = _run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"], ROOT)
    last = [ln for ln in p.stdout.strip().splitlines() if ln.strip()][-1:] or [""]
    out["backend_pytest"] = {"summary": last[0], "exit_code": p.returncode, "seconds": round(secs, 1)}

    jpath = os.path.join(ROOT, "frontend", ".vitest-metrics.json")
    p, secs = _run([NPX, "vitest", "run", "--reporter=json", f"--outputFile={jpath}"], os.path.join(ROOT, "frontend"))
    try:
        with open(jpath, encoding="utf-8") as f:
            j = json.load(f)
        out["frontend_vitest"] = {
            "total": j["numTotalTests"], "passed": j["numPassedTests"], "failed": j["numFailedTests"],
            "suites": j["numTotalTestSuites"], "exit_code": p.returncode, "seconds": round(secs, 1),
        }
    except Exception as e:
        out["frontend_vitest"] = {"error": f"could not read vitest output: {e}", "exit_code": p.returncode}
    finally:
        if os.path.exists(jpath):
            os.unlink(jpath)
    return out


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


def measure_bench(args) -> dict:
    api = args.api.rstrip("/")
    tok = _request("POST", f"{api}/auth/login", {"Content-Type": "application/json"},
                   json.dumps({"email": args.email, "password": args.password}).encode())["access_token"]
    with open(args.manifest, encoding="utf-8") as f:
        clips = json.load(f)
    base = os.path.dirname(os.path.abspath(args.manifest))

    rows = []
    for c in clips:
        path = c["path"] if os.path.isabs(c["path"]) else os.path.join(base, c["path"])
        hdr, body = _multipart(path)
        hdr["Authorization"] = f"Bearer {tok}"
        t0 = time.time()
        try:
            resp = _request("POST", f"{api}/videos", hdr, body, timeout=300)
            job_id = resp.get("task_id") or resp["job_id"]
        except urllib.error.HTTPError as e:
            rows.append({"path": c["path"], "error": f"upload HTTP {e.code}: {e.read()[:200]!r}"})
            continue
        t_posted = time.time()
        st = {}
        while time.time() - t_posted < args.timeout:
            st = _request("GET", f"{api}/videos/{job_id}/status")
            if st.get("status") in ("done", "failed"):
                break
            time.sleep(0.25)
        t_done = time.time()
        pillars = st.get("pillars") or []
        errs = [p["pillar"] for p in pillars if any(f.get("label") == "check_error" for f in p.get("flags", []))]
        mock = [p["pillar"] for p in pillars if any("mock" in str(f.get("detail", "")) for f in p.get("flags", []))]
        rows.append({
            "path": c["path"], "expected": c.get("expected"), "status": st.get("status"),
            "verdict": st.get("overall_status"), "total_s": t_done - t0, "post_to_verdict_s": t_done - t_posted,
            "fallback_pillars": sorted(set(errs + mock)),
        })
        print(f"  {c['path']}: {st.get('overall_status')} in {t_done - t0:.1f}s", file=sys.stderr)

    ok = [r for r in rows if r.get("status") == "done"]
    real = [r for r in ok if not r["fallback_pillars"]]
    out = {"attempted": len(clips), "completed": len(ok), "upload_errors_or_timeouts": len(clips) - len(ok),
           "runs_with_mock_or_error_fallback": len(ok) - len(real)}
    if real:
        tot = [r["total_s"] for r in real]
        post = [r["post_to_verdict_s"] for r in real]
        out["latency_real_api_runs_only"] = {
            "n": len(real),
            "upload_to_verdict_median_s": round(statistics.median(tot), 2), "upload_to_verdict_p95_s": round(_pct(tot, 0.95), 2),
            "post_return_to_verdict_median_s": round(statistics.median(post), 2),
            "post_return_to_verdict_p95_s": round(_pct(post, 0.95), 2),
        }
    labeled = [r for r in real if r.get("expected")]
    if labeled:
        good = [r for r in labeled if r["expected"] == "approved"]
        bad = [r for r in labeled if r["expected"] != "approved"]
        fp = [r for r in good if r["verdict"] != "approved"]
        fn = [r for r in bad if r["verdict"] == "approved"]
        out["accuracy_real_api_runs_only"] = {
            "n_labeled": len(labeled),
            "exact_verdict_match": f"{sum(r['verdict'] == r['expected'] for r in labeled)}/{len(labeled)}",
            "false_positives": f"{len(fp)}/{len(good)} acceptable clips wrongly flagged/blocked" if good else "n/a (no approved-labeled clips)",
            "false_negatives": f"{len(fn)}/{len(bad)} bad clips wrongly approved" if bad else "n/a (no bad-labeled clips)",
            "caveat": "small hand-labeled set; quote n alongside any rate",
        }
    out["rows"] = rows
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tests")
    b = sub.add_parser("bench")
    b.add_argument("--api", required=True)
    b.add_argument("--email", required=True)
    b.add_argument("--password", required=True)
    b.add_argument("--manifest", required=True)
    b.add_argument("--timeout", type=float, default=180)
    args = ap.parse_args()
    res = measure_tests() if args.cmd == "tests" else measure_bench(args)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
