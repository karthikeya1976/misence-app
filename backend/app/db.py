import json
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg2
import psycopg2.extras

from app import config

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS videos (
    id             TEXT PRIMARY KEY,
    filename       TEXT NOT NULL,
    file_path      TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    overall_status TEXT,
    pillar_results JSONB,
    reasons        JSONB,
    size_bytes     INTEGER,
    user_id        UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    account_type  TEXT NOT NULL DEFAULT 'viewer',
    department    TEXT,
    credits       INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_CREATE_FOLLOWS_TABLE = """
CREATE TABLE IF NOT EXISTS follows (
    follower_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    following_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (follower_id, following_id)
);
"""

_CREATE_COMMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS comments (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id   TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_CREATE_COMMENTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_comments_video_id ON comments(video_id)
"""

_CREATE_HOUSES_TABLE = """
CREATE TABLE IF NOT EXISTS houses (
    id          TEXT PRIMARY KEY,
    owner_id    UUID REFERENCES users(id),
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_CREATE_HOUSE_CREATOR_MEMBERS_TABLE = """
CREATE TABLE IF NOT EXISTS house_creator_members (
    house_id   TEXT NOT NULL REFERENCES houses(id) ON DELETE CASCADE,
    creator_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (house_id, creator_id)
);
"""

_CREATE_HOUSE_VIDEO_MEMBERS_TABLE = """
CREATE TABLE IF NOT EXISTS house_video_members (
    house_id   TEXT NOT NULL REFERENCES houses(id) ON DELETE CASCADE,
    video_id   TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    added_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (house_id, video_id)
);
"""

# One row per (video, department) tag. is_primary marks the single tag that
# was auto-derived from the uploader's department at upload time (frozen,
# per the design doc's edge case: it does NOT live-track a creator's later
# department changes). Enforcing "exactly one primary per video" as a DB
# constraint (rather than app-level discipline alone) needs a partial unique
# index, added below in _ensure_schema — CREATE TABLE can't express it inline
# against future rows.
_CREATE_VIDEO_DEPARTMENT_TAGS_TABLE = """
CREATE TABLE IF NOT EXISTS video_department_tags (
    video_id   TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    department TEXT NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    tagged_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (video_id, department)
);
"""

_CREATE_VIDEO_DEPT_TAGS_PRIMARY_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_video_dept_tags_one_primary
ON video_department_tags (video_id) WHERE is_primary
"""

_CREATE_VIDEO_DEPT_TAGS_DEPARTMENT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_video_dept_tags_department
ON video_department_tags (department)
"""

# Backfill: every video uploaded before this feature shipped has zero rows in
# video_department_tags. Since get_department_house_feed now requires a tag
# row to match (not a fallback to users.department), an unpatched pre-
# existing video would silently vanish from every built-in department feed
# the moment this deploys — a real regression caught via test_houses.py's
# existing suite, not anticipated in the original design doc. Backfill gives
# each untagged video a primary tag equal to its creator's CURRENT
# users.department, once, idempotently (WHERE NOT EXISTS — never touches a
# video that already has any tag row, so it can't clobber real tags written
# after this feature shipped). Re-run safe on every startup.
_BACKFILL_MISSING_PRIMARY_TAGS = """
INSERT INTO video_department_tags (video_id, department, is_primary)
SELECT v.id, u.department, TRUE
FROM videos v
JOIN users u ON v.user_id::uuid = u.id
WHERE u.department IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM video_department_tags t WHERE t.video_id = v.id)
ON CONFLICT (video_id, department) DO NOTHING
"""

# Per-video, per-user credit — replaces the old unauthenticated,
# undeduplicated POST /videos/{id}/credit counter (which only ever
# incremented users.credits with no way to know who credited what, or to
# ever undo it). One row per (video_id, user_id): a user can credit a video
# at most once, and can un-credit it (row deleted) — same toggle shape as
# follows/house-membership tables elsewhere in this file. This is also what
# makes a per-video engagement score (feed ranking) trustworthy: a lifetime
# creator-level counter can't tell a genuinely good new video apart from an
# old video by a creator who happened to accumulate credits years ago.
_CREATE_VIDEO_CREDITS_TABLE = """
CREATE TABLE IF NOT EXISTS video_credits (
    video_id   TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (video_id, user_id)
);
"""

_CREATE_VIDEO_CREDITS_VIDEO_INDEX = """
CREATE INDEX IF NOT EXISTS idx_video_credits_video_id ON video_credits(video_id)
"""

# "Not interested" — a viewer can dismiss one video from their own feed,
# permanently, per the confirmed scope (per-video only, no creator-level
# snooze). One row per (user_id, video_id); get_feed excludes any video the
# viewer has dismissed via a NOT EXISTS anti-join, same pattern the
# department-tag EXISTS join elsewhere in this file already establishes.
_CREATE_DISMISSED_VIDEOS_TABLE = """
CREATE TABLE IF NOT EXISTS dismissed_videos (
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    video_id   TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, video_id)
);
"""

# Backfill: video_credits starts empty even though users.credits may already
# hold nonzero lifetime totals from the old unauthenticated counter. Rather
# than fabricate fake per-user credit rows for historical data with no real
# per-user record (impossible — the old counter never recorded who credited
# what), users.credits is left as a frozen historical total and the new
# ranking score (get_feed) reads ONLY from video_credits going forward. This
# means a creator's pre-existing lifetime credits total stays visible on
# their profile but no longer feeds the ranking algorithm — a deliberate
# behavior change, not an oversight: an unverifiable historical counter is
# not a signal the new ranking formula should trust.




def _connect():
    conn = psycopg2.connect(config.POSTGRES_URL)
    conn.autocommit = True
    return conn


def _ensure_schema() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            # Core tables (order matters: users before videos before follows/comments)
            cur.execute(_CREATE_USERS_TABLE)
            cur.execute(_CREATE_TABLE)
            cur.execute(_CREATE_FOLLOWS_TABLE)
            cur.execute(_CREATE_COMMENTS_TABLE)
            cur.execute(_CREATE_COMMENTS_INDEX)
            cur.execute(_CREATE_HOUSES_TABLE)
            cur.execute(_CREATE_HOUSE_CREATOR_MEMBERS_TABLE)
            cur.execute(_CREATE_HOUSE_VIDEO_MEMBERS_TABLE)
            cur.execute(_CREATE_VIDEO_DEPARTMENT_TAGS_TABLE)
            cur.execute(_CREATE_VIDEO_DEPT_TAGS_PRIMARY_UNIQUE_INDEX)
            cur.execute(_CREATE_VIDEO_DEPT_TAGS_DEPARTMENT_INDEX)
            cur.execute(_CREATE_VIDEO_CREDITS_TABLE)
            cur.execute(_CREATE_VIDEO_CREDITS_VIDEO_INDEX)
            cur.execute(_CREATE_DISMISSED_VIDEOS_TABLE)
            # Column migrations — safe to re-run because of IF NOT EXISTS
            cur.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS user_id TEXT")
            cur.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS file_hash TEXT")
            cur.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS phash TEXT")
            cur.execute("ALTER TABLE users  ADD COLUMN IF NOT EXISTS credits INTEGER NOT NULL DEFAULT 0")
            cur.execute("ALTER TABLE users  ADD COLUMN IF NOT EXISTS department TEXT")
            cur.execute(_BACKFILL_MISSING_PRIMARY_TAGS)



def create_job(job_id: str, filename: str, file_path: Optional[str] = None, user_id: Optional[str] = None) -> None:
    now = datetime.now(timezone.utc)
    sql = """
        INSERT INTO videos (id, filename, file_path, status, user_id, created_at, updated_at)
        VALUES (%s, %s, %s, 'pending', %s, %s, %s)
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (job_id, filename, file_path, user_id, now, now))


# ── Video department tags ───────────────────────────────────────────────────
# video_department_tags is a many-to-many join: one video can carry a primary
# tag (auto-derived from the uploader's department, frozen at upload time —
# it does not live-track later department changes) plus zero-or-more
# additional tags the creator explicitly selected. See docs/architecture.md
# for the full design rationale (mitigation-plan doc / this feature).

def set_video_department_tags(video_id: str, primary_department: str, additional_departments: list[str]) -> None:
    """Write a video's full tag set in one transaction: the primary tag plus
    every additional tag, deduplicated (a department appearing in both the
    primary slot and the additional list collapses to just the primary row —
    mirrors the design doc's edge case on primary/additional overlap).
    Called once, at upload time, from inside the same INSERT flow as
    create_job — never exposed as a standalone endpoint for the primary tag,
    since the primary is server-derived, not client-writable (edge case:
    server always sets it regardless of what the client sends)."""
    additional = [d for d in dict.fromkeys(additional_departments) if d != primary_department]
    rows = [(video_id, primary_department, True)] + [(video_id, d, False) for d in additional]
    sql = """
        INSERT INTO video_department_tags (video_id, department, is_primary)
        VALUES (%s, %s, %s)
        ON CONFLICT (video_id, department) DO NOTHING
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)


def get_video_department_tags(video_id: str) -> list[dict]:
    """Return every department tag for one video, primary first."""
    sql = """
        SELECT department, is_primary, tagged_at
        FROM video_department_tags
        WHERE video_id = %s
        ORDER BY is_primary DESC, tagged_at ASC
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (video_id,))
            return [dict(r) for r in cur.fetchall()]


def get_department_tags_for_videos(video_ids: list[str]) -> dict[str, list[dict]]:
    """Batch-fetch tags for many videos at once (feed rows), keyed by video_id —
    avoids an N+1 query per card when enriching a feed/list response."""
    if not video_ids:
        return {}
    sql = """
        SELECT video_id, department, is_primary
        FROM video_department_tags
        WHERE video_id = ANY(%s)
        ORDER BY is_primary DESC, tagged_at ASC
    """
    out: dict[str, list[dict]] = {vid: [] for vid in video_ids}
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (video_ids,))
            for r in cur.fetchall():
                out.setdefault(r["video_id"], []).append({"department": r["department"], "is_primary": r["is_primary"]})
    return out


def add_video_department_tag(video_id: str, department: str) -> None:
    """Add one additional tag post-upload. Never used for the primary slot —
    the route layer rejects is_primary changes before this is called
    (edge case: primary removal/reassignment isn't an operation this layer
    exposes at all, not just one that's blocked after the fact)."""
    sql = """
        INSERT INTO video_department_tags (video_id, department, is_primary)
        VALUES (%s, %s, FALSE)
        ON CONFLICT (video_id, department) DO NOTHING
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (video_id, department))


def remove_video_department_tag(video_id: str, department: str) -> bool:
    """Delete one tag row, but only if it is not the primary — returns False
    (no-op) if the target row is_primary, so the guarantee holds even against
    a direct DB-layer call, not only the route's own pre-check (defense in
    depth for the 'primary can never be removed' rule)."""
    sql = "DELETE FROM video_department_tags WHERE video_id = %s AND department = %s AND is_primary = FALSE"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (video_id, department))
            return cur.rowcount > 0


def update_job(job_id: str, fields: dict[str, Any]) -> None:
    fields = dict(fields)
    fields["updated_at"] = datetime.now(timezone.utc)

    # Serialize list/dict values to JSON strings for JSONB columns
    jsonb_cols = {"pillar_results", "reasons"}
    set_parts = []
    values = []
    for col, val in fields.items():
        set_parts.append(f"{col} = %s")
        if col in jsonb_cols and val is not None:
            values.append(json.dumps(val))
        else:
            values.append(val)
    values.append(job_id)

    sql = f"UPDATE videos SET {', '.join(set_parts)} WHERE id = %s"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, values)


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    sql = "SELECT * FROM videos WHERE id = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (job_id,))
            row = cur.fetchone()
    if row is None:
        return None
    d = dict(row)
    # Remap 'id' → '_id' so existing main.py callers (j["job_id"] = j.pop("_id")) work unchanged
    d["_id"] = d.pop("id")
    return d


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    sql = "SELECT * FROM videos ORDER BY created_at DESC LIMIT %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["_id"] = d.pop("id")
        result.append(d)
    return result


# Ranking score for the 'recommended' bucket — a right-sized version of the
# weighted-combination principle from the feed/recommendation design doc,
# without the ML infrastructure that doc assumes (no funnel, no learned
# model — this app's real scale doesn't call for either). Combines three
# signals, each normalized to a comparable range before weighting:
#
#   score = w_credit * credits
#         + w_comment * comments
#         + w_recency * recency_decay(age_hours)
#
# recency_decay halves every RECENCY_HALF_LIFE_HOURS (a classic
# exponential-decay ranking shape, the same family as Reddit/Hacker News'
# own front-page formulas) — chosen over a hard recency cutoff so a video's
# rank degrades smoothly rather than falling off a cliff at some arbitrary
# age boundary. credits and comments are NOT decayed by age: an old video
# that's still earning fresh engagement should still be able to rank, which
# is exactly the "old popular creator always wins" problem this replaces.
#
# All-SQL (no per-row Python scoring loop) so ORDER BY can push the sort
# down to Postgres rather than fetching every candidate row into the app
# just to sort it — the same "let the database do it" posture the rest of
# this file's queries already take.
RECENCY_HALF_LIFE_HOURS = 48
CREDIT_WEIGHT = 3.0
COMMENT_WEIGHT = 2.0
RECENCY_WEIGHT = 1.0

_RANKING_SCORE_SQL = f"""
    ( {CREDIT_WEIGHT}  * COALESCE(vc.credit_count, 0)
    + {COMMENT_WEIGHT} * COALESCE(cc.comment_count, 0)
    + {RECENCY_WEIGHT} * POWER(0.5, EXTRACT(EPOCH FROM (NOW() - v.created_at)) / 3600.0 / {RECENCY_HALF_LIFE_HOURS})
    )
"""


def get_feed(limit: int = 50, viewer_id: Optional[str] = None) -> dict[str, Any]:
    """Return the smart feed split into two buckets:
    - 'enrouted': approved videos from creators the viewer follows (newest first —
      deliberately NOT ranked by the engagement score below: a follow is an
      explicit signal the viewer wants to see this creator's work regardless
      of how popular any single video is, so this bucket stays chronological)
    - 'recommended': remaining approved videos ranked by a weighted engagement
      score (credits + comments + recency decay — see _RANKING_SCORE_SQL)

    If viewer_id is None (logged-out), only the recommended bucket is
    populated, and no dismissed-video filtering applies (dismissals are
    per-user; a logged-out viewer has no dismissal history to exclude).
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            enrouted: list[dict] = []
            if viewer_id:
                cur.execute("""
                    SELECT v.*, u.name AS creator_name, u.department AS creator_department,
                           u.credits AS creator_credits
                    FROM videos v
                    JOIN users u ON v.user_id::uuid = u.id
                    JOIN follows f ON f.following_id = u.id
                    WHERE v.overall_status IN ('approved', 'flagged')
                      AND f.follower_id = %s::uuid
                      AND NOT EXISTS (
                        SELECT 1 FROM dismissed_videos d
                        WHERE d.video_id = v.id AND d.user_id = %s::uuid
                      )
                    ORDER BY v.created_at DESC
                    LIMIT %s
                """, (viewer_id, viewer_id, limit))
                enrouted = [dict(r) for r in cur.fetchall()]

            # Exclude already-enrouted video ids from recommendations
            enrouted_ids = tuple(r["id"] for r in enrouted) or ("",)

            dismissed_filter = ""
            params: list = [enrouted_ids]
            if viewer_id:
                dismissed_filter = """
                  AND NOT EXISTS (
                    SELECT 1 FROM dismissed_videos d
                    WHERE d.video_id = v.id AND d.user_id = %s::uuid
                  )
                """
                params.append(viewer_id)
            params.append(limit)

            cur.execute(f"""
                SELECT v.*, u.name AS creator_name, u.department AS creator_department,
                       u.credits AS creator_credits,
                       {_RANKING_SCORE_SQL} AS ranking_score
                FROM videos v
                JOIN users u ON v.user_id::uuid = u.id
                LEFT JOIN (
                    SELECT video_id, COUNT(*) AS credit_count
                    FROM video_credits GROUP BY video_id
                ) vc ON vc.video_id = v.id
                LEFT JOIN (
                    SELECT video_id, COUNT(*) AS comment_count
                    FROM comments GROUP BY video_id
                ) cc ON cc.video_id = v.id
                WHERE v.overall_status IN ('approved', 'flagged')
                  AND v.id NOT IN %s
                  {dismissed_filter}
                ORDER BY ranking_score DESC, v.created_at DESC
                LIMIT %s
            """, params)
            recommended = [dict(r) for r in cur.fetchall()]

    def _normalise(rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            d = dict(row)
            d["_id"] = d.pop("id")
            out.append(d)
        return out

    return {
        "enrouted": _normalise(enrouted),
        "recommended": _normalise(recommended),
    }


def dismiss_video(user_id: str, video_id: str) -> None:
    """'Not interested' — hide one video from this user's feed going
    forward (per-video only, no creator-level snooze, per the confirmed
    scope). Idempotent, matching this file's other toggle-membership
    INSERT ... ON CONFLICT DO NOTHING precedent."""
    sql = """
        INSERT INTO dismissed_videos (user_id, video_id)
        VALUES (%s::uuid, %s)
        ON CONFLICT DO NOTHING
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, video_id))


def create_user(name: str, email: str, password_hash: str) -> dict:
    sql = """
        INSERT INTO users (name, email, password_hash)
        VALUES (%s, %s, %s)
        RETURNING id, name, email, account_type, department, created_at
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (name, email, password_hash))
            return dict(cur.fetchone())


def get_user_by_id(user_id: str) -> Optional[dict]:
    sql = "SELECT * FROM users WHERE id = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[dict]:
    sql = "SELECT * FROM users WHERE email = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
    return dict(row) if row else None


def upgrade_to_creator(user_id: str, department: str) -> dict:
    sql = """
        UPDATE users
        SET account_type = 'creator', department = %s
        WHERE id = %s
        RETURNING id, name, email, account_type, department
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (department, user_id))
            return dict(cur.fetchone())


def find_duplicate_hash(file_hash: str, exclude_job_id: str) -> bool:
    """Return True if another completed video with the same SHA-256 hash exists."""
    sql = """
        SELECT 1 FROM videos
        WHERE file_hash = %s AND id != %s AND status = 'done'
        LIMIT 1
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (file_hash, exclude_job_id))
            return cur.fetchone() is not None


def list_phashes(exclude_job_id: str) -> list[tuple[str, str]]:
    """(job_id, perceptual fingerprint) of every other completed video, for near-duplicate matching."""
    sql = "SELECT id, phash FROM videos WHERE phash IS NOT NULL AND id != %s AND status = 'done'"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (exclude_job_id,))
            return [(str(r[0]), r[1]) for r in cur.fetchall()]


# ── Credits ──────────────────────────────────────────────────────────────────
# Per-video, per-user credit toggle — replaces the old unauthenticated,
# undeduplicated add_credit() counter entirely (not kept alongside it: the
# old counter has exactly one real caller, no tests reference it directly,
# and running two parallel credit systems would be confusing with no
# benefit — see the confirmed scope decision on this feature). users.credits
# itself is left untouched as a frozen historical total (see
# _CREATE_DISMISSED_VIDEOS_TABLE's neighboring comment) — nothing here
# writes to it anymore.

def toggle_video_credit(video_id: str, user_id: str) -> dict:
    """Credit a video if the user hasn't already; un-credit it if they have.
    Returns {'credited': bool, 'credits': int} — the new state and the
    video's total credit count after the toggle."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM video_credits WHERE video_id = %s AND user_id = %s::uuid",
                (video_id, user_id),
            )
            already_credited = cur.fetchone() is not None

            if already_credited:
                cur.execute(
                    "DELETE FROM video_credits WHERE video_id = %s AND user_id = %s::uuid",
                    (video_id, user_id),
                )
            else:
                cur.execute(
                    "INSERT INTO video_credits (video_id, user_id) VALUES (%s, %s::uuid) "
                    "ON CONFLICT DO NOTHING",
                    (video_id, user_id),
                )

            cur.execute("SELECT COUNT(*) FROM video_credits WHERE video_id = %s", (video_id,))
            total = cur.fetchone()[0]

    return {"credited": not already_credited, "credits": total}


def get_video_credit_state(video_id: str, user_id: str) -> bool:
    """Whether user_id has already credited video_id — used to render the
    star button's filled/unfilled state correctly on initial feed load,
    fixing the pre-existing bug where 'credited' only ever reflected
    same-session client state, never the real server-side record."""
    sql = "SELECT 1 FROM video_credits WHERE video_id = %s AND user_id = %s::uuid"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (video_id, user_id))
            return cur.fetchone() is not None


def get_engagement_counts_for_videos(video_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch {video_id: {'credits': int, 'comments': int}} for many
    videos at once — same batching shape as get_department_tags_for_videos,
    avoiding an N+1 query per feed card. Two separate COUNT-and-GROUP
    queries (credits, comments) rather than one join, since joining both
    many-to-one tables in a single query would multiply rows and require a
    DISTINCT-count correction — simpler and just as fast at this data
    volume to run them separately and merge in Python."""
    if not video_ids:
        return {}
    out: dict[str, dict] = {vid: {"credits": 0, "comments": 0} for vid in video_ids}
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT video_id, COUNT(*) FROM video_credits WHERE video_id = ANY(%s) GROUP BY video_id",
                (video_ids,),
            )
            for vid, count in cur.fetchall():
                out[vid]["credits"] = count

            cur.execute(
                "SELECT video_id, COUNT(*) FROM comments WHERE video_id = ANY(%s) GROUP BY video_id",
                (video_ids,),
            )
            for vid, count in cur.fetchall():
                out[vid]["comments"] = count
    return out


# ── Follows ───────────────────────────────────────────────────────────────────

def follow_user(follower_id: str, following_id: str) -> None:
    sql = """
        INSERT INTO follows (follower_id, following_id)
        VALUES (%s::uuid, %s::uuid)
        ON CONFLICT DO NOTHING
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (follower_id, following_id))


def unfollow_user(follower_id: str, following_id: str) -> None:
    sql = "DELETE FROM follows WHERE follower_id = %s::uuid AND following_id = %s::uuid"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (follower_id, following_id))


def is_following(follower_id: str, following_id: str) -> bool:
    sql = "SELECT 1 FROM follows WHERE follower_id = %s::uuid AND following_id = %s::uuid"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (follower_id, following_id))
            return cur.fetchone() is not None


def get_creator_profile(creator_id: str, viewer_id: Optional[str] = None) -> Optional[dict]:
    """Return creator public profile with follower count, credit total, and
    follow status. 'credits' is the LIVE sum of video_credits across all of
    this creator's videos, not the frozen u.credits column — see
    toggle_video_credit's module comment for why u.credits is no longer
    written to (an unverifiable historical counter, not a real per-user
    record) and must not be read as if it still reflects current totals."""
    sql = """
        SELECT u.id, u.name, u.department, u.account_type, u.created_at,
               COUNT(DISTINCT f.follower_id) AS follower_count,
               COUNT(DISTINCT v.id) AS video_count,
               COUNT(DISTINCT (vc.video_id, vc.user_id)) AS credits
        FROM users u
        LEFT JOIN follows f ON f.following_id = u.id
        LEFT JOIN videos v ON v.user_id::uuid = u.id AND v.overall_status IN ('approved','flagged')
        LEFT JOIN video_credits vc ON vc.video_id = v.id
        WHERE u.id = %s::uuid
        GROUP BY u.id
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (creator_id,))
            row = cur.fetchone()
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["is_following"] = is_following(viewer_id, creator_id) if viewer_id else False
    return d


# ── Search ────────────────────────────────────────────────────────────────────

def search(query: str) -> dict:
    """Search creators by name/department and videos by filename."""
    like = f"%{query}%"

    creator_sql = """
        SELECT u.id, u.name, u.department, u.account_type,
               (SELECT COUNT(*) FROM follows WHERE following_id = u.id) AS follower_count,
               (SELECT COUNT(*) FROM video_credits vc
                JOIN videos v ON v.id = vc.video_id
                WHERE v.user_id::uuid = u.id) AS credits
        FROM users u
        WHERE (name ILIKE %s OR department ILIKE %s) AND account_type = 'creator'
        LIMIT 10
    """
    video_sql = """
        SELECT v.id, v.filename, v.overall_status, v.created_at,
               u.name AS creator_name, u.department AS creator_department
        FROM videos v
        LEFT JOIN users u ON v.user_id::uuid = u.id
        WHERE v.filename ILIKE %s AND v.overall_status IN ('approved','flagged')
        LIMIT 10
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(creator_sql, (like, like))
            creators = [dict(r) for r in cur.fetchall()]
            cur.execute(video_sql, (like,))
            videos = [dict(r) for r in cur.fetchall()]

    for c in creators:
        c["id"] = str(c["id"])
    for v in videos:
        v["id"] = str(v["id"])
    return {"creators": creators, "videos": videos}


def search_users(query: str) -> list:
    """Search all users (any account_type) by name. Used by the messaging 'find people' flow."""
    like = f"%{query}%"

    sql = """
        SELECT id, name, account_type
        FROM users
        WHERE name ILIKE %s
        LIMIT 10
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (like,))
            users = [dict(r) for r in cur.fetchall()]

    for u in users:
        u["id"] = str(u["id"])
    return users


def search_users_by_ids(ids: list[str]) -> list:
    """Batch-resolve user IDs to {id, name, account_type}. Missing IDs are silently omitted."""
    sql = """
        SELECT id, name, account_type
        FROM users
        WHERE id::text = ANY(%s)
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (ids,))
            users = [dict(r) for r in cur.fetchall()]

    for u in users:
        u["id"] = str(u["id"])
    return users


# ── Comments ──────────────────────────────────────────────────────────────────

def add_comment(video_id: str, body: str, user_id: Optional[str] = None) -> dict:
    """Insert a comment and return it with author name."""
    sql = """
        INSERT INTO comments (video_id, user_id, body)
        VALUES (%s, %s::uuid, %s)
        RETURNING id, video_id, user_id, body, created_at
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (video_id, user_id, body))
            row = dict(cur.fetchone())
    row["id"] = str(row["id"])
    row["user_id"] = str(row["user_id"]) if row["user_id"] else None
    return row


def get_comments(video_id: str, limit: int = 50) -> list[dict]:
    """Return comments for a video, newest first, with author name."""
    sql = """
        SELECT c.id, c.body, c.created_at,
               u.name AS author_name
        FROM comments c
        LEFT JOIN users u ON c.user_id = u.id
        WHERE c.video_id = %s
        ORDER BY c.created_at ASC
        LIMIT %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (video_id, limit))
            rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        result.append(d)
    return result


# ── Houses ────────────────────────────────────────────────────────────────────
# Built-in Houses (one per department) have no table — they're derived from
# users.department at query time (KTD1). Only custom Houses are real rows here.

def create_house(house_id: str, owner_id: str, name: str, description: Optional[str]) -> dict:
    """Insert a new custom House. house_id is generated by the caller (main.py),
    matching create_job's id-generation pattern (a UUID string, not DB-generated)."""
    sql = """
        INSERT INTO houses (id, owner_id, name, description)
        VALUES (%s, %s::uuid, %s, %s)
        RETURNING id, owner_id, name, description, created_at
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (house_id, owner_id, name, description))
            row = dict(cur.fetchone())
    row["owner_id"] = str(row["owner_id"])
    return row


def get_house(house_id: str) -> Optional[dict]:
    """Return a single custom House row, or None if it doesn't exist.
    Used by _require_house_owner (404 if None) and by ownership checks."""
    sql = "SELECT id, owner_id, name, description, created_at FROM houses WHERE id = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (house_id,))
            row = cur.fetchone()
    if not row:
        return None
    d = dict(row)
    d["owner_id"] = str(d["owner_id"])
    return d


def delete_house(house_id: str) -> None:
    """Delete a House. Membership rows cascade via ON DELETE CASCADE."""
    sql = "DELETE FROM houses WHERE id = %s"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (house_id,))


def list_custom_houses() -> list[dict]:
    """Return every custom House with a creator-member count and video-member
    count for display on the Houses listing card."""
    sql = """
        SELECT h.id, h.owner_id, h.name, h.description, h.created_at,
               COUNT(DISTINCT hcm.creator_id) AS creator_count,
               COUNT(DISTINCT hvm.video_id) AS video_count
        FROM houses h
        LEFT JOIN house_creator_members hcm ON hcm.house_id = h.id
        LEFT JOIN house_video_members hvm ON hvm.house_id = h.id
        GROUP BY h.id
        ORDER BY h.created_at DESC
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["owner_id"] = str(r["owner_id"])
    return rows


def add_house_creator_member(house_id: str, creator_id: str) -> None:
    """Idempotent add — matches follow_user's INSERT ... ON CONFLICT DO NOTHING pattern."""
    sql = """
        INSERT INTO house_creator_members (house_id, creator_id)
        VALUES (%s, %s::uuid)
        ON CONFLICT DO NOTHING
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (house_id, creator_id))


def remove_house_creator_member(house_id: str, creator_id: str) -> None:
    """Matches unfollow_user's plain DELETE WHERE pattern — no error if absent."""
    sql = "DELETE FROM house_creator_members WHERE house_id = %s AND creator_id = %s::uuid"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (house_id, creator_id))


def add_house_video_member(house_id: str, video_id: str) -> None:
    """Idempotent add. No ownership check on the video's creator — cross-creator
    video curation is intentional (KTD2a), enforced (as a non-check) at the
    main.py route level, not here."""
    sql = """
        INSERT INTO house_video_members (house_id, video_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (house_id, video_id))


def remove_house_video_member(house_id: str, video_id: str) -> None:
    sql = "DELETE FROM house_video_members WHERE house_id = %s AND video_id = %s"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (house_id, video_id))


def get_house_feed(house_id: str) -> list[dict]:
    """Return a custom House's unioned creator+video membership feed, newest
    first. A single SELECT with an OR'd WHERE over one base table (videos) —
    no DISTINCT needed, since one SELECT over one table cannot return the same
    v.id row twice no matter how many OR-branches it satisfies (KTD4/U2 design).

    Both v.user_id::uuid casts are required: v.user_id is TEXT (ALTER TABLE
    migration), while u.id and house_creator_members.creator_id are UUID —
    same cast pattern already used in get_feed/get_creator_profile/search/toggle_video_credit.
    """
    sql = """
        SELECT v.*, u.name AS creator_name, u.department AS creator_department
        FROM videos v
        JOIN users u ON v.user_id::uuid = u.id
        WHERE v.overall_status IN ('approved', 'flagged')
          AND (
            v.user_id::uuid IN (SELECT creator_id FROM house_creator_members WHERE house_id = %s)
            OR
            v.id IN (SELECT video_id FROM house_video_members WHERE house_id = %s)
          )
        ORDER BY v.created_at DESC
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (house_id, house_id))
            rows = [dict(r) for r in cur.fetchall()]
    result = []
    for row in rows:
        d = dict(row)
        d["_id"] = d.pop("id")
        result.append(d)
    return result


def get_department_house_feed(department_name: str) -> list[dict]:
    """Return every approved/flagged video TAGGED into department_name, newest
    first (built-in House). Membership now comes from video_department_tags
    (primary or additional tag, no distinction at read time — see design doc's
    Feed Display section) rather than solely from the creator's own
    users.department. This is a deliberate behavior change from the
    creator-department-only query this replaced: a video surfaces here if it
    carries ANY tag matching this department, not only if its creator's home
    department does.

    The ::uuid cast on the v.user_id join is required, not optional:
    videos.user_id is TEXT while users.id is UUID — omitting it raises
    'operator does not exist: text = uuid' at query time. Mirrors get_feed's
    identical cast.
    """
    sql = """
        SELECT v.*, u.name AS creator_name, u.department AS creator_department
        FROM videos v
        JOIN users u ON v.user_id::uuid = u.id
        WHERE v.overall_status IN ('approved', 'flagged')
          AND EXISTS (
            SELECT 1 FROM video_department_tags t
            WHERE t.video_id = v.id AND t.department = %s
          )
        ORDER BY v.created_at DESC
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (department_name,))
            rows = [dict(r) for r in cur.fetchall()]
    result = []
    for row in rows:
        d = dict(row)
        d["_id"] = d.pop("id")
        result.append(d)
    return result
