# Misence

**A filmmaker discovery platform with AI-powered video moderation.**

Creators upload scenes and shots; the platform runs them through a distributed moderation pipeline (nudity detection, AI/deepfake detection, duplicate check, filmmaking relevance) before they appear in the public reel feed. Viewers follow creators, give credits, and discover new filmmaking work.

🌐 **Live**: https://distributed-video-moderation.vercel.app  
🔌 **API**: https://redactor-api.duckdns.org

---

## Architecture

```
[Next.js Frontend — Vercel]
        │  HTTPS (proxy: /api/backend/* → redactor-api.duckdns.org)
        ▼
[FastAPI Gateway — EC2 :8088 behind Nginx + Let's Encrypt]
        │  save to S3 → instant ack {task_id}
        ▼
[ElastiCache Redis]  ← task queue
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
              [RDS PostgreSQL — AWS]
                  videos, users, follows, comments
                         │
                         ▼
      [FastAPI social endpoints: /feed, /search, /creators]
                         │
                         ▼
      [Next.js — swipeable reel feed + creator profiles]
```

### Key design decisions
- **Same-origin proxy**: Next.js rewrites `/api/backend/*` → `https://redactor-api.duckdns.org/*` at the Vercel edge — eliminates mixed-content blocks with zero env-var config
- **Pillars are swappable**: each exposes `async def check(job_id) -> dict` — mock vs real API is one file change
- **S3 objects are kept** after processing so the feed streams via presigned URLs
- **Duplicate detection** uses SHA-256 (exact → blocked) plus a perceptual dHash of 5 frames (near-duplicate → flagged) — zero API cost
- **Pillars run concurrently and fail closed**: blocking I/O is moved off the event loop with `asyncio.to_thread`; a pillar error is retried (max 3, backoff), then the video is held as `needs_review` and dead-lettered rather than approved
- **Filmmaking relevance uses inverse scoring** — low score = off-topic = blocked
- **Smart feed**: enrouted (followed creators) content first, then recommendations ranked by creator credits + recency

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16, React 19, Tailwind CSS (light cream theme, peach accent) |
| API Gateway | FastAPI + Uvicorn |
| Task Queue | Celery + Redis (ElastiCache) |
| Storage | AWS S3 (video files + extracted frames) |
| Database | PostgreSQL 15 (RDS) — videos, users, follows, comments |
| Moderation | Sightengine (nudity + deepfake), AWS Rekognition (scene labels) |
| Infra | AWS EC2 t3.small, CloudFormation, Nginx, Let's Encrypt (DuckDNS) |
| Auth | JWT (`python-jose`), bcrypt (`passlib`) |

---

## Pages

| Route | Who | What |
|-------|-----|------|
| `/` | Anyone | Login / register |
| `/feed` | Logged-in | Horizontal-swipe reel feed — drag/flick left-right, tap to pause, long-press (3s) opens a jump-to-video thumbnail strip |
| `/upload` | Creators | Upload a Scene (16:9) or Shot (9:16) for moderation |
| `/profile` | Logged-in | Account card, creator upgrade, settings, logout |
| `/search` | Logged-in | Debounced search for creators and videos |
| `/creators/[id]` | Logged-in | Creator profile: stats, videos, Enroute/Deroute |
| `/settings/privacy` | Logged-in | Blocked users list |
| `/messages/conversations` | Logged-in | Messenger landing page — accepted chat threads |
| `/messages/requests` | Logged-in | Incoming chat requests, including abusive-first-message banners |
| `/messages/compose` | Logged-in | New chat: person search + compose |
| `/houses` | Logged-in | Houses listing — Departments (built-in) + Custom Houses (owned/curated); creators can create a new House |
| `/houses/[id]` | Logged-in | Custom House detail — non-owners are redirected straight to the House's feed; owners see a "View feed" link and a Manage Members section (search-and-add + per-row remove for both creators and videos) |

---

## Moderation Pillars

| Pillar | API | Threshold | Action |
|--------|-----|-----------|--------|
| `adult_content` | Sightengine nudity-2.1 | score ≥ 0.8 → blocked, ≥ 0.5 → flagged | Only explicit nudity |
| `ai_deepfake` | Sightengine genai | score ≥ 0.7 → flagged | AI-generated / synthetic media |
| `duplicate_content` | SHA-256 S3 hash + dHash of 5 frames | 1.0 → blocked, 0.85 → flagged | Same / visually near-identical file already on platform |
| `filmmaking_relevance` | AWS Rekognition DetectLabels | score < 0.3 → blocked | Off-topic content removed |

---

## API Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/health` | — | Liveness check |
| POST | `/auth/register` | — | Create account |
| POST | `/auth/login` | — | Get JWT token |
| POST | `/auth/upgrade` | JWT | Upgrade viewer → creator |
| POST | `/videos` | JWT (creator) | Upload video for moderation; optional `departments` form field (comma-separated additional department tags — primary tag is always server-derived from the uploader's department) |
| GET | `/videos/{job_id}/status` | — | Poll moderation result (includes `department_tags`) |
| POST | `/videos/{job_id}/departments` | JWT (owner) | Add one additional department tag (primary tag not reachable here) |
| DELETE | `/videos/{job_id}/departments/{department}` | JWT (owner) | Remove one additional department tag (no-op if targeting the primary) |
| GET | `/videos/{job_id}/comments` | — | List comments |
| POST | `/videos/{job_id}/comments` | JWT (query param) | Post a comment |
| POST | `/videos/{job_id}/credit` | JWT | Toggle this viewer's credit on a video (per-user, deduplicated) |
| POST | `/videos/{job_id}/dismiss` | JWT | "Not interested" — hide this video from the caller's own feed |
| GET | `/feed` | JWT optional | Smart feed `{enrouted, recommended}` — enrouted is chronological, recommended is ranked by a weighted engagement score |
| GET | `/search?q=` | — | Search creators + videos |
| GET | `/creators/{id}` | JWT optional | Creator profile + follow state |
| POST | `/creators/{id}/follow` | JWT | Enroute a creator |
| DELETE | `/creators/{id}/follow` | JWT | Deroute a creator |
| GET | `/houses` | — | List built-in (department) + custom Houses |
| POST | `/houses` | JWT (creator) | Create a custom House |
| DELETE | `/houses/{house_id}` | JWT (owner) | Delete a custom House |
| GET | `/houses/department/{name}/feed` | — | Built-in House feed (all creators in that department) |
| GET | `/houses/{house_id}/feed` | — | Custom House feed (member creators + member videos, unioned) |
| POST/DELETE | `/houses/{house_id}/members/creators/{creator_id}` | JWT (owner) | Add/remove a creator's whole catalog from a House |
| POST/DELETE | `/houses/{house_id}/members/videos/{video_id}` | JWT (owner) | Add/remove one video from a House (any video, regardless of creator) |

---

## Database Schema

```sql
users    (id UUID, name, email, password_hash, account_type, department, credits)
videos   (id TEXT, filename, file_path, status, overall_status,
          pillar_results JSONB, reasons JSONB, user_id, created_at, updated_at)
follows  (follower_id UUID, following_id UUID, created_at)  -- PK both columns
comments (id UUID, video_id TEXT, user_id UUID, body, created_at)

-- Houses: custom Houses are real rows; built-in (department) Houses have no
-- table — membership is derived from video_department_tags at query time.
houses                 (id TEXT, owner_id UUID, name, description, created_at)
house_creator_members  (house_id TEXT, creator_id UUID, added_at)  -- PK both columns
house_video_members    (house_id TEXT, video_id TEXT, added_at)    -- PK both columns

-- Multi-department content tagging: one row per (video, department).
-- Exactly one is_primary=TRUE row per video, DB-enforced via a partial
-- unique index (idx_video_dept_tags_one_primary ON video_id WHERE is_primary).
video_department_tags  (video_id TEXT, department, is_primary BOOLEAN, tagged_at)  -- PK (video_id, department)

-- Per-user, per-video credit toggle (replaces the old users.credits-only
-- counter, which is now a frozen historical total, no longer written to).
video_credits      (video_id TEXT, user_id UUID, created_at)  -- PK (video_id, user_id)
-- "Not interested" — per-viewer video dismissal, excluded from both feed buckets.
dismissed_videos   (user_id UUID, video_id TEXT, created_at)  -- PK (user_id, video_id)
```

---

## Local Development

### Prerequisites
Python 3.9+, Node.js 18+, Docker

### 1. Start local infrastructure
```bash
docker compose up -d   # Redis + PostgreSQL
```

### 2. Configure environment
```bash
cp .env.example .env
# Fill in: POSTGRES_URL, REDIS_URL, AWS_S3_BUCKET, AWS_S3_REGION,
#          AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
#          SIGHTENGINE_USER, SIGHTENGINE_SECRET, JWT_SECRET
```

### 3. Start the API
```bash
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8088 --reload
```

### 4. Start a Celery worker
```bash
cd backend
python -m celery -A app.tasks worker --loglevel=info --pool=solo
```

### 5. Start the frontend
```bash
cd frontend
npm install && npm run dev
# No env vars needed — next.config.ts proxies /api/backend/* to localhost:8088
```

Open **http://localhost:3000**

---

## Project Docs
- `docs/architecture.md` — system design and component breakdown
- `docs/moderation_policies.md` — per-pillar thresholds and aggregation rules
- `docs/project_status.md` — milestone tracker
- `docs/changelog.md` — implementation history
- `docs/project_spec.md` — original product specification and roadmap
