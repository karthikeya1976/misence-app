# Moderation Policies — Misence

Each pillar module (`backend/app/pillars/`) exposes:

```python
async def check(job_id: str) -> dict
# → {"pillar": str, "score": float (0–1), "flags": [...]}
```

Results flow through `decision_engine.py` which applies the thresholds below.

---

## Pillar 1: Adult Content (`adult_content.py`)

**API**: Sightengine nudity-2.1  
**Score**: probability of explicit/suggestive content (0–1)

| Score range | Verdict contribution |
|-------------|---------------------|
| `>= 0.8` | **Blocked** |
| `0.5 – 0.79` | **Flagged** |
| `< 0.5` | No contribution |

Only explicit nudity triggers a flag — artistic/romance content is below threshold.

---

## Pillar 2: AI / Deepfake Detection (`ai_deepfake.py`)

**API**: Sightengine genai  
**Score**: likelihood the video is AI-generated / synthetic media (0–1)

| Score range | Verdict contribution |
|-------------|---------------------|
| `>= 0.7` | **Flagged** (disclosed/reviewed, not auto-blocked) |
| `< 0.7` | No contribution |

Flagged AI content remains visible in the feed with a disclosure label (future work).

---

## Pillar 3: Duplicate Content (`duplicate_content.py`)

**Method**: SHA-256 hash of the full S3 video object (exact match) plus a perceptual dHash of 5 frames (near match)  
**Score**: `1.0` byte-identical copy already on the platform, `0.85` visually near-identical copy (re-encoded / resized), `0.0` otherwise

| Score | Verdict contribution |
|-------|---------------------|
| `1.0` | **Blocked** |
| `0.85` | **Flagged** (`>= 0.8`) |
| `0.0` | No contribution |

Method detail: after the exact SHA-256 check, a perceptual dHash fingerprint of 5 evenly spaced frames is compared with every stored fingerprint. Near-duplicate = mean Hamming distance across aligned frames <= 10 of 64 bits (`phash.NEAR_DUPLICATE_MAX_DISTANCE`). Zero API cost. Limitations: frames are aligned by position, so trimmed / re-cut videos do not match; the comparison is a linear scan over stored fingerprints.

**Failure policy (all pillars)**: a pillar that errors against a real backend raises instead of returning a mock score. The job is retried (max 3, exponential backoff); if it still fails it is held as `overall_status = needs_review` — hidden from every feed — and dead-lettered for a human.

---

## Pillar 4: Filmmaking Relevance (`filmmaking_relevance.py`)

**API**: AWS Rekognition `DetectLabels` on a mid-video frame  
**Score**: fraction of detected labels that match a filmmaking vocabulary (0–1)  
**Inverse scoring**: low score = off-topic content = blocked

| Score range | Verdict contribution |
|-------------|---------------------|
| `< 0.3` | **Blocked** (off-topic) |
| `>= 0.3` | No contribution |

The filmmaking vocabulary includes labels like: camera, person, performance,
stage, lighting, film, cinema, landscape, architecture, and related terms.
`BLOCK_BELOW_THRESHOLDS` in `decision_engine.py` handles this inverse case.

---

## Aggregation Rules (`decision_engine.py`)

All four pillar results are evaluated together:

```python
# Pseudo-code
if any pillar above its BLOCK_THRESHOLD:
    overall_status = "blocked"
elif any pillar above its FLAG_THRESHOLD:
    overall_status = "flagged"
elif filmmaking_relevance.score < 0.3:
    overall_status = "blocked"   # inverse threshold
else:
    overall_status = "approved"
```

`reasons` lists every threshold crossed, e.g.:
```json
[
  "adult_content: score 0.85 >= 0.8 (blocked threshold)",
  "filmmaking_relevance: score 0.12 < 0.3 (not filmmaking content)"
]
```

---

## Threshold Summary

| Pillar | Block | Flag | Direction |
|--------|-------|------|-----------|
| `adult_content` | `>= 0.8` | `>= 0.5` | Higher = worse |
| `ai_deepfake` | — | `>= 0.7` | Higher = worse |
| `duplicate_content` | `= 1.0` | `>= 0.8` | Higher = worse |
| `filmmaking_relevance` | `< 0.3` | — | **Lower = worse** |
