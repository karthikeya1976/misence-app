# Architecture — Misence

## System Diagram

```
[Next.js Frontend — Vercel HTTPS]
        │
        │  /api/backend/* (same-origin rewrite)
        ▼
[Vercel Edge — next.config.ts rewrite]
        │
        │  HTTPS proxy → redactor-api.duckdns.org
        ▼
[Nginx reverse proxy — EC2]
        │  TLS termination (Let's Encrypt via DuckDNS)
        ▼
[FastAPI Gateway — EC2 :8088]
  ├── Auth endpoints (/auth/*)
  ├── Upload: save to S3 → instant ack {task_id}
  ├── Social endpoints (/feed, /search, /creators/*)
  └── Comment + credit endpoints
        │
        │  Redis queue (Celery)
        ▼
[ElastiCache Redis]
        │
        ▼
[Celery Worker — EC2]
   │         │           │            │
   ▼         ▼           ▼            ▼
Adult     AI/Deepfake  Duplicate   Filmmaking
Content   (Sightengine) Content    Relevance
(Sightengine)         (SHA-256    (AWS Rekognition)
                       S3 hash)
   └─────────┴───────────┴────────────┘
                         │
                  [Decision Engine]
               approved / flagged / blocked
                         │
                         ▼
              [RDS PostgreSQL 15 — AWS]
         (videos, users, follows, comments tables)
                         │
                         ▼
             [FastAPI GET /feed, /search, etc.]
                         │
                         ▼
         [Next.js — swipeable reel feed + social UI]
```

---

## Components

### Same-Origin Proxy (`frontend/next.config.ts`)
Rewrites all `/api/backend/*` requests to `https://redactor-api.duckdns.org/*`
at the Vercel edge. The browser always calls its own origin (same-origin, no
mixed-content blocks, no CORS preflight). Locally, the rewrite targets
`http://localhost:8088` so no env var is needed in either environment.

### FastAPI Gateway (`backend/app/main.py`)

**Auth**
- `POST /auth/register` — create account (`viewer` by default)
- `POST /auth/login` — returns a JWT (HS256, `sub` = user id) that now carries a real 24h `exp` claim — every token issued before this fix never expired at all. `JWT_SECRET` has no hardcoded fallback: the app raises `RuntimeError` at import time if it's unset, matching `config.py`'s `POSTGRES_URL` pattern.
- `POST /auth/upgrade` — viewer → creator (requires JWT + department)

**Videos**
- `POST /videos` — Creator JWT required; saves file to S3, creates DB row, enqueues Celery task, returns `{task_id, status: "processing"}` instantly
- `GET /videos/{job_id}/status` — returns full job row including pillar results
- `GET /videos` — list all jobs (admin/debug use)

**Feed & Discovery**
- `GET /feed?token=<jwt>` — returns `{enrouted: Job[], recommended: Job[]}`. Enrouted = approved videos from followed creators, purely chronological. Recommended = all other approved videos ranked by a weighted engagement score (credits + comments + recency decay — see `## Feed Algorithm`). Both buckets exclude any video the viewer has dismissed ("not interested") and include presigned S3 URLs plus per-video engagement counts for streaming/display.
- `POST /videos/{job_id}/credit` — JWT required; toggles this viewer's own credit on the video (credit once, tap again to un-credit). Per-user, deduplicated.
- `POST /videos/{job_id}/dismiss` — JWT required; "not interested" — hides this video from the caller's own feed going forward.
- `GET /search?q=<query>` — ILIKE search over creator names/departments and video filenames; returns `{creators, videos}`
- `GET /creators/{id}?token=<jwt>` — creator profile with follower count, video count, credit total, and `is_following` for the viewer

**Social**
- `POST /creators/{id}/follow` — JWT required; inserts into `follows` table
- `DELETE /creators/{id}/follow` — JWT required; removes follow
- `POST /videos/{job_id}/credit` — increments `users.credits` for the video's creator
- `GET /videos/{job_id}/comments` — list comments newest-first
- `POST /videos/{job_id}/comments?token=<jwt>` — insert comment with optional author attribution

**Houses** — built-in (one per department, derived, no table) + custom (owned, curated). See `## Houses` below for the full model.
- `GET /houses` — `{builtIn: [{name}], custom: House[]}`. `builtIn` is the hardcoded `DEPARTMENTS` list; `custom` is every `houses` row with creator/video member counts.
- `POST /houses` — Creator JWT required; creates a custom House owned by the caller
- `DELETE /houses/{house_id}` — House owner JWT required
- `GET /houses/department/{name}/feed` — built-in House feed: `{videos: Job[]}`, every approved/flagged video from creators whose `department` exactly matches `name`
- `GET /houses/{house_id}/feed` — custom House feed: `{videos: Job[]}`, unioned creator-membership + video-membership, deduped by construction (single `SELECT`, no `DISTINCT` needed)
- `POST /houses/{house_id}/members/creators/{creator_id}` / `DELETE` — House owner JWT required; add/remove a creator's whole catalog from the House
- `POST /houses/{house_id}/members/videos/{video_id}` / `DELETE` — House owner JWT required; add/remove one video, **regardless of who created it** (no ownership check on the video — cross-creator curation is intentional, matching `follow_user()`'s no-consent posture)

### Storage (`backend/app/storage.py`)
- `save_video(object_name, src_path)` — uploads file to S3 bucket `amzn-s3-bucket-dvm` (us-east-2)
- `get_presigned_url(object_name)` — generates a time-limited S3 URL for streaming
- `cleanup_video(object_name)` — deletes the S3 object after processing (frames are cleaned up separately)

On EC2 with an IAM instance profile, boto3 uses the instance role automatically. No hardcoded credentials needed.

### Database (`backend/app/db.py`)

```sql
-- Core moderation table
videos (
  id             TEXT PRIMARY KEY,   -- UUID, same as Celery task_id
  filename       TEXT,
  file_path      TEXT,               -- s3://bucket/object
  status         TEXT,               -- pending | processing | done
  overall_status TEXT,               -- approved | flagged | blocked | needs_review (moderation failed; hidden)
  pillar_results JSONB,
  reasons        JSONB,
  size_bytes     INTEGER,
  user_id        UUID REFERENCES users(id),
  file_hash      TEXT,               -- SHA-256 for duplicate detection
  phash          TEXT,               -- 5 x 64-bit dHash frames (80 hex chars) for near-duplicate detection
  created_at     TIMESTAMPTZ,
  updated_at     TIMESTAMPTZ
)

-- Auth / social graph
users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT,
  email         TEXT UNIQUE,
  password_hash TEXT,
  account_type  TEXT,    -- viewer | creator
  department    TEXT,    -- e.g. "Cinematography"
  credits       INTEGER DEFAULT 0,
  created_at    TIMESTAMPTZ
)

-- Follow graph (Enroute/Deroute)
follows (
  follower_id  UUID REFERENCES users(id),
  following_id UUID REFERENCES users(id),
  created_at   TIMESTAMPTZ,
  PRIMARY KEY (follower_id, following_id)
)

-- Comments
comments (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id   TEXT REFERENCES videos(id),
  user_id    UUID REFERENCES users(id),
  body       TEXT,
  created_at TIMESTAMPTZ
)

-- Custom Houses (curated video collections; built-in department Houses
-- are derived from users.department at query time and have no table)
houses (
  id          TEXT PRIMARY KEY,
  owner_id    UUID REFERENCES users(id),
  name        TEXT,
  description TEXT,
  created_at  TIMESTAMPTZ
)

-- House membership: whole creator catalogs (present + future uploads)
house_creator_members (
  house_id   TEXT REFERENCES houses(id),
  creator_id UUID REFERENCES users(id),
  added_at   TIMESTAMPTZ,
  PRIMARY KEY (house_id, creator_id)
)

-- House membership: individually curated videos, independent of creator
house_video_members (
  house_id   TEXT REFERENCES houses(id),
  video_id   TEXT REFERENCES videos(id),
  added_at   TIMESTAMPTZ,
  PRIMARY KEY (house_id, video_id)
)

-- Multi-department content tagging: one row per (video, department) pairing.
-- Drives built-in department House membership (see ## Houses) — a video
-- surfaces in a department's feed because it has a tag row here, not because
-- its creator's own users.department matches.
video_department_tags (
  video_id   TEXT REFERENCES videos(id) ON DELETE CASCADE,
  department TEXT,
  is_primary BOOLEAN DEFAULT FALSE,  -- exactly one TRUE row per video, DB-enforced
  tagged_at  TIMESTAMPTZ,
  PRIMARY KEY (video_id, department)
)
-- Partial unique index (not shown above): idx_video_dept_tags_one_primary
-- ON video_department_tags (video_id) WHERE is_primary — makes a second
-- primary row for the same video impossible to insert, even outside the app.

-- Per-user, per-video credit toggle — replaces the old unauthenticated,
-- undeduplicated users.credits-only counter. users.credits itself is left
-- as a frozen historical total; get_creator_profile/search compute a LIVE
-- sum from this table instead.
video_credits (
  video_id   TEXT REFERENCES videos(id) ON DELETE CASCADE,
  user_id    UUID REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ,
  PRIMARY KEY (video_id, user_id)
)

-- "Not interested" — per-viewer video dismissal, excluded from both feed
-- buckets in get_feed via a NOT EXISTS anti-join.
dismissed_videos (
  user_id    UUID REFERENCES users(id) ON DELETE CASCADE,
  video_id   TEXT REFERENCES videos(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ,
  PRIMARY KEY (user_id, video_id)
)
```

`_ensure_schema()` runs on every API startup — all `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` are idempotent.

### Task Queue (`backend/app/tasks.py`)
- `process_video(task_id)` Celery task:
  1. Emits the `QueueDepth` metric, sets `status = "processing"` in DB
  2. Runs all four pillar checks concurrently — each pillar's blocking I/O (S3, OpenCV, HTTP, Postgres) runs in a worker thread via `asyncio.to_thread`, gathered with `asyncio.gather`; each pillar downloads the object and extracts its own frames
  3. Any pillar raising `PillarError` fails the attempt; Celery retries with exponential backoff + jitter (2 s base, 60 s cap, max 3 retries)
  4. Passes results to Decision Engine
  5. Writes final `pillar_results`, `overall_status`, `reasons` to DB; sets `status = "done"`; emits `VerdictLatencySeconds`
  6. If retries are exhausted (`ModerationTask.on_failure`): `status = "failed"`, `overall_status = "needs_review"` (outside the `approved`/`flagged` feed filter, so hidden), job pushed to the Redis dead-letter list `dlq:process_video`, `DeadLetterDepth` emitted. Inspect / replay with `scripts/replay_dlq.py`.

### Moderation Pillars (`backend/app/pillars/`)

Each pillar exposes the same interface:
```python
async def check(job_id: str) -> dict
# → {"pillar": str, "score": float (0–1), "flags": [...]}
```

| File | API | What it checks |
|------|-----|----------------|
| `adult_content.py` | Sightengine nudity-2.1 | Explicit / suggestive imagery |
| `ai_deepfake.py` | Sightengine genai | AI-generated / synthetic video |
| `duplicate_content.py` | SHA-256 of S3 object + dHash of 5 frames (`phash.py`) | Identical (blocked) or visually near-identical (flagged) file already on platform |
| `filmmaking_relevance.py` | AWS Rekognition DetectLabels | Scene labels match filmmaking vocabulary |

Pillars are swappable: replacing a mock with a real API client means editing one file, not the orchestration code. Each module keeps its blocking body in `_check_blocking()` and exposes `check()` as the `asyncio.to_thread` wrapper. Mock scores exist only for local dev without credentials; real-backend errors raise `PillarError`.

### Decision Engine (`backend/app/decision_engine.py`)
Reads all four pillar results, applies thresholds from `docs/moderation_policies.md`:
- Any pillar above its `block` threshold → `blocked`
- Any pillar above its `flag` threshold (or `filmmaking_relevance` below 0.3) → `flagged`
- Otherwise → `approved`

Returns `{overall_status, reasons}` written back to the DB row.

### Frontend (`frontend/`)

**Pages**

| Route | File | Description |
|-------|------|-------------|
| `/` | `app/page.tsx` | Login / register with JWT storage |
| `/feed` | `app/feed/page.tsx` | Horizontal-swipe reel feed — drag/flick left-right or ← → keys; long-press (3s) opens a thumbnail strip to jump directly to any video |
| `/upload` | `app/upload/page.tsx` | Scene (16:9) or Shot (9:16) upload with format toggle |
| `/profile` | `app/profile/page.tsx` | Account info, creator upgrade, settings, logout |
| `/search` | `app/search/page.tsx` | Debounced creator + video search |
| `/creators/[id]` | `app/creators/[id]/page.tsx` | Creator profile with stats and Enroute/Deroute |
| `/settings/privacy` | `app/settings/privacy/page.tsx` | Blocked users list — unblock removes a person from the list without restoring any prior conversation |
| `/messages/conversations` | `app/messages/conversations/page.tsx` | Default landing page for the messenger — accepted chat threads |
| `/messages/requests` | `app/messages/requests/page.tsx` | Incoming chat requests awaiting accept/decline, including abusive-first-message banners in place of the decrypted text |
| `/messages/compose` | `app/messages/compose/page.tsx` | Person search + new-chat compose flow, reached via the Conversations page's "New message" button or a creator profile's Message button |
| `/messages/conversations/[conversationId]` | `app/messages/conversations/[conversationId]/page.tsx` | Thread view — per-message timestamps, day separators, and Copy/Reply/Report (received) or Edit/Reply/Copy (sent) action menus |
| `/houses` | `app/houses/page.tsx` | Houses listing — "Departments" (built-in, derived from `DEPARTMENTS`) and "Custom Houses" (owned, curated) sections; tapping a card navigates into the House-scoped feed. Creators see a "Create a House" affordance with an inline name/description form that posts to `createHouse()` and navigates straight to the new House's manage view |
| `/houses/[id]` | `app/houses/[id]/page.tsx` | Thin owner/non-owner branch for a custom House (KTD7) — a non-owner is `router.replace`'d straight to `/feed?house=<id>` with no intermediate screen; the owner sees a "View feed" link plus a real Manage Members section (U5): Creators and Videos sub-sections, each with debounced search-as-you-type against the global `search()` endpoint (video search is cross-creator by design, KTD2a) and per-row remove, wired to U2's add/remove-member endpoints. Member lists are session-local — there is no "list current members" endpoint, only counts (`GET /houses`) and an undifferentiated unioned feed (`GET /houses/{id}/feed`) |

`/messages` itself redirects to `/messages/conversations` — there is no longer a standalone tab bar switching between New Message / Requests / Conversations views (removed in favor of landing directly on Conversations, with Requests reachable via a link and a pending-count badge).

**Shared components**
- `components/nav-bar.tsx` — collapsible sidebar: "M" monogram collapsed, "Misence" expanded; Home, Search, Houses, Messages (badge dot for pending requests/unread), Upload (creator only), Profile (pinned bottom). The Messages link routes to `/messages/requests` while the badge is visible, `/messages/conversations` otherwise — scoped only to the Messages item, since a past regression once let this fallback apply to every nav item's `href`. The Houses entry is a plain link (no `creatorOnly`, no badge) — visible to every logged-in user.
- `components/MessageActionMenu.tsx`, `components/DaySeparator.tsx`, `components/OffensiveBanner.tsx` — thread-view building blocks for U5/U6/U7 of the messenger channel fixes (see Feed Gestures and the changelog for the full list)
- `components/ThumbnailStrip.tsx`, `components/VideoThumbnail.tsx` — the feed's long-press jump-to-video picker (see Feed Gestures below)

**Libraries**
- `lib/api.ts` — typed wrapper for every backend endpoint; all calls use `/api/backend` prefix (same-origin proxy)
- `lib/auth.ts` — localStorage JWT helpers: `getToken`, `setAuth`, `clearAuth`, `isLoggedIn`, `isCreator`

---

## Feed Algorithm

```
GET /feed?token=<jwt>

1. Decode token → viewer_id (optional)
2. If viewer_id:
   enrouted = SELECT videos JOIN follows
              WHERE follower_id = viewer_id
                AND NOT dismissed by viewer_id
              ORDER BY created_at DESC   ← purely chronological, NOT ranked
3. recommended = SELECT videos
                 WHERE id NOT IN (enrouted_ids)
                   AND NOT dismissed by viewer_id
                 ORDER BY ranking_score DESC, created_at DESC
4. Return {enrouted, recommended}
   (both contain presigned S3 video_url, credited/credit_count/comment_count)

Frontend merges with section dividers:
  [Following]     ← enrouted bucket (if non-empty)
  video, video, …
  [Recommended]   ← recommended bucket (if non-empty)
  video, video, …
```

**Ranking score (`recommended` bucket only)** — a right-sized version of a
general feed/recommendation design doc's "weighted combination, not a single
signal" principle: no ML model, no candidate-generation funnel (this app's
scale doesn't call for either), just an explainable SQL formula Postgres
sorts directly:

```
ranking_score = 3 * credit_count
              + 2 * comment_count
              + 1 * 0.5 ^ (age_hours / 48)     ← exponential recency decay,
                                                   48h half-life (same family
                                                   as Reddit/HN-style ranking)
```

`credit_count`/`comment_count` are NOT decayed by age — an old video still
earning fresh engagement can still rank, which is the point: the OLD sort
(`users.credits DESC` — a creator's lifetime total) meant a popular
creator's oldest, most-forgotten video always outranked a brand-new great
video from anyone else, since it ranked the CREATOR, not the video. The
`enrouted` bucket deliberately does **not** use this score — a follow means
"show me everything from this creator," so re-ranking it by engagement
would bury a brand-new post behind an old popular one from the same person.

**House-scoped feeds diverge from this shape** — `GET /houses/{house_id}/feed` and
`GET /houses/department/{name}/feed` return a flat `{videos: Job[]}`, not the
`{enrouted, recommended}` bucket split (KTD4): a House isn't something you
follow/don't-follow, so the enrouted/recommended distinction doesn't apply
inside one. Both feeds are ordered by `created_at DESC` only, and the
frontend renders at most one section-label divider (the House/department
name) instead of the Following/Recommended two-divider pattern. Both House
feed routes run their rows through the same `_enrich()` transform `GET
/feed` uses (job_id/pillars/presigned video_url) — see `## Houses` below.

**Frontend wiring (U5):** `frontend/app/feed/page.tsx`'s default export is a
thin `<Suspense fallback={null}><FeedPageInner /></Suspense>` shell (required
by `useSearchParams()`, matching `app/messages/compose/page.tsx`'s existing
pattern). `FeedPageInner`'s mount effect reads the `house` search param via
`parseHouseParam` (`frontend/lib/houses.ts`, U3) and branches: `null` → the
default `getFeed()` path, unchanged; otherwise → `getDepartmentHouseFeed()`
or `getHouseFeed()` (plus a parallel `listHouses()` call to resolve a custom
House's real name/owner, since no single-House GET endpoint exists). Because
a House-scoped `items` list always starts with its one section-label divider
at index 0, the existing divider-auto-skip (`setTimeout(goNext, 600)`) now
fires unconditionally on every House-feed load — a brief ~600ms flash before
the first video settles in. This is a known, accepted side effect, not a
bug. The House-scoped empty state also has its own copy, distinct per
owner/non-owner — see `docs/changelog.md`'s 2026-09-23 entry for the exact
variants.

---

## Houses

Two kinds of House, one browsing surface (the existing swipe feed, scoped):

- **Built-in Houses** — one per department. No table: `GET
  /houses/department/{name}/feed` derives membership live via `SELECT ...
  FROM videos WHERE EXISTS (SELECT 1 FROM video_department_tags WHERE
  video_id = videos.id AND department = :name) AND videos.overall_status IN
  ('approved','flagged')` — membership is tag-based (`video_department_tags`,
  see Multi-Department Content Tagging below), not derived from the
  creator's own `users.department` (that was the original design; superseded
  once a video could carry tags independent of its creator's home
  department). The department list (`DEPARTMENTS`) is duplicated
  backend-side in `main.py` from `frontend/app/profile/page.tsx`'s constant
  of the same name (and a third synced copy in `app/upload/page.tsx`) — all
  copies are short and human-maintained, kept in sync by hand. **`POST
  /auth/upgrade` validates `department` against this list (400 if no exact
  match)** — closes a gap where an unvalidated `department` string would
  otherwise leave a creator silently invisible to their own built-in House
  (a case/whitespace/typo mismatch just returns zero rows, with no error
  anywhere in the pipeline).
- **Custom Houses** — an owned, curated entity (`houses` table). The owner
  adds specific creators (`house_creator_members` — that creator's whole
  catalog, present and future) and/or specific individual videos
  (`house_video_members` — independent of who made them; **no ownership
  check on the video's creator**, cross-creator curation is intentional,
  matching `follow_user()`'s existing no-consent-required posture). A video
  that qualifies via both creator-membership and individual video-membership
  appears exactly once in the feed — one `SELECT` with an `OR`'d `WHERE`
  over the `videos` table cannot itself return the same row twice, so no
  `DISTINCT` is needed. Public by default, no private/visibility flag
  (KTD6); only the owner can edit membership or delete the House
  (`_require_house_owner` in `main.py` — this codebase's first
  resource-ownership check, decode-token → fetch-house → 404-if-missing →
  403-if-not-owner, mirroring `_require_creator`'s shape).

Membership rows have no `overall_status` gate at write time, only at
feed-read time — an owner can add a not-yet-approved video/creator; it
simply won't render until (if ever) approved, per the feed queries' existing
`overall_status` filter.

---

## Multi-Department Content Tagging

A video's department is no longer solely inherited from its creator. At
upload time, `POST /videos` writes one **primary** tag (always the
uploader's current `users.department`, server-derived — never
client-supplied, regardless of what the request sends) plus zero-to-`MAX_ADDITIONAL_DEPARTMENTS`
(5) **additional** tags the creator explicitly selects, all into
`video_department_tags`. A video appears in every tagged department's
built-in House feed identically — no primary/additional distinction at feed
read time, only in the tag's own `is_primary` flag.

- **The primary tag can never be removed** — enforced by never exposing the
  operation, not by rejecting it after the fact. `POST /videos/{id}/departments`
  / `DELETE /videos/{id}/departments/{department}` (owner-only,
  `_require_video_owner`) only ever add/remove additional tags. A second,
  independent layer of defense lives in `db.py`:
  `remove_video_department_tag` silently no-ops if the target row
  `is_primary`, so the guarantee holds even against a direct DB-layer call
  that bypasses the route entirely.
- **Exactly one primary tag per video is a database constraint**, not
  application discipline: a partial unique index
  (`idx_video_dept_tags_one_primary ON video_department_tags (video_id)
  WHERE is_primary`) makes a second primary row structurally impossible to
  insert.
- **The primary tag is frozen at upload time** — it does not live-track a
  creator's `users.department` if they change it later. Existing videos'
  primary tags are untouched by a subsequent department change.
- **Backfill for pre-existing videos**: every video uploaded before this
  feature shipped has zero tag rows. Since the department-feed query has no
  fallback to `users.department` (see `## Houses` above), an idempotent
  backfill in `_ensure_schema()` gives every untagged video a primary tag
  from its creator's *current* department, `WHERE NOT EXISTS` so it can
  never overwrite a tag set written after this feature shipped. Runs on
  every startup.
- **Validation**: additional departments are checked against the canonical
  `DEPARTMENTS` list (400 on any unknown value) and capped at
  `MAX_ADDITIONAL_DEPARTMENTS` (400 if exceeded) — same posture as
  `POST /auth/upgrade`'s existing department validation.

---

## Feed Gestures

The feed is a single-card, index-based interface (`current: number` into the
flat `items` array above) — only one `<video>` is ever mounted/playing at a
time. All gesture handling is hand-rolled on top of Pointer Events in
`SwipeCard` (`app/feed/page.tsx`); no gesture/animation/carousel library is
used. Tap, swipe, and long-press share one `onPointerDown` origin and are
disambiguated in `frontend/lib/gestureClassifier.ts` (pure, unit-tested
logic — `classifyPointerUp`, `shouldCancelLongPress`):

- **Tap** — pointer released with no meaningful movement → toggles pause.
- **Swipe** — horizontal drag past `SWIPE_THRESHOLD` (40px), with the
  horizontal delta dominant over the vertical one (an accidental vertical
  scroll attempt must not misfire as a swipe) → advances/retreats `current`.
- **Flick** — a fast short drag that never reaches `SWIPE_THRESHOLD` still
  swipes if its release velocity exceeds `FLICK_VELOCITY_THRESHOLD`
  (0.5px/ms), matching native carousel feel where speed matters as much as
  distance. Velocity is tracked live during `pointermove`, computed
  move-to-move rather than from the last move to `pointerup` — the pointer
  typically sits still for 15-40ms between the last move and the actual
  lift, and measuring over that trailing gap undercounts real flicks.
- **Long-press** — held below the movement tolerance for `LONG_PRESS_MS`
  (3000ms) → pauses the current video and opens `ThumbnailStrip`, a
  windowed horizontally-scrollable strip (own pool of `<video preload=
  "metadata" muted>` elements, never touching the main player's) for
  jumping directly to any video in the feed. Selecting a thumbnail calls
  `setCurrent` directly and closes the strip.
  **Discoverability cue (fixes #32):** a subtle pulsing ring overlay on the
  card, shown only for the first `LONG_PRESS_HINT_VIDEO_COUNT` (3) videos
  of a session, dismissed permanently for the session the moment the user
  actually triggers a long-press (`sessionStorage`-flagged, following the
  same session-gated idiom `lib/gatekept-api.ts`'s `ensureRegistered()`
  already uses). Static (no animation) under `prefers-reduced-motion`.

On release past the swipe/flick threshold, the card animates fully
off-screen (`COMMIT_MS`, 200ms) before the navigation callback fires; below
threshold, it eases back to center (`SNAP_BACK_MS`, 220ms) instead of
snapping instantly. Both mouse and touch are driven by the same Pointer
Events handlers, so this behavior is uniform across desktop and mobile.

**Nested interactive elements are excluded from gesture capture.**
`onPointerDown` checks `e.target.closest("button, a, [role='button']")`
before doing anything else — if the pointerdown originated on the card's own
right-side action buttons or the Enroute pill, the handler returns
immediately without calling `setPointerCapture()`. This was a real,
previously-undiscovered bug affecting every action button (Credits,
Comment, Share, Save, Not interested, Enroute): `setPointerCapture`, once
called on the card's root, redirects every subsequent pointer/mouse event —
including the eventual click — back to the capturing element regardless of
where the cursor actually is (per the Pointer Events spec), so a click that
visually landed on a button never reached it. Confirmed via raw
mouse-coordinate click tracing, not Playwright's locator `.click()` (which
doesn't reproduce the bug — it dispatches events differently).

---

## Infrastructure (AWS)

| Resource | Type | Detail |
|----------|------|--------|
| EC2 | t3.small, Amazon Linux 2023 | API + Celery worker; public IP 18.216.199.64 |
| RDS | PostgreSQL 15, db.t3.micro | `redactor-db.c1qooqeoynjz.us-east-2.rds.amazonaws.com` |
| ElastiCache | Redis, cache.t3.micro | `redactor-redis.5v2cub.0001.use2.cache.amazonaws.com` |
| S3 | `amzn-s3-bucket-dvm` | us-east-2; videos + extracted frames |
| Nginx | EC2 | TLS termination; proxies :443 → :8088 |
| Let's Encrypt | DuckDNS `redactor-api.duckdns.org` | Auto-renewed HTTPS cert |
| Vercel | Next.js | `https://distributed-video-moderation.vercel.app` |

Defined in `infra/cloudformation.yml` (CloudFormation — not Terraform). EC2 systemd services: `redactor-api` and `redactor-celery`. **Caution**: the live instance was configured by hand and has no Elastic IP; a `UserData` change in the template marks the instance for conditional replacement, so never execute a stack update on `redactor-v2` without reviewing a change set.

**Observability**: when `CLOUDWATCH_NAMESPACE` is set (`Misence/Moderation` on EC2) the worker publishes `VerdictLatencySeconds` (dimension `Verdict`), `QueueDepth` and `DeadLetterDepth`. The instance role grants `cloudwatch:PutMetricData` restricted to that namespace.

**Containers**: `backend/Dockerfile` builds one image used for both roles (`uvicorn app.main:app` by default; override the command for `celery -A app.tasks worker`). `scripts/push_ecr.sh` builds and pushes it to ECR. The current deployment still runs the code directly under systemd, not the image.

---

## CI/CD Pipeline & Security Gate

`.github/workflows/pr-review-bot.yml` runs on every PR to `main`, five jobs:

```
lint-typecheck ──┬── artifact-scan ────┐
                  ├── regression-tests ─┼── decision (review_bot.py)
                  └── security-scan ────┘      │
                                                 auto-merge (squash) only if
                                                 ALL FOUR are exactly "success"
```

- **`lint-typecheck`** — frontend `npm run lint`/`npm run typecheck`, backend `py_compile` syntax check.
- **`artifact-scan`** — production `next build`, then `scripts/verify_artifacts.py` confirms the build output isn't corrupted/incomplete.
- **`regression-tests`** — runs `pytest tests/` and `vitest`, compares against `.ci/baseline-results.json` via `scripts/compare_baseline.py` (blocks only on NEW regressions vs. `main`, not pre-existing failures). Uses a `postgres:15-alpine` **service container** (GitHub Actions' native support) with `POSTGRES_URL`/`JWT_SECRET` set — without this, `test_houses.py`, `test_department_tags.py`, `test_feed_ranking.py`, and `test_auth_security.py` (92 of 112 local tests) silently `pytest.skip()` at collection, a real gap that existed from `test_houses.py`'s introduction until it was found and fixed alongside the security-scan job below.
- **`security-scan`** — Python SAST (`bandit`), Python dependency CVEs (`pip-audit`), JS dependency CVEs (`npm audit --audit-level=high`). `scripts/security_gate.py` aggregates all three tools' JSON output and blocks only on **new** findings at or above `--min-severity` (default `high`) not already in `.ci/security-baseline.json` — the same "new regressions only" philosophy `compare_baseline.py` already uses for tests, applied to security findings. `.ci/security-baseline.json` is a deliberately-reviewed acceptance record (finding id + written reason per entry, e.g. "interpolates a module-level constant, not user input" or "transitive dependency, no fix published yet") — never auto-generated, unlike the test baseline.
- **`decision`** — `scripts/review_bot.py`, unchanged logic (accepts arbitrary `name=status` check arguments) — auto-merges only if `lint-typecheck`, `artifact-scan`, `regression-tests`, AND `security-scan` are all exactly `"success"`.

`.github/workflows/update-baseline.yml` (push to `main`, non-blocking) refreshes `.ci/baseline-results.json` after every merge — this does **not** apply to `.ci/security-baseline.json`, which is hand-maintained only, since a security-acceptance record needs a human-reviewed reason per entry, not an automated snapshot.

**Not yet included**: `gitleaks` (content-based secret scanning across a diff, not just `scripts/scan-repo.py`'s existing tracked-filename pattern check) — needs a GitHub App/license setup, tracked as a real follow-up.

---

## Local Development Topology

```
Browser (localhost:3000)
  └── Next.js dev server
        └── /api/backend/* rewrite → http://localhost:8088
              └── FastAPI (uvicorn, port 8088)
                    ├── PostgreSQL (Docker, host port 5434)
                    └── Redis (Docker, host port 6380)
              └── Celery worker (pool=solo for Windows)
```

No `NEXT_PUBLIC_API_URL` env var needed — `next.config.ts` handles routing in both environments.
