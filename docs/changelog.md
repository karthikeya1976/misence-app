# Changelog

## 2026-06-14
- Project initialized: repo, docs scaffold, `.gitignore`, `CLAUDE.md`.

## 2026-06-15
- **Milestone 1**: FastAPI gateway (`/health`, `POST /videos`, `GET /videos/{id}/status`), MinIO storage, MongoDB job docs, Celery task `process_video`. Infra via docker-compose. Verified end-to-end: pending → processing → received.
- **Milestone 2**: Three mock moderation pillars (`adult_content`, `ai_deepfake`, `copyright_match`) with deterministic pseudo-random scores via `common.py`. `aggregator.py` combines scores into approved/flagged/blocked. Pillars run concurrently via `asyncio.gather`.

## 2026-06-17
- **Milestone 3**: `GET /videos` list endpoint + CORS. Next.js 16 frontend: upload page (`/`), moderation dashboard (`/dashboard`) with 3-second polling, per-job expandable detail rows, pillar score bars, flag timelines, verdict badges.

## 2026-06-28 — v2 Architecture Upgrade
- **PostgreSQL** replaces MongoDB (`psycopg2-binary`; `videos` table with JSONB columns).
- **Temp disk** replaces MinIO (`UPLOAD_DIR = C:/tmp/video_uploads/`).
- `aggregator.py` → `decision_engine.py` (rename, no logic change).
- `POST /videos` now returns `{status, task_id}` (instant ack).
- `tasks.py` calls `storage.cleanup_video()` after processing.
- E2E tests updated; all 15 pass against new stack.

## 2026-09-08 — Redactor MVP
- **JWT auth**: `POST /auth/register`, `/auth/login`, `/auth/upgrade`. `python-jose` + `passlib[bcrypt]`. `users` table added to PostgreSQL.
- **Creator-gated upload**: `POST /videos` requires Creator JWT; `user_id` stored on video rows.
- **S3 storage**: `storage.py` rewritten with `boto3`; `amzn-s3-bucket-dvm` (us-east-2). IAM instance profile support on EC2.
- **4th pillar** `filmmaking_relevance`: AWS Rekognition `DetectLabels`; inverse scoring — score < 0.3 → blocked. `BLOCK_BELOW_THRESHOLDS` added to `decision_engine.py`.
- **Real moderation APIs**: Sightengine nudity-2.1 (adult content), Sightengine genai (deepfake), SHA-256 hash (duplicate detection), AWS Rekognition (filmmaking).
- **Frontend redesign**: dark theme (`#0a0a0f` bg, `#4169e1` selenium blue), collapsible sidebar (icons → labels on hover), 4 pages: `/` auth, `/feed`, `/upload`, `/profile`.

## 2026-09-09 — AWS Deployment
- **CloudFormation** `infra/cloudformation.yml`: VPC, subnets, IGW, security groups, RDS PostgreSQL 15 (db.t3.micro), ElastiCache Redis (cache.t3.micro), EC2 t3.small (Amazon Linux 2023), IAM role + instance profile.
- **Nginx + Let's Encrypt** via DuckDNS: `https://redactor-api.duckdns.org` terminates TLS, proxies to `:8088`.
- **Systemd services**: `redactor-api` and `redactor-celery` auto-restart and survive reboots.
- **Vercel deploy**: frontend at `https://distributed-video-moderation.vercel.app`.
- End-to-end verified on AWS: register → login → upgrade → upload → S3 → Celery → 4 pillars → RDS → presigned URL feed.

## 2026-09-10 — Editor Club Social Features

### Smart feed
- `GET /feed` now accepts optional `?token=<jwt>` and returns `{enrouted, recommended}` instead of a flat list.
- Two SQL queries: (1) videos from followed creators, recency-ordered; (2) all others, ranked by `creator.credits DESC, created_at DESC`.
- Frontend merges buckets with `SectionDivider` entries (`Following` / `Recommended`). `isDivider()` guards against `undefined` at Next.js build time (prerender crash fix).

### Follow / Enroute system
- `follows` table added: `(follower_id UUID, following_id UUID, created_at)` with composite PK.
- `POST /creators/{id}/follow` and `DELETE /creators/{id}/follow` endpoints.
- Enroute/Deroute pill in feed overlay, creator profile page, and search results. Optimistic update with revert on error.

### Credits
- `users.credits INTEGER DEFAULT 0` column added.
- `POST /videos/{id}/credit` increments creator credits by 1.
- Star button in feed shows live count; one credit per viewer per session.

### Comments
- `comments` table: `(id UUID, video_id TEXT, user_id UUID, body TEXT, created_at)`.
- `GET /videos/{id}/comments` and `POST /videos/{id}/comments?token=<jwt>`.
- `CommentDrawer` in feed fetches on open, posts with author attribution; author name + initials shown per comment.
- `_ensure_schema()` fixed: `CREATE INDEX` split into a separate `execute()` call (psycopg2 only handles one statement per call).

### Search
- `GET /search?q=` ILIKE query across creator names/departments and video filenames.
- Debounced 400ms via `useEffect` + `useRef` timer (replaces broken `useCallback(debounce())` pattern).
- UX: animated 3-dot loading indicator, clear (×) button, error banner, no-results state with suggestions.

### Creator profile page
- `/creators/[id]` with avatar (initials), name, department chip, stat tiles (followers, videos, credits), Enroute/Deroute button, back button.

### Upload format toggle
- **Scene** (16:9 landscape) and **Shot** (9:16 portrait) selector above the drop zone.
- Drop zone shape changes to match the selected format's aspect ratio.
- Switching format clears the file picker. Submit button label reflects format.

### Feed swipe navigation
- `SwipeCard` component wraps the reel card: `onPointerDown`/`onPointerMove`/`onPointerUp` track drag delta.
- Swipe up = next, swipe down = prev, tap = pause/play. Works with mouse and touch.
- Removed arrow navigation buttons below the card; subtle ↑/↓ hints shown inside card edges.
- Arrow keyboard navigation (`↑↓` + `Space`) still works alongside swipe.

### NavBar
- Logo: "EC" monogram collapsed → "Editor Club" full name expanded; `<Link href="/feed">` (was dead `<div>`).
- Nav items: Home (`/feed`), Search (`/search`), Upload (`/upload`, creator only), Profile (pinned bottom).
- Logout removed from sidebar — exists only on `/profile`.

### Bug fixes
- **Mixed-content block**: added `next.config.ts` rewrite proxying `/api/backend/*` to `https://redactor-api.duckdns.org/*` at Vercel edge. All API calls use `/api/backend` base — browser never makes a cross-origin HTTPS→HTTP request.
- **EC2 JOIN crash**: `videos.user_id` is `UUID` on EC2 (unlike local `TEXT`); changed all JOINs from `v.user_id = u.id::text` to `v.user_id::uuid = u.id`.
- **Prerender crash**: `isDivider()` now accepts `FeedItem | undefined` and guards `item != null` before `"_divider" in item`.

### Cleanup
- Removed unused files: `app/dashboard/page.tsx`, `components/job-detail.tsx`, `components/jobs-table.tsx`, `components/upload-form.tsx`, `components/ui/{badge,button,card,progress}.tsx`, `lib/utils.ts`, `components.json`, `frontend/README.md`, `public/*.svg` (Next.js boilerplate assets).
- Updated `README.md`, `docs/architecture.md`, `docs/project_status.md`, `docs/changelog.md` to reflect current Editor Club state.

### Repo health tooling
- Added `scripts/scan-repo.py`: scans for tracked secrets, dead Python modules, dead frontend components, `.env.example` drift, stale docs (>30d), and TODO/FIXME markers. Run with `--fix` to auto-delete dead files.
- Added `.git/hooks/pre-commit` (shell script): runs `scan-repo.py` before every commit. Blocks on secrets or `.env.example` drift; warns (non-blocking) on dead files, stale docs, and TODOs. Resolves Windows Python path by searching known install locations rather than relying on the `python3` shebang (which hits the Windows Store stub on Git Bash).

## 2026-09-10 — CI/CD: PR Review Bot, Test Suites, Worktree Support

### Test suites (new)
- `tests/test_decision_engine.py`: 14 unit tests covering every threshold branch in `decision_engine.py` (block, flag, inverse-scoring, priority ordering, unknown-pillar no-op). Imports the module directly by path so it never needs a live Postgres connection (`app.main` calls `db._ensure_schema()` at import time, which does).
- `frontend/lib/auth.test.ts`: 5 Vitest tests for `lib/auth.ts` (token/user round-trip, malformed-JSON handling, clear).
- Added Vitest + jsdom to `frontend/package.json` (`npm test`), plus `npm run typecheck` (`tsc --noEmit`).
- `backend/requirements.txt`: added `pytest==8.3.4`.

### Lint gate hardened to zero-tolerance
- Fixed 3 pre-existing `react-hooks/set-state-in-effect` errors (nav-bar, profile, search) by deriving state during render or via lazy `useState` initializers instead of `setState` inside a bare effect body — same behavior, no extra render pass.
- Fixed 1 unused-variable warning in `app/creators/[id]/page.tsx` (dead `token` local — `getCreatorProfile` already reads the token internally).
- `npm run lint` and `npm run typecheck` are now 100% clean — no baseline exceptions needed.

### PR Review Bot (GitHub Actions)
- `.github/workflows/pr-review-bot.yml`: on every PR into `main`, runs 3 jobs in sequence/parallel — `lint-typecheck` (eslint + tsc + backend `py_compile`), `artifact-scan` (build the frontend, verify output), `regression-tests` (both test suites vs. baseline) — then a `decision` job that auto-merges (squash) only if all three report `success`.
- `.github/workflows/update-baseline.yml`: after every merge to `main`, re-runs both suites and commits a refreshed `.ci/baseline-results.json`, so the regression gate always compares against main's actual current state.
- `scripts/verify_artifacts.py`: reads Next.js's own `app-path-routes-manifest.json` to check every declared route produced a non-empty server bundle file — no hardcoded page list to go stale.
- `scripts/compare_baseline.py` / `scripts/generate_baseline.py`: parse JUnit XML from pytest + Vitest, diff against `.ci/baseline-results.json`. Blocks only on *new* regressions (a test that passed on `main` and now fails) — pre-existing failures don't permanently block the repo.
- `scripts/review_bot.py`: takes `--check name=status` per job, merges via `gh pr merge --squash --auto` only if every status is exactly `success` — any other value (including `cancelled`) blocks.
- `.ci/baseline-results.json`: initial baseline, 19/19 tests passing.

### Worktrees for parallel agent work
- `scripts/spawn-agent-worktree.sh <task-id> <slug>`: creates an isolated `git worktree` + branch (`agent/<task-id>/<slug>`) with its own `npm ci` / venv install, so multiple agents can work on separate branches simultaneously without sharing a working directory or lockfile.
- `scripts/setup_branch_protection.sh`: one-time (not yet run) script to make the 3 CI jobs required status checks on `main`, with `enforce_admins: true`. Not applied automatically — enabling it blocks direct pushes to `main` for everyone, including solo maintainers, so it needs an explicit decision to run.

### Not yet done (as of 2026-09-10)
- Branch protection is scripted but **not applied** to the live GitHub repo — run `sh scripts/setup_branch_protection.sh` when ready to require the bot's checks before merge.
- `BOT_PAT` secret (fine-grained PAT scoped to `contents:write` + `pull-requests:write`) must be added to the repo's Actions secrets before the `decision` job can actually comment/merge.

**Update:** both of the above are done. `BOT_PAT` was configured 2026-09-11; branch protection was applied at some point before 2026-09-19 (PRs #24 onward all required merging via `gh pr create` + auto-merge — a direct `git push` to `main` attempted during doc updates on 2026-09-22 was rejected with `GH006: Protected branch update failed for refs/heads/main... 3 of 3 required status checks are expected`, confirming it's live).

## 2026-09-19 to 2026-09-21 — Messenger Channel Fixes

Implemented `docs/plans/2026-09-18-001-feat-messenger-channel-fixes-plan.md`'s 8 units across this repo (frontend) and `gatekept` (backend, verified/confirmed only — no new backend code needed).

### Nav restructure (U4)
- Removed the New Message / Requests / Conversations tab bar (`MessagesNavTabs.tsx` deleted). `/messages` now redirects to `/messages/conversations`, the canonical landing page, which gained a "New Requests" link (with pending count) and a "New message" button.
- Compose/search flow moved to its own route, `/messages/compose`, reachable from that button and the existing creator-profile "Message" deep link.
- **Bug found and fixed (PR #27):** `nav-bar.tsx`'s Messages-specific href fallback (route to `/messages/requests` while the badge dot is visible, else `/messages/conversations`) was applied unconditionally to every nav item's `href`, not just the Messages item — Home and Search silently pointed at `/messages/conversations` too. From any `/messages/*` page, clicking Home or Search was a same-URL Link navigation (no-op), which looked like the nav had stopped responding. Diagnosed via a scripted Playwright repro (register, land on `/messages/conversations`, inspect the nav DOM) after static code reading wasn't conclusive; fixed by scoping the fallback to `item.href === "/messages"` without changing `item.href` itself (both the active-highlight prefix match and the badge-dot exact match still depend on it staying literally `"/messages"`).
- **Bug found and fixed (PR #25):** the message action-menu trigger rendered before the message bubble instead of after it.

### Timestamps and day separators (U5)
- `components/DaySeparator.tsx` + `lib/messageDayGroups.ts` (pure grouping logic, unit-tested): the thread view now shows a per-message timestamp and a day-separator whenever the conversation crosses into a new calendar day.

### Message action menus (U6)
- `components/MessageActionMenu.tsx`: received messages get Copy/Reply/Report; sent messages get Edit/Reply/Copy. Each wired to a real action rather than a placeholder.
- `lib/clipboard.ts` (new, tested): Copy action's clipboard helper.
- `lib/messageSupersession.ts` (new, tested): resolves the Edit action's cryptographic constraint — message ciphertext is Double-Ratchet-bound to a specific `message_number`/session step, so an in-place ciphertext UPDATE would not decrypt correctly for a recipient who has already advanced past that step. Edits are modeled as a superseding message instead of a naive overwrite.

### Duplicate-channel prevention (U8) — confirmed, not rebuilt
- Verified the existing `idx_chat_requests_one_pending` Postgres partial unique index (scoped per `(sender_id, recipient_id)` pending pair) in the `gatekept` backend already fully prevents duplicate chat channels and blocks a second message before the recipient accepts, with oracle-denial-preserving behavior intact. No backend changes made — this was a confirm-and-wire-through-the-UI unit (`lib/pendingOutboundRequests.ts`, new, tested: disables Send on an already-pending outbound request), not a rebuild.

### Abusive-first-message handling — security posture change (U7)
- Previously: a first message that scored `abusive` on the moderation scan created **no** `chat_request` row at all, and the sender received an identical-looking fake success — a deliberate oracle-denial design (the sender can't distinguish "recipient declined" from "message was silently dropped for being abusive").
- Now: an abusive-verdict first message **does** create a row (writing the already-existing-but-previously-unwritten `chat_requests.scan_verdict = 'abusive'` value), and the **recipient** sees `components/OffensiveBanner.tsx` in place of the decrypted text in their requests inbox instead of nothing arriving at all.
- The sender-side response is unchanged and still non-distinguishing — only the recipient-side display changed. `lib/offensiveContent.ts` (new, tested) carries the recipient-side verdict-to-banner logic.

### Testing
- New pure-logic test files: `lib/clipboard.test.ts`, `lib/messageDayGroups.test.ts`, `lib/messageSupersession.test.ts`, `lib/offensiveContent.test.ts`, `lib/pendingOutboundRequests.test.ts` — following this repo's existing precedent of extracting testable logic out of components that have no render-test harness.

## 2026-09-21 to 2026-09-22 — Feed Redesign: Horizontal Swipe + Long-Press Thumbnail Picker

Full replacement of the feed's vertical swipe-up/down gesture model with horizontal swipe, plus a new long-press-to-reveal thumbnail picker for jumping directly between videos. No dual-mode/flag — this is the only gesture model now. No backend changes: thumbnails render as `<video preload="metadata" muted>` elements rather than requiring a new `thumbnail_url` field, which also sidesteps canvas/CORS complications with the S3-presigned `video_url`.

### Core redesign (#28)
- The feed's existing single-card, index-based architecture (`current: number` into a flat `items` array, only one `<video>` ever mounted/playing) was reused unchanged — this was an axis flip and a new interaction layered on top, not a rewrite.
- `lib/gestureClassifier.ts` (new, unit-tested): pure tap/swipe/long-press decision logic extracted out of `SwipeCard`'s pointer-event handlers, matching this repo's `messageDayGroups.ts`-style precedent for testable logic without a component-render harness. `MOVE_TOLERANCE` (10px), `SWIPE_THRESHOLD` (40px), `LONG_PRESS_MS` (3000ms).
- `lib/feedItems.ts` (new, unit-tested): `SectionDivider`/`FeedItem`/`isDivider` hoisted out of `page.tsx`, plus `computeVisibleWindow` — pure-arithmetic windowing (`scrollLeft / itemWidth`) for the thumbnail strip, deliberately avoiding both a virtualization library and per-item `getBoundingClientRect()` measurement given realistic feed sizes (dozens of items, not thousands).
- `components/ThumbnailStrip.tsx` + `components/VideoThumbnail.tsx` (new): the long-press-revealed picker. Renders the same full flat `items` order (not a creator-only subset); dividers render as non-interactive label chips. Only mounts live `<video>` elements within a windowed range around the scroll-derived center index — a separate pool from the main player's `videoRefs`. Scroll-to-center on open respects `prefers-reduced-motion` (first use of that media query in this codebase, scoped only here). Dismiss via tap-outside, swipe-down, or Escape; selecting a thumbnail auto-closes the strip.
- Long-press pauses the current video (reuses the existing `paused` state) before opening the strip, rather than leaving it playing behind a scrim.
- `onPointerCancel` handling added to `SwipeCard` — a real gap in the original vertical-swipe implementation (no cancel/leave handler at all), now load-bearing since a 3-second hold gives an OS gesture or browser chrome much more opportunity to steal the pointer mid-gesture than the old sub-second swipe did.
- Keyboard remapped: `ArrowUp`/`ArrowDown` dropped entirely in favor of `ArrowRight`/`ArrowLeft` (no aliasing); `Enter` opens the thumbnail strip, `Escape` closes it.

### Live drag-follow + snap animation (#29)
- The card previously had no visual feedback during a drag and cut instantly to the next/prev video on release. Now: the card translates 1:1 with the pointer during drag (zero-transition), then on release either animates fully off-screen in the swipe direction before the navigation callback fires (`COMMIT_MS`, 200ms) or eases back to center (`SNAP_BACK_MS`, 220ms) instead of an instant snap.
- New gestures are ignored while a commit/snap-back animation is still resolving, preventing overlapping animations or double-navigation from a rapid second swipe. Same Pointer Events handlers drive both mouse and touch.
- Verified via Playwright against a stubbed feed response.

### Velocity-based flick detection (#30)
- A fast, short flick now advances the feed even under the 40px `SWIPE_THRESHOLD` — `classifyPointerUp()` gained an optional `velocityX`; when the distance check doesn't qualify, a horizontal-dominant release past `FLICK_VELOCITY_THRESHOLD` (0.5px/ms) also resolves to swipe, using velocity's sign for direction rather than `dx`'s.
- **Bug found and fixed during implementation:** the first version computed release velocity from the last `pointermove` to `pointerup`, which systematically undercounted real flicks — real-browser testing (Playwright + raw pointer-event timestamp logging) showed the pointer typically sits still for 15-40ms between the last move and the actual lift (event coalescing/lift latency), zeroing out the velocity of a genuinely fast flick. Fixed by tracking velocity live, move-to-move, during `pointermove`, and reading that value at release instead of recomputing against the up-event's own late timestamp.
- 8 new test cases in `gestureClassifier.test.ts` cover the flick path; all 159 frontend tests pass (151 pre-existing + 8 new).

## 2026-09-22 — Theme: Peach Accent Replaces Selenium Blue

`--accent` (and every derived/hardcoded reference to it) changed from selenium blue (`#4169e1`) to a peach/terracotta (`#c25423`) across the entire app — nav highlight, buttons, links, the Enroute pill, the EC logo mark, form focus rings, and every hardcoded moderation-status "approved" badge literal (`profile/page.tsx`, `search/page.tsx`, `upload/page.tsx`, `feed/page.tsx`'s bookmark icon).

- **Color chosen for contrast, not just aesthetics:** the first candidate peach (`#ff9466`) was rejected after a real relative-luminance/WCAG contrast-ratio calculation showed it only reaches 2.17:1 against white button text (AA requires 4.5:1) — the prior blue reached 4.85:1. `#c25423` reaches 4.58:1 against white and 4.03:1 as a text/link color against the cream `--bg`, both passing. `--accent-dim` (hover state, `#8f3d18`) and `--accent-bg` (faint highlight tint, `#c2542315`) were derived with the same proportional darkening/alpha the prior blue tokens used.
- **Found during the sweep:** a second, separate hardcoded blue literal (`#7ba3ff`, a lighter tint used for "approved"-status text color and the feed's filled-bookmark icon) existed independently of `--accent`/`--accent-dim` in 4 files — not caught by an initial grep scoped to the base blue hex, found via a full unique-hex-literal audit of the codebase. Replaced with `#e08a5f`, the equivalent peach tint.
- Semantic status colors for "flagged" (amber) and "blocked" (red) were deliberately left unchanged — only the selenium-blue family was in scope.
- `README.md`'s tech-stack table updated (previously read "dark theme, selenium blue" — stale on two counts since the 2026-09-22 cream-theme change; now reads "light cream theme, peach accent").
- Verified via `tsc --noEmit` (clean), `eslint` (0 errors), all 162 Vitest tests passing, and real-browser checks (Playwright, temporary, removed after) confirming the peach resolves correctly via `getComputedStyle` across `/profile`, `/feed`, and a stubbed `/search` result showing the "approved" badge — not just source-level.

## 2026-09-22 — Houses: Backend Schema + API Surface (U1 + U2)

New browsable grouping concept — a **House** is either **built-in** (one per department, no table, derived live from `users.department`) or **custom** (an owned, curated collection a creator can build). Selecting a House hands off into the existing swipe feed, scoped (frontend wiring is a later unit; this entry covers the backend foundation only).

### Schema (U1)
- `houses(id TEXT PK, owner_id UUID REFERENCES users(id), name, description, created_at)` — `id` is a caller-generated UUID string (matching `create_job`'s pattern), not DB-generated.
- `house_creator_members(house_id TEXT, creator_id UUID, added_at)` / `house_video_members(house_id TEXT, video_id TEXT, added_at)` — two plain junction tables (not one polymorphic table), composite PK + `ON DELETE CASCADE`, mirroring `follows`'s exact shape.
- **FK typing double-checked against this codebase's one existing instance of getting it wrong** (`videos.user_id` was added `TEXT` instead of `UUID`, requiring an `::uuid` cast at every join site since): `houses.owner_id` and `house_creator_members.creator_id` are correctly `UUID` (verified via `\d houses` / `\d house_creator_members` against a live Postgres instance — confirmed, not just assumed from the SQL text).
- No `is_public` column (custom Houses are public-by-default with no visibility flag) and no `updated_at` (name/description editing deferred).

### Backend API (U2)
- `GET /houses` — `{builtIn: [{name}], custom: House[]}`. `builtIn` is a small hardcoded `DEPARTMENTS` constant in `main.py` (duplicated from `frontend/app/profile/page.tsx`'s list of the same name — no cross-boundary shared-constant mechanism exists in this codebase yet); `custom` includes creator/video member counts per House for the listing card.
- `GET /houses/department/{name}/feed` and `GET /houses/{house_id}/feed` — both return a flat `{videos: Job[]}` (no `{enrouted, recommended}` bucket split; a House isn't something you follow/don't-follow). Both run their rows through the **same `_enrich()` transform `GET /feed` already uses** — extracted from an inline closure to a shared module-level helper in `main.py` specifically so these two new routes reuse it rather than reimplementing it. Skipping this would leave every House-feed video with no `job_id` and no playable `video_url` ("No video available") — confirmed NOT the case via a real end-to-end `curl`/pytest check (see Verification below), not just code inspection.
- `GET /houses/{house_id}/feed`'s query unions creator-membership and video-membership in one `SELECT` with an `OR`'d `WHERE` (no `UNION`, no `DISTINCT` — a single `SELECT` over one base table can't itself return the same row twice) — confirmed via a live test where a video qualifying via both membership paths still appears exactly once.
- Both new queries carry the same `videos.user_id::uuid` cast already used four other places in `db.py` for this identical `videos JOIN users` shape — confirmed necessary via live Postgres (omitting it raises `operator does not exist: text = uuid` at query time, not a style choice).
- `POST /houses` (creator-only, `_require_creator`), `DELETE /houses/{house_id}` and the four `POST`/`DELETE /houses/{house_id}/members/{creators,videos}/{id}` routes (owner-only) — the last four introduce `_require_house_owner`, **this codebase's first resource-ownership check** (decode token → fetch house → 404 if missing → 403 if not owner), mirroring `_require_creator`'s shape.
- **`POST /houses/{house_id}/members/videos/{video_id}` has no ownership check on the video's creator, by design** — any House owner can curate any existing public video into their House regardless of who created it, matching `follow_user()`'s existing no-consent-required posture. Confirmed via a live test adding a video from an unrelated third creator, which succeeds and appears in the feed.
- **`POST /auth/upgrade` gains department validation** (400 if `department` isn't an exact match to `DEPARTMENTS`) — closes a real gap where an unvalidated department string (case/whitespace/typo mismatch) would leave a creator silently invisible to their own built-in House forever, with no error anywhere in the pipeline. Tightens an existing unvalidated field; no currently-valid caller's behavior changes.
- `frontend/lib/api.ts` — typed client functions for every new endpoint (`listHouses`, `createHouse`, `deleteHouse`, `getHouseFeed`, `getDepartmentHouseFeed`, and the four member add/remove functions).

### Verification
- **Live Postgres, real endpoints** (`docker compose up -d postgres` + local `.env`, matching U1's own verification technique): every route exercised via real HTTP calls (PowerShell/`Invoke-WebRequest`, this session's `curl` equivalent on Windows) — `GET /houses`, both feed routes (including the `::uuid` cast, the `overall_status IN ('approved','flagged')` filter, empty-department/empty-membership cases), `POST`/`DELETE /houses`, all four member routes, 403s for non-owner/non-creator, 404 for a nonexistent `house_id`, the dedup case (a video qualifying via both membership paths), the cross-creator KTD2a case, membership-row-untouched-but-video-vanishes-on-block, and every `POST /auth/upgrade` validation case (case-mismatch, whitespace-padded, unknown, and valid-exact-match).
- **`tests/test_houses.py`** (new, 36 tests) — live-DB integration tests (these functions do real SQL I/O, unlike `test_decision_engine.py`'s pure-logic module, so they can't be tested the same no-DB way; the file `pytest.skip`s cleanly at module level when `POSTGRES_URL` isn't set, matching this repo's no-DB-mocking-layer precedent rather than faking one). Covers House CRUD, `get_house_feed`'s union+dedup, `get_department_house_feed`'s exact-match behavior (including a direct regression guard for the confirmed `::uuid`-cast runtime-failure bug an earlier plan draft had), membership add/remove idempotency, and route-level 403/404/`_enrich()`-reuse checks via `TestClient`. All 36 pass; the pre-existing 14 `test_decision_engine.py` tests are unaffected (50 total).
- `py_compile` clean on all touched backend files; `tsc --noEmit` and `eslint` clean on `frontend/lib/api.ts`; all 171 pre-existing Vitest tests (including U3's `lib/houses.test.ts`) still pass.
- **Unrelated environment issue found and fixed during verification, not a code regression**: the pinned `passlib==1.7.4` in `requirements.txt` fails its own internal bcrypt self-test against newer `bcrypt` package releases (`ValueError: password cannot be longer than 72 bytes`) inside `pwd_context.hash()` — pre-existing in `POST /auth/register`, unrelated to any Houses code, only surfaced because this was the first time this session ran `register` against a fully fresh venv. Worked around locally for this verification pass by pinning `bcrypt==4.0.1`; not a change shipped in this PR (no `requirements.txt` pin was in U2's scope) — flagged here for whoever picks up dependency maintenance next.

## 2026-09-22 — Houses: Listing Page + Detail Route + Nav Entry (U4)

Frontend surface for browsing Houses — builds on U2's backend endpoints and U3's `frontend/lib/houses.ts` pure-logic module. This unit is UI-only: no backend or schema changes.

### `/houses` listing page (`frontend/app/houses/page.tsx`, new)
- Calls `listHouses()` on mount; renders a "Departments" section (built-in Houses, from the `builtIn` list) and a "Custom Houses" section (from `custom`), each item a tappable card — visual shape follows `frontend/app/search/page.tsx`'s existing card-list precedent (surface/border rows, chip-style badges) rather than a new layout language.
- Tapping a department card navigates to `/feed?house=department:<name>`; tapping a custom House card navigates to `/houses/[id]`.
- Custom House cards use `formatHouseMemberCount()` (U3) for the "3 creators · 12 videos" / singular / zero-member-omitted display text — verified via real-browser check, not just unit-test coverage of the formatter alone.
- A "Create a House" affordance is visible only when `isLoggedIn() && isCreator()` (mirrors `Upload`'s `creatorOnly` gating pattern) and opens an inline name/description form that posts to the real `createHouse()` client function, then navigates straight to the new House's `/houses/[id]` view — an empty House with no way to populate it would otherwise be a dead end.

### `/houses/[id]` detail route (`frontend/app/houses/[id]/page.tsx`, new)
- Reads the dynamic `id` segment, fetches `listHouses()` (there is no dedicated "get one House" endpoint — `GET /houses` already returns every custom House's `owner_id`, reused here rather than adding a new endpoint call) and compares `getUser()?.id` against the House's `owner_id`, following `app/profile/page.tsx`'s existing owner-comparison pattern.
- **Non-owner**: `router.replace`'s straight to `/feed?house=<id>` with no intermediate screen, per KTD7. Verified via real-browser check that no "Manage Members" content is ever visible to a non-owner during the redirect window (polled DOM text across the redirect, not just the final URL).
- **Owner**: sees a hero card, a working "View feed" link (`href="/feed?house=<id>"` — the same handoff a non-owner gets automatically), and a Manage Members section.
- **Scope boundary with U5 (explicit, load-bearing for this PR):** the Manage Members section ships as a clearly labeled placeholder/skeleton only — a "Coming soon" empty-state block, no functional search input or add/remove interaction. The real creator/video search-and-add and per-row remove UI is Implementation Unit U5's scope, to be built inside this same file once this PR merges. Verified via a real-browser DOM check that no `input[placeholder*="search"]`/`input[placeholder*="add"]` element exists in the owner view.

### Nav bar (`frontend/components/nav-bar.tsx`)
- One new `NAV_ITEMS` entry: `{ href: "/houses", label: "Houses", icon: <Building2 size={20} /> }`, no `creatorOnly` (visible to every logged-in user), placed between Search and Messages. `Building2` chosen per the plan's own Open Questions note that the exact icon is implementation-time taste.
- Confirmed via real-browser check that no other change was needed: the existing active-highlight logic (`pathname === item.href || pathname.startsWith(...)`) correctly highlights Houses on both `/houses` and `/houses/[id]`, and the badge-dot special-case (guarded by `item.href === "/messages"`) is unaffected.

### Verification
- `tsc --noEmit` — clean. `eslint` — 0 errors (3 pre-existing warnings in unrelated files, `<img>` LCP hints in `AttachmentMessage.tsx`/`AttachmentPicker.tsx`).
- `npx vitest run` — all 171 tests pass (including U3's 9 `lib/houses.test.ts` tests; no regressions).
- **Real-browser verification** (Playwright, temporary `npm install --no-save playwright` + `npx playwright install chromium` in this unit's worktree, removed after — this repo has no component-render test harness, confirmed by the plan, so this is the actual behavioral coverage for this unit): dev server run locally on a free port (3001; 3000 was already in use by another process) with `GET /api/backend/houses` and related feed/member-add calls stubbed via `page.route()` (the live EC2 backend's `/houses` route returned 404 at verification time — U2's backend code is merged to `main` but not yet deployed/restarted on the EC2 instance, an infra step outside this frontend-only unit's scope). 31 assertions across two scripts, all passing:
  - `/houses` renders both sections with real department names and custom House cards, correct member-count formatting (including the zero-creators/video-only case correctly omitting "0 creators").
  - "Create a House" affordance visible for a creator, hidden for a non-creator viewer.
  - Tapping the Cinematography department card navigates to exactly `/feed?house=department:Cinematography`.
  - Nav bar has exactly one `/houses` link, labeled "Houses", highlighted (non-transparent background) on both `/houses` and `/houses/[id]`.
  - Owner visiting `/houses/[id]` is NOT redirected, sees "Manage Members" + "Coming soon", no functional add-member input present, and a "View feed" link pointing at the correct `/feed?house=<id>` href.
  - Non-owner visiting the same `/houses/[id]` URL is redirected to `/feed?house=<id>` with the owner's Manage Members content never observed during the transition.
  - Submitting the create-House form POSTs `{name, description}` to `/houses` via the real `createHouse()` client function and navigates to `/houses/<new-id>` on success.
  - Screenshots captured and visually reviewed (cream theme, peach accent, consistent with `/search` and `/settings/privacy`'s established visual language) before cleanup.
- Playwright, its screenshots, and the two temporary verification scripts were all removed after verification (`npm uninstall playwright`); `package.json`/`package-lock.json` show no diff.

## 2026-09-23 — Houses: Feed Integration + Manage-Members UI (U5)

Final unit of the Houses navigation plan — wires the existing swipe feed to render House-scoped results and replaces U4's "Coming soon" placeholder with the real manage-members UI. No backend/schema changes; consumes U2's endpoints and U3's `parseHouseParam` exactly as shipped.

### `frontend/app/feed/page.tsx` — `<Suspense>` restructure + `house` param branch
- **Required structural change** (not optional, per the plan's own Risks section): the default export is now a thin `<Suspense fallback={null}><FeedPageInner /></Suspense>` shell; today's entire component body moved unchanged into `FeedPageInner`. Exact pattern match to `frontend/app/messages/compose/page.tsx`'s existing `MessagesSearchPageInner` precedent — required because `useSearchParams()` needs a Suspense boundary in this app's pinned Next.js version (16.2.9), confirmed via a real `next build` (`/feed` still prerenders as static content, `○`, with no build/prerender failure).
- Mount effect now reads `house` via `useSearchParams()`, parses it with `parseHouseParam` (U3): `null` → the existing `getFeed()` path, **byte-for-byte unchanged** (same enrouted/recommended bucket logic, same divider shape); `{kind: "department", name}` → `getDepartmentHouseFeed(name)`; `{kind: "custom", id}` → `getHouseFeed(id)` plus a parallel `listHouses()` call (no dedicated single-House GET endpoint exists) to resolve the House's real name for the section label and the current viewer's ownership for the empty-state branch.
- House-scoped `items` gets exactly one `SectionDivider` (the House/department name) instead of the Following/Recommended two-divider pattern (KTD4). The `feed` state (confirmed still write-only — no new reader was introduced) is left at its default `{enrouted: [], recommended: []}` for the House-scoped branch rather than synthesizing a fake bucketed shape.
- `current` resets to `0` whenever the House scope itself changes (covers client-side navigation between two different `/feed?house=` URLs without a remount, which the original single-fetch-on-mount effect never had to handle).
- Every piece of `SwipeCard`/`ThumbnailStrip`/gesture/action-button code is untouched — confirmed via real-browser check that swipe navigation, the action-button column, and the thumbnail strip all behave identically regardless of where `items` came from.
- **Known, accepted side effect, not a bug**: because a House-scoped `items` array always starts with its one divider at index 0, the existing divider-auto-skip (`setTimeout(goNext, 600)`) now fires unconditionally on every House-feed page load — a brief ~600ms section-label-only flash before the first video settles in. Verified this resolves cleanly to `1/N` (including the single-video case) with no stuck/glitched state.
- **Empty-state copy fix** (flagged during plan review): the default feed's "Upload filmmaking content to get started." literal copy is no longer reused verbatim for a House-scoped empty state, since uploading doesn't populate any specific House. Three variants now: default unscoped feed keeps its original copy; a non-owner visitor (any built-in House, or someone else's custom House) sees "No videos in this House yet." with no upload/manage call-to-action; the custom House's own owner sees "No members yet. / Add creators or videos to get started." with a working link to `/houses/[id]`'s manage view.
- Every `setState` call inside the mount effect is either inside a resolved `.then()`/async-IIFE callback or the async IIFE's post-`await` body — none synchronous at the top of the effect body, matching this repo's `react-hooks/set-state-in-effect` lint rule (same reasoning as `app/settings/privacy/page.tsx`'s own async-IIFE precedent, extended here to also cover a genuine mid-lifecycle `setLoading(true)` the privacy page's one-shot case never needed).

### `frontend/app/houses/[id]/page.tsx` — real manage-members UI
- Replaces U4's placeholder "Coming soon" skeleton with two real sections, **Creators** and **Videos**, following `app/settings/privacy/page.tsx`'s confirmed structural pattern (per-row pending-id during remove, filter-from-state-on-success, inline error banner) reused for its UI shape only — wired to U2's real `addHouseCreatorMember`/`removeHouseCreatorMember`/`addHouseVideoMember`/`removeHouseVideoMember` functions in `frontend/lib/api.ts`, not to `gatekept-api.ts`.
- Adding a member: debounced (400ms) search-as-you-type against the existing global `searchAll()` endpoint, matching `app/search/page.tsx`'s pattern exactly — both branches, creators and videos. Per KTD2a, the video-add search is deliberately **not** scoped to the owner's own uploads; it is the same global search any viewer would get from `/search`, since video-level House membership is cross-creator by design.
- Add/remove is optimistic-**after**-success only: a row is appended/removed from local state only once the corresponding API call has actually resolved, matching the confirmed pattern (not optimistic-before-success).
- **Real scope boundary, not an oversight**: there is no "list this House's current members" backend endpoint (`GET /houses` returns only counts; `GET /houses/{id}/feed` returns the unioned video list with no per-item indication of which membership path added it). The Creators/Videos lists are therefore session-local — they start empty on page load and grow/shrink only from this session's own add/remove actions. Adding a "view current members" endpoint would be new backend surface outside this unit's scope (U2 is already merged and frozen).
- Debounced-search effects follow `app/search/page.tsx`'s exact `handleInput` split (clearing results on an emptied query is handled in the input's `onChange` handler, not as a synchronous `setState` at the top of the debounce effect) to satisfy the same `react-hooks/set-state-in-effect` rule.

### Verification
- `tsc --noEmit` — clean. `eslint` — 0 errors (same 3 pre-existing unrelated warnings as U4, `<img>` LCP hints).
- `npx vitest run` — all 171 tests pass, no regressions (including U3's `lib/houses.test.ts` and `lib/feedItems.test.ts`).
- `next build` — clean production build; `/feed` still prerenders as static content (`○`), confirming the `<Suspense>` restructure introduces no build/prerender failure.
- **Real-browser verification** (Playwright, temporary install + `npx playwright install chromium`, removed after — same discipline as U1/U4): ran against a `next start` production server (not `next dev`) after confirming React Strict Mode's dev-only double-effect-invocation was producing a double divider-auto-skip that does not occur in the real, deployed build — cross-checked directly against both servers before settling on production-mode verification as the accurate signal. Backend calls stubbed via `page.route()` (the live EC2 backend still 404s on `/houses` — U2's backend code isn't deployed there yet, unrelated to this frontend-only unit). 24 assertions, 21 passing outright; the remaining 3 are an identical, pre-existing "500 Internal Server Error" console message from `nav-bar.tsx`'s unconditional (unrelated to Houses) realtime-WS-ticket fetch to the unstubbed Gatekept messaging backend — confirmed present on the plain default-feed scenario too, i.e. not a House-scoping regression:
  - **Default `/feed` (no `house` param) — the plan's own highest-risk regression guard**: renders identically to before this change — "Following" section label, correct video counter (`1 / 3`), a horizontal swipe gesture correctly advances to the next video (`2 / 3`), no uncaught page errors, no visible Suspense fallback flash.
  - Department-scoped feed (`?house=department:Editing`): shows only that department's videos, correct section label, correct count.
  - Custom-House-scoped feed: unions creator-membership and video-membership videos with no visual duplicates, section label shows the House's real name (resolved via the parallel `listHouses()` call).
  - Single-video House: divider-auto-skip resolves cleanly to `1 / 1`, never stuck on the divider.
  - Empty-state copy: a non-owner sees "No videos in this House yet." with none of the upload/manage-members call-to-actions; the custom House's own owner sees "No members yet." with a working "Manage members" link to `/houses/[id]`.
  - Manage-members flow: searching "Alice" surfaces a stubbed creator result, clicking it calls `POST /houses/{id}/members/creators/{id}` and the row appears in the Creators list; searching "cool" surfaces a stubbed video result, clicking it calls `POST /houses/{id}/members/videos/{id}` and the row appears in the Videos list; clicking Remove calls the matching `DELETE` endpoint and the row disappears.
- Playwright, its screenshots, and all temporary verification/debug scripts were removed after verification (`npm uninstall playwright`); `git status` confirms only `frontend/app/feed/page.tsx` and `frontend/app/houses/[id]/page.tsx` changed — `package.json`/`package-lock.json` show no diff.

## 2026-09-23 — Department List Expanded (9 → 28 Real Filmmaking Departments)

`DEPARTMENTS` (the creator-upgrade dropdown and, since the Houses feature, the built-in Houses list) grew from 9 generic categories to 28 real, industry-standard production departments — the kind of granularity that appears on an actual film/TV call sheet (department-head level, not individual job titles within a department — e.g. "Camera" as one entry, not "1st AC"/"2nd AC" listed separately, which would need a searchable picker instead of a plain `<select>`).

- New departments added: Producing, Camera, Grip & Electric, Art Department, Set Decoration, Costume Design, Hair & Makeup, Sound Recording, Music, Special Effects, Stunts, Casting, Locations, Production Management, Script Supervision, Continuity, Colorist / Post-Production, Animation, Transportation, Catering & Craft Services.
- The original 9 (Cinematography, Directing, Screenwriting, Editing, Sound Design, Visual Effects, Production Design, Acting, Other) are preserved verbatim and in their original relative order — any creator's existing `users.department` value keeps matching exactly, no migration needed.
- Both copies of the list (`frontend/app/profile/page.tsx`'s `DEPARTMENTS` constant, `backend/app/main.py`'s `DEPARTMENTS` constant — kept as two manually-synced copies per the Houses plan's own Open Question, not unified into a single source this round) were grown in lockstep and confirmed byte-for-byte identical via a direct diff of the extracted string arrays, not just eyeballed — a mismatch here would either reject a valid dropdown selection server-side (`POST /auth/upgrade` returns 400) or leave a real option permanently unreachable.
- `tests/test_houses.py`'s own small local `DEPARTMENTS` fixture (used only to seed a valid department name for test users, e.g. `department or DEPARTMENTS[0]`) does not need updating — it's not asserting against the full canonical list's contents or count, and its first entry (`"Cinematography"`) remains valid.

### Verification
- `tsc --noEmit` — clean. `eslint` — 0 errors (same 3 pre-existing unrelated `<img>` warnings). `py_compile` on `backend/app/main.py` — clean.
- `npx vitest run` — 171/171 tests pass, no regressions.
- Byte-for-byte parity between the two `DEPARTMENTS` copies confirmed via a direct diff of the extracted quoted-string arrays from both files (not just visual comparison).
- Real-browser check (Playwright, temporary install + removal, same discipline as every other unit this session): the profile page's department `<select>` renders all 29 options (28 departments + "Other") in the correct order, confirmed via reading the live DOM's `<option>` list, not just the source array. No layout break from the longer list — a native `<select>` handles this option count without any UI change needed.

## 2026-09-23 — Department List Refined: Craft/Creativity Only

Following user review of the previous department expansion, four departments judged to be logistics/support rather than hands-on craft or creative work were removed and replaced with four genuine, distinct craft roles — same total count (28 + "Other" = 29), no net change in list size.

- **Removed** (logistics/support, not craft): Locations, Continuity, Transportation, Catering & Craft Services.
- **Kept from the prior round** on explicit instruction despite initially being flagged as borderline: Production Management.
- **Added** (real, distinct craft roles not already covered by the existing list): Choreography (dance/fight/movement direction — distinct from Stunts' physical-safety/execution focus), Foley Artistry (the hands-on sound-effects craft — distinct from Sound Design's conceptual work and Sound Recording's production capture), Storyboarding / Previsualization (a distinct visual-planning craft — distinct from Screenwriting/Directing), Prosthetics & Creature Design (a distinct sculptural/makeup-adjacent craft — distinct from Hair & Makeup and Special Effects).
- Confirmed via the live backend (`GET /search?q=<removed department name>`, all four) that no real creator had selected any of the four removed departments in the few hours they were live, so no `users.department` value needed migrating.
- Both copies of the list (frontend `DEPARTMENTS` constant, backend `DEPARTMENTS` constant) updated in lockstep and confirmed byte-for-byte identical via a direct diff, same discipline as the prior expansion.

### Verification
- `tsc --noEmit` — clean. `eslint` — 0 errors (same 3 pre-existing unrelated `<img>` warnings). `py_compile` on `backend/app/main.py` — clean.
- `npx vitest run` — 171/171 tests pass, no regressions.
- Byte-for-byte parity between both `DEPARTMENTS` copies confirmed via diff.
- Real-browser check (Playwright, temporary install + removal): confirmed via the live DOM that all 4 removed departments are genuinely absent from the rendered `<select>`, all 4 new departments are present, `Production Management` is retained, and the total option count is exactly 29.

## 2026-09-23 — Multi-Department Content Tagging

A video's primary department was previously implicit — derived at read time by joining to its creator's `users.department`. Creators can now additionally tag an upload with up to 5 more departments it's relevant to (e.g. a Cinematography-primary short that's also Choreography and Costume Design relevant), and the video surfaces in every tagged department's built-in House feed, not only its creator's home department.

### Data model
- New table `video_department_tags` (`video_id, department, is_primary, tagged_at`, composite PK `(video_id, department)`). One row per (video, department) pairing — a genuine many-to-many join, not a column, since a video needs zero-to-many additional tags plus exactly one primary.
- **DB-enforced, not just app-level discipline**: a partial unique index (`idx_video_dept_tags_one_primary ON video_department_tags (video_id) WHERE is_primary`) makes "more than one primary row per video" structurally impossible to write, even via a direct SQL insert that bypasses the application layer entirely.
- The primary tag is written once, at upload time, from the uploader's *current* `users.department` — frozen from that point on. It does not live-track a creator's department if they change it later (verified via a dedicated test: upgrading a creator to a new department after upload leaves their existing videos' primary tags untouched).

### Backfill — critical edge case caught via regression testing, not the original design
Every video uploaded before this feature shipped has zero `video_department_tags` rows. Since `get_department_house_feed` is now tag-based with no fallback to `users.department`, an unpatched pre-existing video would have silently vanished from every built-in department feed the moment this deployed — this was not anticipated in the original design doc and was only caught because `tests/test_houses.py`'s existing suite regressed against a live database. Fixed with an idempotent backfill in `_ensure_schema()`: every video with zero tag rows gets a primary tag equal to its creator's *current* department, on every startup, `WHERE NOT EXISTS` so it can never overwrite a real tag set written after this feature shipped.

### API surface
- `POST /videos` gains an optional `departments` form field (comma-separated additional departments; primary is never client-supplied — the server always derives it server-side from `users.department`, regardless of what the client sends). Validated against the canonical `DEPARTMENTS` list (400 on any unknown value) and capped at `MAX_ADDITIONAL_DEPARTMENTS = 5` (400 if exceeded).
- New `POST /videos/{id}/departments` / `DELETE /videos/{id}/departments/{department}` — owner-only (new `_require_video_owner` dependency, mirrors `_require_house_owner`), for post-upload editing of *additional* tags only. The primary tag is not reachable through either route at all — "cannot be removed" is enforced by never exposing the operation, with a second layer of defense at the `db.py` level (`remove_video_department_tag` silently no-ops if the target row `is_primary`), so the guarantee holds even against a direct DB-layer call that skips the route entirely.
- `get_department_house_feed` rewritten from `WHERE u.department = %s` (creator's own department) to `WHERE EXISTS (SELECT 1 FROM video_department_tags WHERE department = %s)` (any tag match) — a deliberate behavior change, not a pure refactor.
- `_enrich()` now batch-attaches `department_tags` to every feed row (`get_department_tags_for_videos`, one query for N videos, not N+1).

### Frontend
- `frontend/app/upload/page.tsx`: department picker below the format toggle. Primary department renders as a locked, non-interactive chip (🔒 + "— Main Department" label, not color alone) sourced from the locally-cached user for display only — never sent as part of the upload, since the server independently re-derives it. Additional-department buttons exclude the primary from their own option list entirely (never offered as a duplicate pick, not just rejected after the fact) and disable further selection past the 5-tag cap.
- Post-upload result card and `GET /videos/{id}/status` both render the full tag set with the same locked/unlocked visual distinction.

### A real bug found via testing, not code review
FastAPI does not automatically treat a plain `str` parameter as a form field when the route also has an `UploadFile` parameter — it needs explicit `Form(...)` typing. Without it, the `departments` field silently failed to bind, and the intended 400 validation (invalid department name, too many additional departments) never fired — a request with a bad department fell straight through to the real S3 upload call instead of being rejected. Caught by running the actual test suite against a live Postgres + attempted-S3 call (not by reading the code), fixed by declaring `departments: str = Form("")`.

### Verification
- `tests/test_department_tags.py` (new, 26 tests): schema/backfill correctness, primary-tag DB-level uniqueness enforcement, add/remove-tag defense-in-depth on the primary, batch tag fetch, tag-based feed membership, upload-route validation ordering, ownership checks on the tag-management routes — all run against a live disposable Postgres (`docker compose up -d postgres`), not mocked.
- `tests/test_houses.py`: `make_video` fixture updated to also write a primary tag (matching what a real upload now does), its local `DEPARTMENTS` stub resynced to the real 29-department list (was stale at the original 9) — both were pre-existing gaps this change surfaced, not new to this feature. Full 36-test suite passes with no other changes.
- 3 of the 26 new tests are marked `skipif` without real AWS credentials (they need a successful S3 upload to complete) — the other 23, including both validation-ordering tests, always run. `tests/test_decision_engine.py`'s 14 tests unaffected.
- `tsc --noEmit` — clean. `eslint` — clean on both modified frontend files.
- Not yet deployed to EC2 as of this entry.

## 2026-09-23 — Renamed to Cineaste

Product renamed from "Editor Club" to "Cineaste" across all user-visible branding and doc/prose titles.

- **User-visible**: nav bar full name (`frontend/components/nav-bar.tsx`) and collapsed monogram ("EC" → "Ci"); browser tab title (`frontend/app/layout.tsx`) — this was actually still "Redactor" (a leftover from an even earlier name, never updated when the product became "Editor Club"), so this fixes a real stale-title bug, not just a rename; the login page's own brand heading (`frontend/app/page.tsx`) had the same "Redactor" staleness — also fixed; creator-profile bio fallback text, search page empty-state copy, messenger compose empty-state copy.
- **Doc/prose titles**: `CLAUDE.md`, `README.md`, `docs/architecture.md`, `docs/moderation_policies.md`, `docs/project_status.md` top-level headers; `docs/private-notes.md` (untracked, local-only, updated for consistency); `scripts/scan-repo.py`'s CLI description and banner output; code comments referencing the product name by prose in `backend/app/pillars/duplicate_content.py`, `backend/app/pillars/filmmaking_relevance.py`, `frontend/lib/gatekept-api.ts`, `frontend/components/CryptoNotice.tsx`, `frontend/app/messages/compose/page.tsx`, `frontend/next.config.ts`.
- **Deliberately NOT renamed** (real infrastructure identifiers, not branding — confirmed with the user before proceeding): the live DNS hostname `redactor-api.duckdns.org`, systemd service names (`redactor-api`/`redactor-celery`), CloudFormation stack/resource names and tags (`infra/cloudformation.yml`, `docs/private-notes.md`'s `editorclub-v1` stack name), the `redactor_token`/`redactor_user` localStorage key prefixes (renaming these would silently log out every existing user), the Postgres password, and the CI bot username (`editor-club-bot` in `.github/workflows/update-baseline.yml`). Renaming these is a separate, riskier infra task (DNS, EC2 service restarts, redeploys, forced logout) explicitly deferred.
- **Deliberately NOT renamed**: dated historical changelog/project_status entries (e.g. "Redactor MVP (2026-09-08)", "Editor Club — Social Features (2026-09-10)") — these describe what the product was actually called on that date and are left as an accurate historical record, same treatment as this file's other dated entries.
- **GitHub repo**: renamed via `gh repo rename`; local remote URL updated to match.

### Verification
- `tsc --noEmit` — clean. `eslint` — clean on every modified frontend file. `py_compile` — clean on both modified pillar files and `scripts/scan-repo.py`.
- `scripts/scan-repo.py` run post-rename — 0 new issues (banner itself now reads "Cineaste — Repo Health Scan").
- Full repo-wide case-insensitive grep for "editor club" / "editor-club" / "editorclub" confirms only the deliberately-preserved infra identifiers and historical dated entries remain.

## 2026-09-23 — Renamed to Misence

Product renamed a second time, from "Cineaste" to "Misence", across the same user-visible branding and doc/prose titles the prior rename touched. Same file set as the Editor Club → Cineaste rename (see entry immediately above), applied again.

- **User-visible**: nav bar full name (`frontend/components/nav-bar.tsx`) and collapsed monogram ("Ci" → "M"); browser tab title (`frontend/app/layout.tsx`); login page brand heading (`frontend/app/page.tsx`); creator-profile bio fallback text; search page and messenger compose empty-state copy.
- **Doc/prose titles**: `CLAUDE.md`, `README.md`, `docs/architecture.md`, `docs/moderation_policies.md`, `docs/project_status.md` top-level headers; `docs/private-notes.md` (untracked, local-only); `scripts/scan-repo.py`'s CLI description and banner output; prose code comments in `backend/app/pillars/duplicate_content.py`, `backend/app/pillars/filmmaking_relevance.py`, `frontend/lib/gatekept-api.ts`, `frontend/components/CryptoNotice.tsx`, `frontend/app/messages/compose/page.tsx`, `frontend/next.config.ts`.
- **Deliberately NOT renamed** — same reasoning and same list as the prior rename: the live DNS hostname, systemd service names, CloudFormation resources, `redactor_token`/`redactor_user` localStorage keys, the DB password, the CI bot username, and dated historical changelog/project_status entries (including the "Renamed to Cineaste" entry above, which stays as an accurate record of that intermediate rename).
- **GitHub repo**: renamed from `cineaste-app` to `misence-app` via `gh repo rename`, local remote updated to match, same as the prior rename. (The Vercel deployment domain is tracked separately, outside this repo — not part of this change.)

### Verification
- `tsc --noEmit` — clean. `eslint` — clean on every modified frontend file. `py_compile` — clean on both modified pillar files and `scripts/scan-repo.py`.
- `scripts/scan-repo.py` run post-rename — 0 new issues (banner now reads "Misence — Repo Health Scan").
- Repo-wide case-insensitive grep for "cineaste" confirms only this file's own historical dated entries remain.

## 2026-09-23 — Long-Press Hint Affordance (fixes #32)

The feed's long-press gesture (hold 3s to open the jump-to-video thumbnail strip, PR #28) had zero on-screen visual cue that it existed — the only affordance was a screen-reader-only hint, invisible to sighted users. Flagged in issue #32 as an accepted-but-unaddressed tradeoff.

- **The cue**: a subtle pulsing ring (56px circle, `rgba(255,255,255,0.55)` border) centered on the card, shown only for the first `LONG_PRESS_HINT_VIDEO_COUNT` (3) videos of a session — matches the issue's own suggested direction ("a subtle pulsing ring or small icon, shown only on the first N videos of a session"). Additive to `SwipeCard`'s existing overlay layer; does not touch the swipe-hint-arrow (`isFirst`/`isLast`) logic at all.
- **Dismissal, two independent paths, both required by the acceptance criteria**: (1) the cue simply stops rendering once `videoIdx >= 3` within a single sitting, and (2) it's dismissed for the rest of the session the moment the user actually long-presses (`openThumbnailStrip` now also calls `markLongPressHintDismissed()`, writing a `sessionStorage` flag) — so a user who's already discovered the gesture never sees it again this session, even if they scroll back to video 1.
- **`prefers-reduced-motion`**: reads the same way `ThumbnailStrip.tsx` already does (`window.matchMedia`); under reduced motion the ring renders as a static circle at fixed `opacity: 0.55` with no `animation` and the `<style>` keyframe block isn't even injected, rather than just disabling the animation property on an otherwise-present stylesheet.
- **Session-flag mechanism is new, minimal infrastructure** — `frontend/app/feed/page.tsx` had no first-run/session-flag mechanism before this fix (confirmed via search, matching the issue's own Notes section). Follows the exact `sessionStorage`-gated idiom `frontend/lib/gatekept-api.ts`'s `ensureRegistered()` already established elsewhere in this codebase, including the same fail-toward-hidden posture if storage is blocked (private browsing, etc.) rather than crashing.
- Keyframe styling (`<style>{...}@keyframes long-press-hint-pulse...</style>`) follows this codebase's existing plain-`<style>`-tag pulse-animation precedent (`app/search/page.tsx`, `app/houses/[id]/page.tsx`, `app/messages/compose/page.tsx` all use the identical pattern for their own loading-dot pulses) rather than introducing a new animation approach.

### Verification
- `tsc --noEmit` — clean. `eslint` — clean on `app/feed/page.tsx`.
- Real-browser check (Playwright, temporary install + full removal after — this codebase's established discipline for gesture-adjacent UI, per the issue's own explicit acceptance criterion): ran against a genuinely local backend + seeded videos (a stale `frontend/.env.local` from earlier local-dev work was pointing the dev proxy at the real production EC2 API instead of `localhost:8088` — caught mid-verification when a screenshot showed a real production account instead of the seeded test data; moved the file aside for the duration of the check, restored it afterward, seeded rows deleted from the shared local Postgres volume).
- Confirmed via screenshot: the ring is visible mid-pulse-cycle on video 1/5 (a screenshot taken during the animation's near-zero-opacity phase initially looked like a false negative — resolved by inspecting the DOM directly, which confirmed the element and its `animation-name` were correctly present and running; a second screenshot timed earlier in the cycle shows it clearly).
- Confirmed absent past video 3 (video 4/5 has no ring).
- Confirmed it reappears on navigating back to video 1 (not a permanent one-time dismissal just from scrolling past the gate).
- Confirmed permanently dismissed (ring absent even back on video 1, `sessionStorage` flag set to `"1"`) after triggering the strip once via the existing Enter-key equivalent.
- Confirmed the reduced-motion variant: static ring at fixed opacity, no `<style>` keyframe tag injected, screenshotted directly.

## 2026-09-23 — Right-Sized Feed Ranking, Per-Video Credits, "Not Interested"

A scoped-down version of a general feed/recommendation design doc's principles (weighted-combination ranking, negative-feedback controls) adapted to this app's actual scale — no ML model, no candidate-generation funnel, just an explainable SQL scoring formula. Also closed two real, previously undiscussed gaps this surfaced: credits were unauthenticated/spammable/creator-lifetime-only, and the `recommended` bucket's sort couldn't tell a genuinely good new video apart from an old video by a once-popular creator.

### Per-video, per-user credits (replaces the old counter entirely)
- New `video_credits` table (`video_id, user_id`, PK on the pair) — a real toggle: credit once, tap again to un-credit. Replaces `POST /videos/{id}/credit`'s old behavior, which had **no auth check and no dedup** — anyone, including logged-out requests, could spam it infinitely with no record of who credited what.
- `users.credits` is now a **frozen historical total**, deliberately no longer written to — an old unauthenticated counter has no real per-user record to reconcile, so it can't be trusted as a ranking signal going forward. `get_creator_profile` and `search`'s creator listing were both rewritten to compute a **live** sum from `video_credits` instead, so a creator's displayed credit count doesn't silently go stale the moment this shipped.
- Fixed a real pre-existing bug this surfaced: the feed's star button's filled/count state was purely client-side session state (`credited[job.job_id]`), never read from the server — every video showed 0 credits and an unfilled star on every page load, even if hundreds of people had already credited it, until the CURRENT viewer credited it themselves in that same session. `_enrich()` now attaches `credited`/`credit_count`/`comment_count` (batch-fetched, not N+1) to every feed row.

### Feed ranking (replaces the rigid `u.credits DESC, created_at DESC` sort)
- New weighted score: `3 * credits + 2 * comments + 1 * recency_decay(age)`, with recency using an exponential half-life (48h) rather than a hard cutoff — the same decay shape Reddit/Hacker News-style rankings use, computed entirely in SQL so Postgres does the sort, not the app.
- The OLD sort ranked by the **creator's lifetime credit total**, not the video's own quality — meaning a popular creator's oldest, most-forgotten video would always outrank a brand-new great video from anyone else. The new score is per-video.
- The `enrouted` (followed-creator) bucket is deliberately **NOT** re-ranked by this score — a follow means "show me everything," so it stays purely chronological; only `recommended` uses the weighted score.

### "Not interested"
- New `dismissed_videos` table (per-user, per-video) and `POST /videos/{id}/dismiss` — hides one video from that viewer's feed going forward, filtered via a `NOT EXISTS` anti-join in `get_feed` (applies to both `enrouted` and `recommended` — dismissal is a stronger, more explicit signal than a follow). Removed from the current session's `items` immediately on click, not just excluded from the next fetch, so it doesn't reappear if the viewer swipes back before reloading.

### Two real, unrelated bugs found via browser verification (not the original design)
- **Divider auto-skip double-fire**: `setTimeout(() => goNext(), 600)` ran unconditionally in the render body (not a `useEffect`), so React StrictMode's dev-mode double-render could schedule two independent timers, both firing `goNext()` and skipping an extra video past the intended first one on load. Confirmed via a 3-item test feed opening on item 3 instead of item 1. Fixed by moving it into a `useEffect` keyed on `[current, items, goNext]` with proper timer cleanup, so at most one timer per divider-landing can ever fire.
- **Pointer capture blocked every action button**: `SwipeCard`'s `onPointerDown` called `setPointerCapture()` unconditionally, which — per the Pointer Events spec — redirects every subsequent pointer/mouse event (including the eventual click) back to the capturing element regardless of where the cursor actually is. This broke real clicks on ALL FIVE action buttons (Credits, Comment, Share, Save, Not interested) and the Enroute pill, not just the new ones — confirmed via raw mouse-coordinate click tracing showing a click at the Comment button's exact screen position landing on the card's root div instead. Fixed by checking `e.target.closest("button, a, [role='button']")` before claiming the gesture at all, letting native click behavior pass through untouched for any nested interactive element.

### Verification
- `tests/test_feed_ranking.py` (new, 28 tests, live Postgres): credit toggle dedup, per-video/per-viewer credit state, batch engagement counts, dismissal excluding both feed buckets and being per-user not global, the ranking score genuinely letting an older credited video outrank a newer uncredited one, comments contributing to rank, the enrouted bucket staying chronological, route-level auth checks, and `get_creator_profile`'s credits field being live not frozen.
- `tests/test_houses.py` + `tests/test_department_tags.py` — full existing suites re-run, no regressions (106 total passed, 3 pre-existing S3-gated skips).
- Real-browser verification (Playwright, temporary install + full removal after) against a genuinely local backend + seeded data (same `.env.local`-pointed-at-production gotcha from the prior entry recurred and was worked around the same way): confirmed ranking order, star-count persistence across reload (credit → reload → un-credit → reload → re-credit → reload, each step server-confirmed via direct DB inspection, not just UI trust), dismiss removing a video from both the current session and a subsequent fetch, and — after the pointer-capture fix — real mouse clicks (not Playwright's locator `.click()`, which doesn't reproduce the bug) landing on Comment, the star, Not interested, and Enroute correctly.
- `tsc --noEmit` — clean. `eslint` — clean on all four modified/new frontend files.
- Not yet deployed to EC2 as of this entry.

## 2026-09-24 — Security Hardening Phase 0 + Phase 1 (JWT Fixes + CI Security Agent)

Implements the first two phases of the security/privacy hardening plan (the two live vulnerabilities, plus an automated SAST/dependency-scan gate wired into the real existing `pr-review-bot.yml` pipeline) — no ML, no new pipeline, extends what already existed.

### Phase 0 — two live vulnerabilities, fixed
- **JWTs now expire** (`JWT_EXPIRY = timedelta(hours=24)`): every token previously had no `exp` claim at all and was valid forever with no revocation mechanism. `python-jose`'s `jwt.decode()` validates `exp` automatically when present, raising `ExpiredSignatureError` (a `JWTError` subclass) — every one of `main.py`'s 9 existing `except JWTError:` blocks already catches it correctly with zero changes needed at the decode call sites.
- **`JWT_SECRET` no longer has a hardcoded fallback.** It previously defaulted to `"dev-secret-change-in-prod"` if the env var was unset — a misconfigured production deploy would silently sign every token with a secret visible in the app's own source history. Now raises `RuntimeError` at import time if unset, matching `config.py`'s existing `POSTGRES_URL` pattern exactly.
- A token minted without `exp` (e.g. by an older client) remains valid per the JWT spec — this only changes what NEW tokens contain, it doesn't retroactively invalidate existing sessions.

### Phase 1 — automated security agent in CI
- New `security-scan` job in `.github/workflows/pr-review-bot.yml`, parallel to `artifact-scan`/`regression-tests` (same `needs: lint-typecheck` pattern), wired into `decision`'s required-checks list via a new `--check security-scan=...` argument to `scripts/review_bot.py` (needed zero code changes inside that script — it already accepted arbitrary `name=status` pairs).
- Tools: `bandit` (Python SAST), `pip-audit` (Python dependency CVEs), `npm audit` (JS dependency CVEs). `gitleaks` (content-based secret scanning) deliberately deferred — needs a GitHub App/license setup this session couldn't provision; noted as a real follow-up, not silently dropped.
- New `scripts/security_gate.py` aggregates all three tools' JSON output and decides pass/fail, following `compare_baseline.py`'s exact philosophy: block only on **new** findings at or above `--min-severity` (default `high`) that aren't already in `.ci/security-baseline.json` — a deliberately-reviewed acceptance record (finding id + a written reason per entry), never auto-generated. A first real run against this repo found 2 low-confidence bandit false-positives (f-string SQL interpolation of module-level constants, not user input) and genuine pre-existing dependency CVEs — a gate that blocked on all of that on day one would be permanently red, the same failure mode `compare_baseline.py`'s own "new regressions only" design already avoids for the test suite.

### A real, pre-existing CI gap found and fixed in the same PR
`regression-tests` never set `POSTGRES_URL`, so `test_houses.py`, `test_department_tags.py`, `test_feed_ranking.py`, and the new `test_auth_security.py` — 92 of 112 local tests — silently `pytest.skip()`'d in CI on every single run, every time, since `test_houses.py` was first added. Only `test_decision_engine.py`'s 14 pure-logic tests ever actually ran; CI reported a clean-looking "X passed, 3 skipped" that read as correctly configured rather than a real coverage gap. Fixed by adding a `postgres:15-alpine` service container (GitHub Actions' native support, no new infrastructure) to `regression-tests` and setting `POSTGRES_URL`/`JWT_SECRET` env vars for the job. Found while auditing the exact current pipeline shape to design where the new `security-scan` job should slot in — fixed here since a security gate is only as useful as the regression suite it sits beside actually exercising real code paths.

### `backend/requirements.txt` — closed a real dependency-drift gap, and fixed a genuine CVE
`passlib`, `python-jose`, `boto3`, and `python-dotenv` are all directly imported by `main.py`/`storage.py`/`config.py` but were never listed in `requirements.txt` — installed only ad hoc via `infra/cloudformation.yml`'s EC2 UserData. This meant a plain `pip install -r requirements.txt` (the CI job's own install step) could never actually import `app.main` at all; it only "worked" in CI because `POSTGRES_URL` being unset meant every test file that would have exercised the import silently skipped first (see above). Added all four, with `bcrypt==4.0.1` pinned explicitly — `passlib` 1.7.4 cannot detect newer `bcrypt` releases' version string, which breaks `CryptContext.hash()` outright (confirmed locally); the same pin CloudFormation's UserData already uses.

Running `pip-audit` for real also surfaced a genuine, directly-relevant CVE: `python-multipart` 0.0.20 (handles every `POST /videos` file upload) had several known vulnerabilities including a path-traversal issue (not exploitable here — this app doesn't set the `UPLOAD_DIR`/`UPLOAD_KEEP_FILENAME` config the CVE requires) and real parser-level DoS issues (exploitable regardless of config). Bumped to `0.0.32` (latest, fixes all of them); `python-jose` bumped `3.3.0` → `3.4.0` and `python-dotenv` `1.0.1` → `1.2.2` for the same reason, both confirmed safe (no breaking API surface touched by this app's narrow usage). Full local test suite re-run after each bump — 112 passed, 3 skipped, no regressions, including the multipart-form-data upload-validation tests that directly exercise the bumped parser.

### A second real gap, found only once the PR was actually pushed and CI ran
Local verification ran everything through a venv that had `httpx` installed as a side effect of an earlier `pip install fastapi[all]` — masking that `httpx` (required at runtime by `fastapi.testclient.TestClient`, which every route-level test in `test_houses.py`/`test_department_tags.py`/`test_feed_ranking.py`/`test_auth_security.py` uses) was never listed in `requirements.txt` either, and FastAPI only declares it as an optional extra, not a hard dependency. This bug **predated this PR** — it was invisible before because the same missing-`POSTGRES_URL` gap this PR fixed meant those test modules always skipped at collection, before ever reaching the `TestClient` import. The first real CI run after the Postgres service container landed failed with 34 `RuntimeError: The starlette.testclient module requires the httpx package to be installed` errors — exactly the class of "fixing one masking bug unmasks the next one" this PR had already hit once with the `passlib`/`jose`/`boto3`/`dotenv` gap. Added `httpx==0.28.1` to `requirements.txt`; re-verified with a completely fresh venv installing *only* `requirements.txt` (no `fastapi[all]` shortcut) to confirm this was the actual, complete fix and not another partially-masked gap — 112 passed, 3 skipped, matching local results exactly.

### Verification
- `tests/test_auth_security.py` (new, 6 tests, live Postgres): app import genuinely fails without `JWT_SECRET` / succeeds with it set, login response tokens carry a real `exp` claim within the expected window, an expired token is rejected on a protected route, a not-yet-expired token is accepted, and a token with no `exp` claim at all (backward compatibility) still works.
- Full suite re-run after every change (dependency bumps, JWT fixes, requirements.txt reconciliation) — 112 passed, 3 pre-existing S3-gated skips, zero regressions throughout.
- Re-verified with a fresh venv installing *only* `requirements.txt` (matching CI's exact install step, no local shortcuts) after the `httpx` fix — 112 passed, 3 skipped, confirming CI will now genuinely pass, not just pass locally.
- `scripts/security_gate.py` verified end-to-end against real scanner output from this actual codebase (not synthetic fixtures) at every stage: confirmed it correctly blocks (exit 1) before the baseline existed, confirmed a real pip-audit output-duplication bug (the same CVE ID appearing twice per package when reachable via more than one resolution path) and fixed it with proper dedup, confirmed severity thresholding correctly separates blocking/below-threshold findings, confirmed a clean pass (exit 0) once every remaining finding was either fixed or deliberately baselined with a written reason. Re-confirmed clean after the `httpx` addition (no new CVEs introduced).
- `python -m py_compile` — clean on `security_gate.py`. YAML syntax validated for the modified workflow file.
- Not yet deployed to EC2 as of this entry (Phase 0's fixes are backend-only and will take effect on the next real deploy).

## 2026-09-24 — R&D Agent Department: Scaffolding (Phase 0 of the Design Doc)

Implements the code/repo-scaffolding half of the previously-published R&D multi-agent department architecture doc — the half verifiable without provisioning `ANTHROPIC_API_KEY` or spending real API budget. See `docs/rd-department-setup.md` for the exact line between what's built-and-verified versus built-but-untested in this entry.

### Real corrections to the published design, found via primary-source research
The published architecture doc flagged its headless-CLI flag examples as unverified and told a future implementer to confirm them first. Doing that research for real (against `code.claude.com/docs/en/headless`, `code.claude.com/docs/en/github-actions`, and the `anthropics/claude-code-action` repo's own `action.yml`/`docs/usage.md`, not a third-party summary) found one real correction: **there is no `--max-budget-usd` or similar dollar-cap flag** — an earlier research pass had invented one. The real, confirmed cost controls are `--max-turns`, GitHub Actions' own `timeout-minutes`, and a `concurrency` group — all now wired into `rd-department.yml`. Everything else the design doc named (`--bare`, `-p`, `--allowedTools`, `--output-format json` with a real `session_id` field, `--continue`/`--resume` for session continuation across separate invocations, `--permission-prompts none`) was confirmed real and exact, including a complete first-party "Run on a schedule" example workflow that validated the overall shape of `rd-department.yml` directly.

### Built and fully verified (no API key needed)
- `docs/plans/templates/rd-proposal-template.md` — the plan-document format a Worker Agent's proposal must follow; extends this repo's existing human-authored `docs/plans/*.md` convention (KTDs, Scope Boundaries, per-unit Implementation Units) with a Decision Record section per the design doc's joint-decision requirement.
- `docs/rd-research-log.md` — append-only cycle history, seeded empty.
- `scripts/check_worker_file_scope.py` — enforces the design doc's "no worker touches a file outside its assigned unit's declared file list" rule. Parses a plan's `**Files:**` sections and fails closed (exit 1) on any changed file outside the declared set, a missing plan, or an unparseable unit.
- `scripts/compute_worker_matrix.py` — computes a dependency-ordered wave schedule from a plan's `**Dependencies:**` annotations (topological sort; fails closed on an unknown dependency reference or a cycle).
- `.github/workflows/rd-approval-watcher.yml`'s `validate-approval` job — confirms a PR is genuinely plan-only (touches nothing outside `docs/plans/`, exactly one new file) and, for the `/approve`-comment trigger path, that the commenter actually has write access. No Claude invocation in this job at all.

### Two real parsing bugs found via testing against this repo's OWN real plan doc, not synthetic fixtures
Both scripts were deliberately tested against `docs/plans/2026-09-22-001-feat-houses-navigation-plan.md` — a real, already-merged plan this session itself produced — rather than only hand-crafted fixtures, specifically to catch format assumptions that don't hold against how this repo's plans are actually written:
- `check_worker_file_scope.py`: the real document's `**Files:**` entries are `` - `path` — rationale text ``, not a bare path per line as originally assumed. A naive "whole line must be just the path" parser silently returned an empty list for every real unit. Fixed to extract only the leading backtick-quoted path, ignoring trailing prose.
- `compute_worker_matrix.py`: the real document's `**Dependencies:**` lines carry trailing parenthetical rationale on the same line — e.g. U3's real line is `"None (can be built in parallel with U1/U2 against a typed placeholder shape)."`. A naive "find every `U<n>` token on the line" parser incorrectly computed U3 as depending on U1 and U2, when the line explicitly says the opposite. Fixed by stripping parenthetical content before extracting dependency ids — confirmed correct by comparing the resulting computed schedule (`[U1,U3] → [U2] → [U4] → [U5]`) against this session's own real historical execution of this exact plan (which ran U4+U5 in parallel manually, taking on a risk the corrected automated schedule no longer does, since U5's real Dependencies line does list U4).

### Built but explicitly NOT verified end-to-end — see `docs/rd-department-setup.md`
- `.github/workflows/rd-department.yml` (R&D Decision Agent → Tech Lead Agent, session-resumed) — cron trigger left commented out; `workflow_dispatch` with a `dry_run` input (default `true`) is the only way to invoke it until `ANTHROPIC_API_KEY` is provisioned, at which point it fails its own precheck step with a clear message rather than erroring confusingly.
- `.github/workflows/rd-approval-watcher.yml`'s `dispatch-workers` job — computes and reports the wave schedule (using the now-tested `compute_worker_matrix.py`), then stops; the actual per-unit Worker Agent invocation step is a documented `TODO`, deliberately left unwritten rather than shipped with unverified `claude_args` syntax nobody could catch was wrong until a real cycle failed.

### Verification
- `tests/test_check_worker_file_scope.py` (17 tests) and `tests/test_compute_worker_matrix.py` (17 tests) — pure-logic, no DB/network dependency, same category as `test_decision_engine.py`; all verified against the real Houses plan doc, not only fixtures.
- Full local suite (`test_decision_engine.py` + the two new files, 48 tests) — all pass. The remaining 112 live-DB tests correctly skip locally without `POSTGRES_URL`/Docker running in this pass, same as always; unaffected by this change and will run normally in CI's existing Postgres-service-container job.
- Both new workflow YAML files parsed successfully with PyYAML (the `on:` → boolean-`True` key coercion some checks flag is a known PyYAML 1.1 artifact, confirmed present on the existing, already-working `pr-review-bot.yml` too — not a real syntax problem).
- `scripts/scan-repo.py` — 0 new issues; both new scripts are referenced by the new workflow files, so neither is flagged as dead code.
- Not deployed anywhere — this is CI/tooling scaffolding, not an application feature with a runtime deploy target.

## 2026-10-29 — Pipeline hardening: real concurrency, retries, fail-closed, perceptual dedup, observability

### Why
`asyncio.gather` over the four pillars gave no concurrency: every pillar was an `async def` whose body made blocking calls (`boto3`, `urllib`, OpenCV) with no `await`, so each ran to completion before the next started. Failures were also masked — a pillar error returned a hash-seeded *mock* score, so a failed adult-content check could silently produce a verdict.

### Changes
- **Concurrency**: each pillar's body is now `_check_blocking()`; `check()` is `await asyncio.to_thread(_check_blocking, job_id)`. Controlled simulation (4 stub pillars, 1.0 s blocking each): 4.00 s before → 1.01 s after. Not a production measurement.
- **Retries + fail-closed**: pillars raise `PillarError` (new, `pillars/common.py`) instead of returning a mock score when configured to use a real backend. `process_video` retries on `PillarError` with exponential backoff + jitter (2 s base, 60 s cap, max 3 retries). When retries are exhausted `ModerationTask.on_failure` sets `status = failed`, `overall_status = needs_review` and pushes the job to the dead-letter list. `needs_review` is outside the `('approved', 'flagged')` filter used by every feed/search query, so the video stays hidden. (Marking it `flagged` would have *published* it — flagged videos are visible.)
- **Mock fallback narrowed**: mock scores remain only for local dev with no Sightengine credentials (adult / deepfake) or no S3 bucket + OpenCV (filmmaking). A deployment with `AWS_S3_BUCKET` set and OpenCV missing now fails loudly.
- **Dead-letter path**: `backend/app/dead_letter.py` (Redis list `dlq:process_video`), `scripts/replay_dlq.py` to list / replay.
- **Perceptual duplicate detection**: new pure module `backend/app/phash.py` — dHash of 5 evenly spaced frames (64 bits each), mean Hamming distance <= 10 = near-duplicate. New nullable `videos.phash` column (idempotent `ALTER TABLE` migration), `db.list_phashes()`. Exact SHA-256 match still scores 1.0 (blocked); a near-duplicate scores 0.85 and the decision engine now flags it (`FLAG_THRESHOLDS["duplicate_content"] = 0.8`).
- **Observability**: `backend/app/metrics.py` publishes `VerdictLatencySeconds` (job creation → verdict, dimension `Verdict`), `QueueDepth` and `DeadLetterDepth` to CloudWatch. Disabled unless `CLOUDWATCH_NAMESPACE` is set; failures are logged and never propagate.
- **Containers**: `backend/Dockerfile` (one image, API or worker by command, non-root), `backend/.dockerignore`, `scripts/push_ecr.sh`.
- **Infra**: `infra/cloudformation.yml` gains a `CloudWatchMetrics` IAM policy (`cloudwatch:PutMetricData`, restricted to the `Misence/Moderation` namespace), `CLOUDWATCH_NAMESPACE` in the generated `.env`, and `opencv-python-headless` in UserData. `opencv-python-headless==4.10.0.84` added to `backend/requirements.txt` (previously installed by hand, never declared).
- **Frontend**: `Job` type gains `failed` / `needs_review`; the upload page stops polling on `failed` and shows "Held for review".
- **Broker resilience + backlog signal** (added after the incident below): Celery broker transport options `socket_keepalive`, `health_check_interval=30`, `retry_on_timeout`; `metrics.publish_queue_depth()` is now called by the **API on every enqueue** (a dead worker publishes nothing, so a worker-side metric cannot detect a dead worker) as well as by the worker.
- **Tooling**: `scripts/measure_metrics.py` — runs the test suites and benchmarks a live API (latency percentiles, false-positive rate), excluding runs that used a mock / error fallback.

### Verification
- `tests/test_pipeline_hardening.py` (15 tests): real-thread concurrency (4 x 0.3 s blocking pillars finish in < 0.6 s), `PillarError` propagation, retry configuration, a persistent failure retried 1 + 3 times via Celery's eager `apply()` and ending `needs_review` with a dead-letter entry and no `approved` write, success path + latency metric, dead-letter push / depth / ordered drain, metrics disabled / enabled / failure-swallowing, dHash and near-duplicate matching. 3 new decision-engine tests (near-duplicate flagged, exact blocked, unique approved).
- Full local suite: all pass (live-DB modules skip without `POSTGRES_URL`). Frontend: `tsc --noEmit` clean, 171 vitest tests pass. `pip-audit` reports no findings for the new OpenCV pin (existing `starlette` / `ecdsa` findings are unchanged). `scripts/scan-repo.py`: 16 issues before and after, none new.

### Production incident found while deploying (2026-10-29)
- The production Celery worker had been **silently dead since 2026-10-06 21:42 UTC**: it logged `Connection to broker lost. Trying to re-establish` after a Redis `Connection reset by peer`, never logged `ready` again, and stayed `active (running)` — so systemd never restarted it. Uploads sat in `pending` for ~23 days (4 jobs were queued when found). Fixed operationally by `systemctl restart redactor-celery` (jobs then processed normally); the keepalive / health-check settings above are a mitigation, not a proven root-cause fix. The `QueueDepth` alarm below is the detection.
- Baseline on the *pre-PR* code after the restart: 6 uploads of 3 real clips, **median 17.2 s upload -> verdict (p95 ~43 s)**, 0 mock / error fallbacks; the 10 MB 1080p clip took 33-43 s.

### Infra actions taken (2026-10-29)
- ECR repository `misence-backend` (scan-on-push) created; image built from `backend/Dockerfile` and pushed (`:e3cb609`, `:latest`, ~160 MB). Smoke-tested: all app modules import, OpenCV 4.10, runs as uid 1000.
- SNS topic `misence-alerts` and CloudWatch alarm `misence-dead-letter-jobs` (`DeadLetterDepth > 0`) created. The topic has **no subscribers yet**.
- **CloudFormation stack `redactor-v2` was NOT updated.** A change set showed the `UserData` edit has `RequiresRecreation: Conditionally` on the EC2 instance, which has no Elastic IP and was configured by hand — a replacement would change its address and wipe it. Do not run `cloudformation deploy` against this stack without reviewing a change set first. The `CloudWatchMetrics` IAM policy has to be attached to `redactor-ec2-role` directly (`aws iam put-role-policy`) instead.

### Not done / not verified
- **Code not deployed to EC2 yet** (blocked on the PR's security gate, see below). No post-change latency measurement yet.
- The PR's `security-scan` fails on 6 *new* advisories unrelated to this change (`python-jose` PYSEC-2026-4298, no fix published; `vitest`/`tinypool`/`vite`/`zod`/`source-map-js` in the frontend toolchain). They need a human decision in `.ci/security-baseline.json`.
- Perceptual-hash accuracy was only checked on synthetic photo-like video (resized / re-encoded / brightened copies: distance 0-0.2; unrelated videos: 30-35; threshold 10), not on real film footage. A first attempt with flat-colour clips gave meaningless distances (15 vs 18) because dHash needs gradients — `tests/test_phash_opencv.py` uses textured frames and skips when OpenCV is absent.
- CloudFormation changes only affect a *new* stack. The existing EC2 instance needs: stack update for the IAM policy, `CLOUDWATCH_NAMESPACE=Misence/Moderation` appended to `/app/.env`, `opencv-python-headless` confirmed installed in the venv, then `sudo systemctl restart redactor-api redactor-celery`. The `phash` column is added automatically on API startup.
- Near-duplicate matching is a linear scan over stored fingerprints, aligned by frame position — a trimmed or re-cut video will not match.

## 2026-10-29 — Production is Python 3.9: compatibility fix + guard (found by smoke-testing before restart)

### What happened
Fast-forwarding the EC2 checkout to the merged PR #52 and import-testing as the service user (before restarting anything) failed: `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` in `metrics.py`. The server's system `python3` is **3.9.25**; the new modules used PEP 604 `X | None` annotations, which are a runtime error before 3.10. CI and dev machines run 3.12, so nothing caught it. The running services were never restarted, so there was no outage; the server checkout was rolled back to the known-good `92caf0a` until the fix was ready.

### Changes
- `from __future__ import annotations` added to `metrics.py`, `phash.py`, `pillars/duplicate_content.py`, `tasks.py`.
- `tests/test_python39_compat.py`: AST guard that fails if any backend module uses `X | Y` in an annotation without the `__future__` import (the exact bug class), plus a test that the guard detects it.

### Verification
- Full suite run inside `python:3.9-slim` (3.9.25, same patch version as the server): all backend modules import; 39 passed, 4 skipped (live-DB). The two R&D CI-tooling test files are excluded there because the scripts they test only run on CI's 3.12.

### Still open (found, not fixed here)
- `backend/requirements.txt` pins `python-multipart==0.0.32` and `python-dotenv==1.2.2`, which **do not exist for Python 3.9** (latest 3.9 builds: 0.0.20 and 1.2.1). That is why the server has `python-multipart 0.0.20`: the dependency bump from the JWT/security PR (#50) cannot be applied to production as long as it runs 3.9. Fix = move the server to Python 3.11+ (Amazon Linux 2023 ships `python3.11`) and update the systemd `ExecStart` lines; until then the pinned versions are only correct for CI / Docker (3.12).
- The Docker image uses Python 3.12 while production uses 3.9 — the image is not a faithful rehearsal of production until the server is upgraded.
- The "Update Test Baseline" workflow fails on `main` since branch protection was enabled (`GH006: Protected branch update failed`); the regression baseline is therefore stale.

### Load-test baseline on the current production code (2026-10-29, pre-#52 behaviour: 1 solo worker, sequential pillars)
- New `scripts/load_test.py` (stdlib only): N simultaneous uploads, reports ack latency, verdict latency p50/p95/max and throughput. After this run it was changed to detect fallback jobs itself and compute latency/throughput from real-work jobs only.
- Burst of 12 simultaneous uploads (0.7 MB and 1.0 MB clips). **The run exhausted the Sightengine free plan's daily quota**: the last 4 jobs got `HTTP 400: Daily usage limit reached` on the adult-content and deepfake pillars, and (pre-fail-closed code) silently fell back to mock scores, finishing in ~3.7 s each. An initial summary that reported "12 jobs in 147.5 s, 4.9 jobs/min" was therefore wrong and has been retracted.
- Corrected figures from the 8 real-work jobs (server timestamps): **~16 s per job (median gap between completions), 3.7 jobs/min, verdict wait median 71.5 s / max 128.6 s**. POST acknowledgment (client-side, unaffected by the fallback): median 1.6 s, max 2.0 s — the API stays responsive while the queue backs up; the single worker is the bottleneck.
- **Production exposure created by this run**: while the daily quota is exhausted, uploads to the *deployed* (pre-#52) code get fake adult-content / deepfake scores instead of an error. That is exactly the fail-open behaviour #52 removes, but #52 is not deployed yet. Resets with the provider's daily window; confirm in the Sightengine dashboard.
- Lessons: (1) load-test against a provider with a free-tier quota burns the quota — use a mock provider or a paid test key; (2) any performance number must be filtered for fallback runs, which `measure_metrics.py bench` already did and `load_test.py` now does; (3) the same quota is a production capacity limit (~10 Sightengine calls per video).
- Not measured (blocked on deploying the merged code and on permission to start extra worker processes on the server): post-fix single-job latency and multi-worker throughput.
- Each run created real (blocked-as-duplicate, hidden) jobs on the production database under the test account.
