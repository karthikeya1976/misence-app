"""Decision Engine: compiles pillar scores into an overall moderation verdict.

Promotes the aggregator role to a named, standalone module matching the
flow-graph architecture. See docs/moderation_policies.md for threshold rules.
"""

BLOCK_THRESHOLDS = {
    "adult_content": 0.8,       # explicit nudity → blocked
    "duplicate_content": 1.0,   # exact duplicate → blocked
}

FLAG_THRESHOLDS = {
    "adult_content": 0.5,       # borderline nudity → flagged for review
    "ai_deepfake": 0.7,         # likely AI-generated → flagged
    "duplicate_content": 0.8,   # visually near-identical re-upload (score 0.85) → flagged
}

# Pillars where a LOW score triggers a block (relevance checks, not harm checks)
BLOCK_BELOW_THRESHOLDS = {
    "filmmaking_relevance": 0.3,
}


def aggregate(pillar_results: list[dict]) -> dict:
    blocked_reasons = []
    flagged_reasons = []

    for result in pillar_results:
        pillar = result["pillar"]
        score = result["score"]

        block_threshold = BLOCK_THRESHOLDS.get(pillar)
        if block_threshold is not None and score >= block_threshold:
            blocked_reasons.append(
                f"{pillar}: score {score} >= {block_threshold} (blocked threshold)"
            )
            continue

        # Relevance pillars: block when score is too LOW
        block_below = BLOCK_BELOW_THRESHOLDS.get(pillar)
        if block_below is not None and score < block_below:
            blocked_reasons.append(
                f"{pillar}: score {score} < {block_below} (not filmmaking content)"
            )
            continue

        flag_threshold = FLAG_THRESHOLDS.get(pillar)
        if flag_threshold is not None and score >= flag_threshold:
            flagged_reasons.append(
                f"{pillar}: score {score} >= {flag_threshold} (flagged threshold)"
            )

    if blocked_reasons:
        overall_status = "blocked"
        reasons = blocked_reasons + flagged_reasons
    elif flagged_reasons:
        overall_status = "flagged"
        reasons = flagged_reasons
    else:
        overall_status = "approved"
        reasons = []

    return {"overall_status": overall_status, "reasons": reasons}
