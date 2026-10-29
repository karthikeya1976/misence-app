# Project Status — Misence

## Phase 0: Environment Setup ✅
- [x] Python 3.11+ installed and verified (3.12.10)
- [x] Node.js / npm verified (v24.15.0 / 11.12.1)
- [x] Docker / docker compose verified
- [x] Project repo initialized with docs scaffold

## Milestone 1–3: Pipeline, Moderation, Dashboard ✅
- [x] FastAPI gateway with upload + status endpoints
- [x] Celery + Redis async task queue
- [x] Four moderation pillars (adult content, AI/deepfake, duplicate, filmmaking relevance)
- [x] Decision engine: approved / flagged / blocked
- [x] PostgreSQL for job persistence

## Milestone 4: v2 Architecture ✅
- [x] PostgreSQL replaces MongoDB; S3 replaces local disk
- [x] `decision_engine.py` (renamed from `aggregator.py`)
- [x] E2E tests updated and passing

## Redactor MVP (2026-09-08) ✅
- [x] JWT auth: register, login, upgrade viewer → creator
- [x] `users` table with `account_type`, `department`, `credits`
- [x] Creator-gated upload (`POST /videos` requires Creator JWT)
- [x] S3 video storage via boto3 + IAM instance profile
- [x] Real moderation APIs: Sightengine (nudity + deepfake), AWS Rekognition (filmmaking relevance)
- [x] SHA-256 duplicate detection pillar
- [x] Dark-theme frontend redesign (selenium blue, `#0a0a0f` bg)
- [x] Collapsible vertical sidebar

## AWS Deployment (2026-09-09) ✅
- [x] CloudFormation stack: VPC, subnets, IGW, security groups
- [x] RDS PostgreSQL 15 (db.t3.micro)
- [x] ElastiCache Redis (cache.t3.micro)
- [x] EC2 t3.small (Amazon Linux 2023)
- [x] Nginx + Let's Encrypt TLS via DuckDNS (`redactor-api.duckdns.org`)
- [x] Systemd services: `redactor-api` + `redactor-celery` (auto-restart)
- [x] Frontend deployed to Vercel (`https://distributed-video-moderation.vercel.app`)
- [x] End-to-end verified: register → login → upload → S3 → Celery → RDS → feed

## Editor Club — Social Features (2026-09-10) ✅

### Feed
- [x] Smart feed algorithm: `{enrouted, recommended}` buckets
  - Enrouted = videos from followed creators, ordered by recency
  - Recommended = all others, ordered by `creator.credits DESC, created_at DESC`
- [x] Section dividers in feed (`Following` / `Recommended`)
- [x] Swipe navigation: drag up/down on the reel card (mouse + touch); tap to pause
- [x] Arrow keys still work alongside swipe
- [x] S3 presigned URLs for in-browser video streaming

### Upload
- [x] Format toggle: **Scene** (landscape 16:9) vs **Shot** (portrait 9:16)
- [x] Drop zone shape matches selected format aspect ratio
- [x] Moderation result shown inline after upload (pillar score bars + reasons)

### Credits
- [x] `users.credits` integer column (incremented per-video by any viewer)
- [x] `POST /videos/{id}/credit` endpoint
- [x] Star button in feed with live count display

### Follow / Enroute
- [x] `follows` table: `(follower_id, following_id)` primary key
- [x] `POST /creators/{id}/follow` and `DELETE /creators/{id}/follow`
- [x] Enroute/Deroute button in feed overlay (creator info bar)
- [x] Enroute/Deroute button on creator profile page
- [x] Enroute/Deroute button in search results

### Comments
- [x] `comments` table: `(id, video_id, user_id, body, created_at)`
- [x] `GET /videos/{id}/comments` and `POST /videos/{id}/comments`
- [x] Comment drawer in feed: fetches on open, posts with author attribution
- [x] Author name + initials shown per comment

### Search
- [x] `GET /search?q=` — ILIKE across creator names, departments, video filenames
- [x] Debounced search (400ms) via `useEffect` + `useRef` timer
- [x] Error state (API unreachable), no-results state, animated loading dots
- [x] Clear button (×) in search input
- [x] Creator results: clickable name → profile, Enroute/Deroute button
- [x] Video results: filename, creator, moderation status chip

### Creator Profile
- [x] `/creators/[id]` page: avatar (initials), name, department, CREATOR chip
- [x] Stat tiles: follower count, video count, credits
- [x] Enroute/Deroute with optimistic update + revert on error
- [x] Back button

### NavBar / Branding
- [x] Logo: "EC" collapsed → "Editor Club" expanded (with home link)
- [x] Nav items: Home (`/feed`), Search (`/search`), Upload (`/upload`, creator only)
- [x] Profile pinned to bottom slot; logout only on `/profile`

### Bug Fixes
- [x] Same-origin proxy (`next.config.ts`) eliminates mixed-content HTTPS→HTTP block
- [x] `isDivider(undefined)` crash at Next.js build time fixed (null guard)
- [x] `videos.user_id::uuid` JOIN cast fixed (EC2 schema has UUID type, not TEXT)
- [x] `_CREATE_COMMENTS_TABLE` split into two separate `execute()` calls (psycopg2 single-statement limit)

### Repo Health Tooling
- [x] `scripts/scan-repo.py`: 6-check scanner (secrets, dead code, .env drift, stale docs, TODOs)
- [x] `.git/hooks/pre-commit`: auto-runs scanner before every commit; blocks on critical issues, warns on non-blocking ones; Windows-compatible (shell script, not Python shebang)

### CI/CD: PR Review Bot & Test Infrastructure (2026-09-10)
- [x] `tests/test_decision_engine.py`: 14 unit tests, pure-logic (no DB) — every threshold branch covered
- [x] `frontend/lib/auth.test.ts`: 5 Vitest tests for auth localStorage helpers
- [x] `npm run lint` / `npm run typecheck` — both 100% clean, zero baseline exceptions
- [x] `.github/workflows/pr-review-bot.yml`: lint-typecheck + artifact-scan + regression-tests → auto-merge on all-green
- [x] `.github/workflows/update-baseline.yml`: refreshes `.ci/baseline-results.json` after every merge to `main`
- [x] `scripts/verify_artifacts.py`: validates Next.js build output against its own routes manifest
- [x] `scripts/compare_baseline.py` + `generate_baseline.py`: JUnit-based regression diffing
- [x] `scripts/review_bot.py`: decision logic — merges only if every required job is exactly `success`
- [x] `scripts/spawn-agent-worktree.sh`: isolated git worktree + branch per agent/task, own npm/pip install
- [x] `scripts/setup_branch_protection.sh` applied to the live repo — `main` now requires the 3 PR-bot status checks before merge; direct `git push` to `main` is rejected (`GH006: Protected branch update failed`), confirmed firsthand during doc updates on 2026-09-22. All work since lands via PR + auto-merge.
- [x] `BOT_PAT` repo secret configured (2026-09-11) — decision job can now comment/merge PRs

## Messenger Channel Fixes (2026-09-19 – 2026-09-21) ✅
- [x] Nav restructure: removed the New Message / Requests / Conversations tab bar; `/messages` redirects to `/messages/conversations` (default landing page), which gains a New Requests link with pending count and a New message button. Compose/search moved to `/messages/compose`.
- [x] `nav-bar.tsx` Messages-link fallback (requests vs. conversations by badge state) re-scoped to the Messages item only — a prior version applied it to every nav item's `href`, which silently made Home/Search no-op while already on a `/messages/*` page (found and fixed via scripted browser repro, PR #27)
- [x] Per-message timestamps and day separators in the thread view (`DaySeparator.tsx`, `lib/messageDayGroups.ts`)
- [x] Message action menus: received messages get Copy/Reply/Report, sent get Edit/Reply/Copy (`MessageActionMenu.tsx`), each wired to a real action; menu trigger positioning fixed to render after the message bubble, not before (PR #25)
- [x] Duplicate-channel prevention (`idx_chat_requests_one_pending` partial unique index, oracle-denial-preserving) — confirmed already correct on the backend, not rebuilt
- [x] Abusive first-message handling changed from silent-drop to a visible `OffensiveBanner.tsx` in the recipient's requests inbox in place of the decrypted text — sender-side response stays non-distinguishing (oracle-denial preserved); the chat request row is now created (piggybacking on the existing `chat_requests.scan_verdict='abusive'` value) rather than dropped
- [x] Blocked users list under Settings → Privacy (`/settings/privacy`, PR #26)
- [x] Supporting pure-logic modules + tests: `lib/clipboard.ts`, `lib/messageSupersession.ts`, `lib/offensiveContent.ts`, `lib/pendingOutboundRequests.ts`

## Feed Redesign: Horizontal Swipe + Long-Press Thumbnail Picker (2026-09-21 – 2026-09-22) ✅
- [x] Full replacement of vertical swipe-up/down with horizontal swipe/flick — single-card index architecture (`current`/`items`) reused unchanged, only the gesture axis and animation are new (PR #28)
- [x] Tap/swipe/long-press gesture classification extracted to pure, unit-tested `lib/gestureClassifier.ts` (no component-render harness in this repo — matches the `messageDayGroups.ts` precedent)
- [x] Long-press (3s hold) opens `ThumbnailStrip.tsx` — windowed horizontal thumbnail strip (own `VideoThumbnail.tsx` pool, `<video preload="metadata" muted>`, never touching the main player) for jumping directly to any video; selecting one closes the strip
- [x] Live drag-follow: card tracks the pointer 1:1 during drag (zero-transition), then animates a commit-and-exit or snap-back-to-center on release instead of an instant cut (PR #29)
- [x] Velocity-based flick detection: a fast short drag advances even under the 40px distance threshold, tracked live move-to-move rather than at the final move-to-pointerup gap (which undercounts real flicks due to lift latency — found via real-browser timestamp logging, PR #30)
- [x] All gesture/windowing logic verified via Vitest (`gestureClassifier.test.ts`, `feedItems.test.ts`) and real-browser Playwright checks (temporary installs, cleaned up after each PR)

## Houses: Department Browsing + Custom Curated Collections (2026-09-22)

### Schema (U1) ✅
- [x] `houses` table: `id TEXT PK`, `owner_id UUID`, `name`, `description`, `created_at` — custom Houses only; built-in (one per department) have no table, derived from `users.department` at query time
- [x] `house_creator_members` / `house_video_members` junction tables — composite PK, `ON DELETE CASCADE`, mirroring `follows`'s shape; FK typing (`UUID` for creator/owner references) verified correct against a live Postgres instance, not just assumed
- [x] `docs/architecture.md`'s `### Database` block updated with all three tables

### Backend API (U2) ✅
- [x] `GET /houses` — built-in (hardcoded `DEPARTMENTS` list) + custom (with member counts)
- [x] `GET /houses/department/{name}/feed` — built-in House feed, `::uuid`-cast join verified against live Postgres
- [x] `GET /houses/{house_id}/feed` — custom House feed, unioned creator+video membership, dedup confirmed live (one `SELECT`, `OR`'d `WHERE`, no `UNION`/`DISTINCT` needed)
- [x] Both feed routes reuse the exact `_enrich()` transform `GET /feed` already applies (extracted to a shared helper) — confirmed live that every House-feed video has `job_id`/`pillars`/a real presigned `video_url`, not the "No video available" failure mode a skipped enrich step would cause
- [x] `POST /houses` (creator-only) / `DELETE /houses/{house_id}` (owner-only)
- [x] `POST`/`DELETE /houses/{house_id}/members/creators/{creator_id}` and `.../videos/{video_id}` (owner-only)
- [x] `_require_house_owner` — this codebase's first resource-ownership check (404 if missing, 403 if not owner), mirroring `_require_creator`'s shape
- [x] Video-membership has **no** ownership check on the video's creator (KTD2a, deliberate) — confirmed live: an owner can curate a video from a completely unrelated creator into their House
- [x] `POST /auth/upgrade` now validates `department` against the canonical `DEPARTMENTS` list (400 on case-mismatch/whitespace/unknown) — closes the gap where an invalid department silently breaks a creator's own built-in House with no error anywhere
- [x] `frontend/lib/api.ts` typed client functions for every new endpoint
- [x] `tests/test_houses.py` — 36 new live-Postgres integration tests (House CRUD, feed union/dedup, department exact-match, membership idempotency, route-level 403/404/`_enrich()`-reuse); all pass alongside the pre-existing 14 `test_decision_engine.py` tests (50 total)
- [x] `docs/architecture.md` — new `## Houses` section + route documentation + `## Feed Algorithm` divergence note; `README.md`'s API Reference table and Database Schema block updated to match

### Frontend: pure-logic module (U3) ✅
- [x] `frontend/lib/houses.ts` — `parseHouseParam` (the `"department:<name>"` vs. bare-custom-id discriminator behind KTD7) and `formatHouseMemberCount` (singular/plural, zero-half-omitted display formatting)
- [x] `frontend/lib/houses.test.ts` — 9 Vitest tests, all passing

### Frontend: listing page + detail route + nav entry (U4) ✅
- [x] `/houses` (`app/houses/page.tsx`) — Departments + Custom Houses sections from `listHouses()`, tappable cards (department → `/feed?house=department:<name>`, custom → `/houses/[id]`), creator-only "Create a House" inline form posting to the real `createHouse()` client function
- [x] `/houses/[id]` (`app/houses/[id]/page.tsx`) — owner vs. non-owner branch via `getUser()?.id` vs. the House's `owner_id`; non-owner `router.replace`s straight to `/feed?house=<id>` with no intermediate screen (KTD7); owner sees a working "View feed" link plus a Manage Members section
- [x] Manage Members ships as a labeled placeholder/skeleton only in this unit ("Coming soon", no functional search/add/remove) — deliberate scope boundary so U5 can build the real interaction inside the same file without a merge conflict
- [x] One new `nav-bar.tsx` `NAV_ITEMS` entry (`Houses`, `Building2` icon, no `creatorOnly`) — existing active-highlight and badge-dot logic required no changes, confirmed via real-browser check on both `/houses` and `/houses/[id]`
- [x] Verified via `tsc --noEmit` (clean), `eslint` (0 errors), all 171 Vitest tests passing, and real-browser Playwright checks (temporary install, removed after) — 31 assertions covering both sections rendering, card navigation, nav highlighting, the owner/non-owner branch, the placeholder's absence of functional add-member UI, and the create-form POST + redirect flow

### Frontend: House-scoped feed + manage-members UI (U5) ✅
- [x] `frontend/app/feed/page.tsx` — `<Suspense>` restructure: default export is now a thin `<Suspense fallback={null}><FeedPageInner /></Suspense>` shell (exact pattern match to `app/messages/compose/page.tsx`'s existing precedent), today's entire component body moved unchanged into `FeedPageInner`
- [x] Mount effect branches on `useSearchParams().get("house")` via `parseHouseParam` (U3): `null` → existing `getFeed()` path, confirmed byte-for-byte unchanged; department → `getDepartmentHouseFeed()`; custom → `getHouseFeed()` + a parallel `listHouses()` call for the House's name/owner. Single `SectionDivider` (House/department name) instead of Following/Recommended (KTD4)
- [x] `current` resets on House-scope change (covers client-side navigation between two House feeds without a remount)
- [x] Divider-auto-skip (~600ms flash) becoming universal on House-scoped loads confirmed as a known, accepted side effect — verified it resolves cleanly, including for a single-video House
- [x] House-scoped empty state has its own copy (non-owner: "No videos in this House yet."; the custom House's own owner: "No members yet." + a working link to the manage-members view) instead of reusing the default feed's upload-focused copy
- [x] `frontend/app/houses/[id]/page.tsx` — real manage-members UI replaces U4's placeholder: Creators + Videos sections, `settings/privacy`'s confirmed add/remove pattern, debounced global `searchAll()` search for both add flows (video search is NOT self-scoped, per KTD2a), optimistic-after-success add/remove wired to U2's real endpoints
- [x] Member lists are session-local by design (no "list current members" endpoint exists — `GET /houses` returns only counts, `GET /houses/{id}/feed` returns an undifferentiated unioned list) — documented as a real scope boundary, not an oversight
- [x] Verified via `tsc --noEmit` (clean), `eslint` (0 errors), all 171 Vitest tests passing, a clean `next build` (confirms the `<Suspense>` restructure introduces no build/prerender failure), and real-browser Playwright checks (temporary install, removed after) run against a production (`next start`) server — 21/24 assertions pass outright; the remaining 3 are an unrelated, pre-existing console-error signature from `nav-bar.tsx`'s unstubbed realtime-ticket fetch, confirmed present on the plain default-feed scenario too (not a House-scoping regression)
- [x] **Default `/feed` regression guard passed**: no `house` param renders identically to before this unit — correct section label, correct video count, swipe gesture still advances correctly, no uncaught errors, no visible Suspense fallback flash

### Multi-Department Content Tagging ✅ (not yet deployed to EC2)
- [x] New table `video_department_tags` (`video_id, department, is_primary, tagged_at`) — many-to-many, one primary tag (auto-derived from uploader's department at upload time, frozen after) plus up to `MAX_ADDITIONAL_DEPARTMENTS = 5` additional tags
- [x] DB-enforced single-primary-per-video via a partial unique index (`WHERE is_primary`), not just application discipline
- [x] Idempotent backfill in `_ensure_schema()` gives every pre-existing (zero-tag) video a primary tag from its creator's current department — added after this was caught as a real regression by the existing `test_houses.py` suite, not part of the original design
- [x] `get_department_house_feed` rewritten to tag-based membership (`EXISTS` against `video_department_tags`) instead of joining to `users.department` — a video now surfaces in every department it's tagged into, not only its creator's home department
- [x] `POST /videos` accepts an optional `departments` form field (additional tags only — primary is always server-derived, never client-supplied); validates against `DEPARTMENTS` and the max-additional cap
- [x] `POST /videos/{id}/departments` / `DELETE /videos/{id}/departments/{department}` — owner-only, additional tags only; primary tag removal isn't reachable through either route, with a second defense-in-depth layer at the `db.py` level
- [x] `_enrich()` batch-attaches `department_tags` to every feed row (no N+1)
- [x] `frontend/app/upload/page.tsx` — locked primary-department chip + multi-select additional-department picker (primary excluded from its own option list); post-upload result card and status view both render the full tag set
- [x] Found and fixed a real bug via live testing (not code review): FastAPI needs explicit `Form(...)` on a `str` parameter alongside `UploadFile`, or the field silently fails to bind and the intended validation never fires
- [x] `tests/test_department_tags.py` — 26 new tests against a live disposable Postgres; `tests/test_houses.py` updated (fixture + stale local `DEPARTMENTS` list) with no other regressions across its 36 tests
- [ ] Not yet deployed to EC2 / verified live

### Long-Press Hint Affordance ✅ (fixes #32)
- [x] Pulsing-ring visual cue on `SwipeCard`, shown only for the first 3 videos of a session
- [x] Dismissed permanently for the session once the long-press is actually used, independent of the video-index gate
- [x] Respects `prefers-reduced-motion` — static ring, no keyframe `<style>` injected under reduced motion
- [x] Verified in a real browser (screenshots), including catching and working around a stale local `.env.local` that was silently pointing local dev at the production API mid-verification

### Right-Sized Feed Ranking, Per-Video Credits, "Not Interested" ✅ (not yet deployed to EC2)
- [x] `video_credits` table — per-user, per-video, toggleable; replaces the old unauthenticated/undeduped counter entirely
- [x] `POST /videos/{id}/credit` now requires login and toggles (credit/un-credit) instead of only ever incrementing
- [x] `users.credits` frozen as a historical total; `get_creator_profile`/`search` now compute a LIVE sum from `video_credits` instead
- [x] Fixed a real pre-existing bug: the star button's filled/count state was client-session-only, never read from the server — every video always showed 0 credits on page load regardless of real engagement
- [x] `get_feed`'s `recommended` bucket now uses a weighted score (`3*credits + 2*comments + 1*recency_decay`, 48h half-life) instead of `creator.credits DESC` — fixes a popular creator's old videos always outranking a new creator's good video; `enrouted` deliberately stays purely chronological
- [x] `dismissed_videos` table + `POST /videos/{id}/dismiss` — "not interested," excluded from both feed buckets, removed from the current session immediately (not just the next fetch)
- [x] Found and fixed two unrelated pre-existing bugs during real-browser verification: the divider auto-skip could double-fire under React StrictMode (moved into a proper `useEffect`), and `SwipeCard`'s unconditional `setPointerCapture()` was silently breaking real clicks on every action button (Credits/Comment/Share/Save/Not interested) and Enroute
- [x] `tests/test_feed_ranking.py` — 28 new tests against a live Postgres; full existing suite (106 total) passes with no regressions
- [ ] Not yet deployed to EC2 / verified live

### Security Hardening: Phase 0 (JWT Fixes) + Phase 1 (CI Security Agent) ✅
- [x] JWTs now carry a real `exp` claim (24h) — previously never expired
- [x] `JWT_SECRET`'s hardcoded fallback removed; app fails to start loudly if unset
- [x] New `security-scan` CI job (bandit + pip-audit + npm audit) wired into `pr-review-bot.yml`, parallel to the existing jobs, required for auto-merge
- [x] `scripts/security_gate.py` — new-findings-only gate against a reviewed `.ci/security-baseline.json`, same philosophy as the existing test-regression baseline
- [x] Found and fixed a real pre-existing CI gap: `regression-tests` never set `POSTGRES_URL`, so 92 of 112 local tests silently skipped in CI on every run since `test_houses.py` was added — added a Postgres service container
- [x] Found and fixed a real dependency-drift gap: `passlib`/`python-jose`/`boto3`/`python-dotenv` were used but never listed in `requirements.txt`
- [x] Found and fixed a genuine CVE: `python-multipart` (handles every video upload) bumped 0.0.20 → 0.0.32, closing several parser-level DoS issues; `python-jose`/`python-dotenv` also bumped
- [x] `tests/test_auth_security.py` — 6 new tests against a live Postgres
- [ ] Phase 2 (RDS/ElastiCache/S3 encryption), Phase 3 (refresh tokens, httpOnly cookies), Phase 4 (GDPR/CCPA endpoints), Phase 5 (messaging E2E WASM spike) — not started, need AWS console access / maintenance windows / a dedicated research spike (see the published security plan doc for full scope)
- [ ] `gitleaks` (content-based secret scanning) deferred — needs a GitHub App/license setup not provisionable from this session
- [ ] Not yet deployed to EC2

### R&D Agent Department: Scaffolding ✅ (dispatch not yet implemented, no API key provisioned)
- [x] `docs/plans/templates/rd-proposal-template.md`, `docs/rd-research-log.md` — extends this repo's existing plan-doc convention
- [x] `scripts/check_worker_file_scope.py` — file-scope enforcement, verified against the real Houses plan doc, not just fixtures
- [x] `scripts/compute_worker_matrix.py` — dependency-ordered wave scheduling, verified against the real Houses plan doc (found and fixed a real parenthetical-parsing bug in the process)
- [x] `.github/workflows/rd-approval-watcher.yml`'s `validate-approval` job — plan-only-PR + write-access checks, no Claude invocation, fully verifiable without an API key
- [x] `.github/workflows/rd-department.yml` — Decision Agent → Tech Lead Agent (session-resumed), cron disabled by default, `workflow_dispatch` dry-run only until a key is provisioned
- [x] Corrected a real inaccuracy in the published design doc via primary-source research: no `--max-budget-usd` flag exists; real cost controls are `--max-turns` + job `timeout-minutes` + a `concurrency` group
- [ ] `ANTHROPIC_API_KEY` not provisioned — nothing in either workflow can actually invoke Claude yet
- [ ] `dispatch-workers`' actual per-unit Worker Agent invocation step — documented `TODO`, deliberately unwritten (see `docs/rd-department-setup.md`)
- [ ] Real end-to-end dry run (manual `workflow_dispatch`) not yet performed — first real invocation should be closely supervised, not the real cron

## Pipeline Hardening (2026-10-29)
- [x] Pillars run truly concurrently (`asyncio.to_thread`) — regression-tested
- [x] Celery retries with backoff (max 3); persistent failure is fail-closed (`needs_review`, hidden from feeds) and dead-lettered
- [x] `scripts/replay_dlq.py` to list / replay dead-lettered jobs
- [x] Perceptual (dHash) near-duplicate detection → flagged; exact SHA-256 → blocked
- [x] CloudWatch metrics: verdict latency, queue depth, dead-letter depth (opt-in via `CLOUDWATCH_NAMESPACE`)
- [x] `backend/Dockerfile`, `scripts/push_ecr.sh`, CloudFormation IAM for metrics
- [ ] Deploy to EC2 (stack update, `.env` line, OpenCV check, restart both services) and re-measure verdict latency with real APIs
- [ ] Build the Docker image and push to ECR (needs a Docker daemon + AWS credentials)
- [ ] CloudWatch alarm on `DeadLetterDepth > 0` (needs an SNS topic)

## Pending / Future
- [ ] Creator profile: list their approved videos inline
- [ ] Notifications for new followers and credits received
- [ ] Saved videos (bookmark persisted to DB, not just local state)
- [ ] CloudFormation UserData fully automated (no manual `pip install` step)
- [ ] Remove `/debug/feed` and `/debug/search` endpoints before public launch
