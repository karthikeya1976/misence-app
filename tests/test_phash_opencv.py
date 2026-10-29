"""
OpenCV-backed check of the duplicate pillar's frame sampling + dHash on real encoded video files.

Skipped when OpenCV is not installed (it is in backend/requirements.txt, so CI runs it).
Videos are synthetic but photo-like (blurred multi-scale noise drifting over time): flat-colour
test clips are degenerate for dHash and give meaningless distances.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("POSTGRES_URL", "postgresql://unused:unused@localhost:1/unused")

import pytest  # noqa: E402

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from app import phash  # noqa: E402
from app.pillars.duplicate_content import _perceptual_fingerprint  # noqa: E402

W, H, FRAMES = 320, 180, 60


def _scene(seed: int):
    rng = np.random.RandomState(seed)
    base = sum(
        cv2.GaussianBlur(rng.rand(H, W).astype(np.float32), (0, 0), s) * a
        for s, a in ((20, 1.0), (8, 0.6), (3, 0.25))
    )
    base = (base - base.min()) / (base.max() - base.min())
    for f in range(FRAMES):
        shifted = np.roll(base, (f * 2, f * 3), axis=(0, 1))
        mix = 0.5 + 0.5 * np.sin(f / FRAMES * 4 * np.pi + seed)
        g = (shifted * (0.6 + 0.4 * mix) * 255).astype(np.uint8)
        yield cv2.merge([g, np.roll(g, 20, 1), np.roll(g, 45, 0)])


def _write(path, frames, size):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 24, size)
    for fr in frames:
        vw.write(cv2.resize(fr, size, interpolation=cv2.INTER_AREA))
    vw.release()
    return str(path)


def test_resized_and_brightened_copies_match_but_other_videos_do_not(tmp_path):
    orig = _write(tmp_path / "orig.avi", _scene(1), (W, H))
    resized = _write(tmp_path / "resized.avi", _scene(1), (W // 2, H // 2))
    brighter = _write(
        tmp_path / "brighter.avi",
        (np.clip(f.astype(np.int16) * 1.15 + 12, 0, 255).astype(np.uint8) for f in _scene(1)),
        (W, H),
    )
    others = [_write(tmp_path / f"other{s}.avi", _scene(s), (W, H)) for s in (2, 3, 4)]

    ref = _perceptual_fingerprint(orig)
    assert ref is not None and len(ref) == phash.HEX_PER_FRAME * phash.FRAME_COUNT

    for copy in (resized, brighter):
        assert phash.find_near_duplicate(ref, [("copy", _perceptual_fingerprint(copy))]) is not None

    for other in others:
        assert phash.find_near_duplicate(ref, [("other", _perceptual_fingerprint(other))]) is None


def test_unreadable_or_too_short_video_has_no_fingerprint(tmp_path):
    assert _perceptual_fingerprint(str(tmp_path / "missing.avi")) is None
    short = _write(tmp_path / "short.avi", list(_scene(1))[: phash.FRAME_COUNT - 1], (W, H))
    assert _perceptual_fingerprint(short) is None
