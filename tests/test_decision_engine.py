"""
Unit tests for backend/app/decision_engine.py.

Pure-logic module (no DB, no network) — safe to run in any CI environment
without a Postgres/Redis service container. This is the regression gate's
first line of defense: the threshold table in docs/moderation_policies.md
must always match this module's actual behavior.
"""
import sys
from pathlib import Path

# Import the module directly by path so this test doesn't need `app.main`
# (which calls db._ensure_schema() at import time and requires a live DB).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.decision_engine import aggregate  # noqa: E402


def result(pillar: str, score: float) -> dict:
    return {"pillar": pillar, "score": score, "flags": []}


class TestApproved:
    def test_all_clean_scores_approve(self):
        results = [
            result("adult_content", 0.1),
            result("ai_deepfake", 0.1),
            result("duplicate_content", 0.0),
            result("filmmaking_relevance", 0.9),
        ]
        verdict = aggregate(results)
        assert verdict["overall_status"] == "approved"
        assert verdict["reasons"] == []

    def test_empty_results_approve(self):
        verdict = aggregate([])
        assert verdict["overall_status"] == "approved"


class TestBlocked:
    def test_adult_content_at_block_threshold_blocks(self):
        verdict = aggregate([result("adult_content", 0.8)])
        assert verdict["overall_status"] == "blocked"
        assert "adult_content" in verdict["reasons"][0]

    def test_adult_content_just_below_block_threshold_does_not_block(self):
        verdict = aggregate([result("adult_content", 0.79)])
        assert verdict["overall_status"] != "blocked"

    def test_duplicate_content_exact_match_blocks(self):
        verdict = aggregate([result("duplicate_content", 1.0)])
        assert verdict["overall_status"] == "blocked"

    def test_duplicate_content_zero_does_not_block(self):
        verdict = aggregate([result("duplicate_content", 0.0)])
        assert verdict["overall_status"] == "approved"

    def test_filmmaking_relevance_inverse_scoring_blocks_when_low(self):
        # Inverse threshold: LOW score = off-topic = blocked
        verdict = aggregate([result("filmmaking_relevance", 0.29)])
        assert verdict["overall_status"] == "blocked"
        assert "not filmmaking content" in verdict["reasons"][0]

    def test_filmmaking_relevance_at_threshold_does_not_block(self):
        verdict = aggregate([result("filmmaking_relevance", 0.3)])
        assert verdict["overall_status"] == "approved"


class TestFlagged:
    def test_adult_content_flag_threshold_flags_not_blocks(self):
        verdict = aggregate([result("adult_content", 0.5)])
        assert verdict["overall_status"] == "flagged"

    def test_ai_deepfake_flag_threshold_flags(self):
        verdict = aggregate([result("ai_deepfake", 0.7)])
        assert verdict["overall_status"] == "flagged"

    def test_ai_deepfake_never_blocks_regardless_of_score(self):
        # ai_deepfake has no BLOCK_THRESHOLDS entry — must only ever flag
        verdict = aggregate([result("ai_deepfake", 1.0)])
        assert verdict["overall_status"] == "flagged"


class TestAggregationPriority:
    def test_block_takes_priority_over_flag(self):
        results = [
            result("adult_content", 0.9),   # blocks
            result("ai_deepfake", 0.9),      # would flag
        ]
        verdict = aggregate(results)
        assert verdict["overall_status"] == "blocked"
        # Both reasons should still be reported, blocked first
        assert any("adult_content" in r for r in verdict["reasons"])
        assert any("ai_deepfake" in r for r in verdict["reasons"])

    def test_multiple_block_reasons_all_reported(self):
        results = [
            result("adult_content", 0.95),
            result("duplicate_content", 1.0),
        ]
        verdict = aggregate(results)
        assert verdict["overall_status"] == "blocked"
        assert len(verdict["reasons"]) == 2

    def test_unknown_pillar_never_affects_verdict(self):
        # A pillar with no configured thresholds should be silently ignored,
        # not crash and not affect the verdict — keeps pillars.check() plug-and-play
        verdict = aggregate([result("some_future_pillar", 0.99)])
        assert verdict["overall_status"] == "approved"


# -- Duplicate pillar: exact vs near-duplicate --------------------------------

def test_near_duplicate_is_flagged_not_blocked():
    # Pillar scores a perceptual (re-encoded / resized) match 0.85: held for review, not auto-blocked.
    out = aggregate([result("duplicate_content", 0.85), result("filmmaking_relevance", 1.0)])
    assert out["overall_status"] == "flagged"
    assert "duplicate_content" in out["reasons"][0]


def test_exact_duplicate_is_still_blocked():
    out = aggregate([result("duplicate_content", 1.0), result("filmmaking_relevance", 1.0)])
    assert out["overall_status"] == "blocked"


def test_unique_video_is_not_flagged_by_duplicate_pillar():
    out = aggregate([result("duplicate_content", 0.0), result("filmmaking_relevance", 1.0)])
    assert out["overall_status"] == "approved"
