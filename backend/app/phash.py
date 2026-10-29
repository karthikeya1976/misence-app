"""Perceptual video fingerprint — catches re-encoded / resized re-uploads that SHA-256 misses.

A fingerprint is the dHash of up to FRAME_COUNT evenly spaced frames, concatenated as hex
(16 hex chars = 64 bits per frame). Two videos are near-duplicates when the mean Hamming
distance across their aligned frames is <= NEAR_DUPLICATE_MAX_DISTANCE (of 64 bits).

Pure logic, no OpenCV: callers pass already-shrunk grayscale frames (HASH_ROWS x HASH_COLS).
Limitation: frames are aligned by position, so a trimmed or re-cut video will not match.
"""

FRAME_COUNT = 5
HASH_ROWS = 8
HASH_COLS = 9  # one extra column so each row yields 8 left-vs-right comparisons
BITS_PER_FRAME = 64
HEX_PER_FRAME = BITS_PER_FRAME // 4
NEAR_DUPLICATE_MAX_DISTANCE = 10


def dhash_frame(gray) -> str:
    """dHash of one HASH_ROWS x HASH_COLS grayscale frame (any 2D indexable) -> 16 hex chars."""
    bits = 0
    for r in range(HASH_ROWS):
        for c in range(HASH_COLS - 1):
            bits = (bits << 1) | (1 if gray[r][c] > gray[r][c + 1] else 0)
    return f"{bits:0{HEX_PER_FRAME}x}"


def fingerprint(grays: list) -> str:
    return "".join(dhash_frame(g) for g in grays)


def distance(a: str, b: str) -> float | None:
    """Mean per-frame Hamming distance (0-64), or None when the fingerprints aren't comparable."""
    if not a or not b or len(a) != len(b) or len(a) % HEX_PER_FRAME:
        return None
    frames = len(a) // HEX_PER_FRAME
    total = 0
    for i in range(frames):
        lo, hi = i * HEX_PER_FRAME, (i + 1) * HEX_PER_FRAME
        total += bin(int(a[lo:hi], 16) ^ int(b[lo:hi], 16)).count("1")
    return total / frames


def find_near_duplicate(fp: str, candidates: list[tuple[str, str]]) -> tuple[str, float] | None:
    """Closest candidate (job_id, fingerprint) within the threshold, else None."""
    best = None
    for job_id, other in candidates:
        d = distance(fp, other)
        if d is not None and d <= NEAR_DUPLICATE_MAX_DISTANCE and (best is None or d < best[1]):
            best = (job_id, d)
    return best
