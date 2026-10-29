import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from jose import jwt, JWTError
from app import db, metrics, storage
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from app.tasks import process_video

app = FastAPI(title="Video Moderation API")

# Ensure DB tables exist on every startup — safe because CREATE TABLE IF NOT EXISTS is idempotent
db._ensure_schema()

# Canonical department list — duplicated from frontend/app/profile/page.tsx's
# DEPARTMENTS constant (per the plan's Open Questions: no shared source exists
# across the frontend/backend boundary today; both lists are short and
# human-maintained). Used to validate POST /auth/upgrade and to build the
# built-in Houses list on GET /houses.
#
# Deliberately scoped to craftsmanship/creativity roles only — logistics and
# support departments (Locations, Continuity, Transportation, Catering &
# Craft Services) were removed and replaced with genuine, distinct craft
# roles (Choreography, Foley Artistry, Storyboarding / Previsualization,
# Prosthetics & Creature Design) — see the frontend's copy for the full
# rationale on why each replacement is distinct from existing entries.
#
# MUST be kept byte-for-byte identical (same strings, same order) to the
# frontend's copy — mismatched entries here would either reject a valid
# selection from the frontend's dropdown (400 on upgrade) or leave a real
# frontend option unable to ever get accepted server-side.
DEPARTMENTS = [
    "Cinematography", "Directing", "Screenwriting", "Editing",
    "Sound Design", "Visual Effects", "Production Design", "Acting",
    "Producing", "Camera", "Grip & Electric", "Art Department",
    "Set Decoration", "Costume Design", "Hair & Makeup", "Sound Recording",
    "Music", "Special Effects", "Stunts", "Casting",
    "Production Management", "Script Supervision", "Choreography",
    "Foley Artistry", "Storyboarding / Previsualization",
    "Prosthetics & Creature Design", "Colorist / Post-Production",
    "Animation", "Other",
]

# Open product decision from the design doc, resolved here: caps how many
# ADDITIONAL departments (beyond the auto-included primary) one video can
# carry. Keeps a department tag a meaningful browsing signal rather than a
# video appearing in most/all department feeds at once.
MAX_ADDITIONAL_DEPARTMENTS = 5

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://distributed-video-moderation.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Auth setup ---
pwd_context = CryptContext(schemes=["bcrypt"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# No hardcoded fallback: a misconfigured production deploy (env var unset)
# used to silently sign every JWT with a secret visible in this file's own
# source history, letting anyone forge a valid token for any user. Fails
# startup loudly instead, matching app/config.py's existing POSTGRES_URL
# pattern (raise RuntimeError with a clear message, not a silent default).
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET env var is required. "
        "Copy .env.example to .env at the project root and fill in credentials."
    )

# JWTs previously had no exp claim at all — every login token was valid
# forever with no server-side revocation mechanism. python-jose's
# jwt.decode() validates exp automatically when present, raising
# ExpiredSignatureError (a JWTError subclass) — every one of this file's
# existing `except JWTError:` blocks already catches it correctly with no
# changes needed there.
JWT_EXPIRY = timedelta(hours=24)

# --- Request models ---
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class UpgradeRequest(BaseModel):
    department: str

# --- Auth endpoints ---
@app.post("/auth/register")
def register(req: RegisterRequest) -> dict:
    if db.get_user_by_email(req.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    password_hash = pwd_context.hash(req.password)
    user = db.create_user(req.name, req.email, password_hash)
    return {"message": "Account created", "user": user}


@app.post("/auth/login")
def login(req: LoginRequest) -> dict:
    user = db.get_user_by_email(req.email)
    if not user or not pwd_context.verify(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    expires_at = datetime.now(timezone.utc) + JWT_EXPIRY
    token = jwt.encode({"sub": str(user["id"]), "exp": expires_at}, JWT_SECRET, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer"}


@app.post("/auth/upgrade")
def upgrade(req: UpgradeRequest, token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if req.department not in DEPARTMENTS:
        raise HTTPException(status_code=400, detail="Invalid department")
    user = db.upgrade_to_creator(user_id, req.department)
    return {"message": "Account upgraded to creator", "user": user}





@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/debug/feed")
def debug_feed() -> dict:
    """Temporary debug endpoint — returns the actual exception from get_feed()."""
    import traceback
    try:
        data = db.get_feed(5, None)
        return {"ok": True, "enrouted": len(data["enrouted"]), "recommended": len(data["recommended"])}
    except Exception as e:
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}


@app.get("/debug/search")
def debug_search() -> dict:
    """Temporary debug endpoint — returns the actual exception from search()."""
    import traceback
    try:
        data = db.search("test")
        return {"ok": True, "creators": len(data["creators"]), "videos": len(data["videos"])}
    except Exception as e:
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}


def _require_creator(token: str = Depends(oauth2_scheme)) -> str:
    """Decode JWT and verify account_type == creator. Returns user_id."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user["account_type"] != "creator":
        raise HTTPException(status_code=403, detail="Creator account required to upload")
    return user_id


@app.post("/videos")
async def upload_video(
    file: UploadFile,
    departments: str = Form(""),
    user_id: str = Depends(_require_creator),
) -> dict:
    """departments is an optional comma-separated list of ADDITIONAL department
    tags (the primary tag is never client-supplied — see set_video_department_tags
    docstring / design doc edge case: the server always derives the primary
    from the uploader's current users.department, regardless of what the
    client sends). Sent as a plain form field alongside the file, matching
    this endpoint's existing multipart/form-data shape (no JSON body today).

    Form(...) is required here, not a bare str default: a route that mixes
    UploadFile with a plain-str parameter does NOT automatically treat the
    latter as a form field — without this, departments silently binds to
    nothing/a query param instead of the multipart body, and the 400
    validation below never fires (confirmed the hard way: a request with an
    invalid department fell through to the S3 upload instead of rejecting)."""
    user = db.get_user_by_id(user_id)
    primary_department = user["department"] if user else None

    additional = [d.strip() for d in departments.split(",") if d.strip()]
    invalid = [d for d in additional if d not in DEPARTMENTS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid department(s): {', '.join(invalid)}")
    if len(additional) > MAX_ADDITIONAL_DEPARTMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"At most {MAX_ADDITIONAL_DEPARTMENTS} additional departments allowed",
        )

    task_id = str(uuid.uuid4())
    object_name = f"{task_id}.mp4"

    # Write upload to a temp file first, then upload to S3
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = os.path.join(tmp_dir, object_name)
        with open(tmp_path, "wb") as f:
            f.write(await file.read())
        file_path = storage.save_video(object_name, tmp_path)

    db.create_job(task_id, file.filename or object_name, file_path, user_id=user_id)
    if primary_department:
        db.set_video_department_tags(task_id, primary_department, additional)
    process_video.delay(task_id)
    metrics.publish_queue_depth()

    # Flow-graph response: instant acknowledgment with tracking ID
    return {"status": "processing", "task_id": task_id}


def _enrich(jobs: list, viewer_id: Optional[str] = None) -> list:
    """Shared enrichment transform for any list of raw video rows (dicts with
    a '_id' key from db.py) headed to the frontend: renames '_id' -> 'job_id'
    (the frontend Job type has no _id field), 'pillar_results' -> 'pillars',
    attaches department_tags and credit_count/comment_count (all batch-
    fetched, not N+1), and converts file_path (an s3://... URI) into a real
    playable video_url via a live presigned-URL call. None of this is a DB
    column — every route returning Job-shaped rows (GET /feed, GET
    /houses/{id}/feed, GET /houses/department/{name}/feed) must run its rows
    through this exact helper, not a re-implementation, or cards silently
    render with no job_id/video_url ("No video available").

    viewer_id (optional) additionally attaches 'credited': whether THIS
    viewer has already credited each video — fixes a pre-existing bug where
    the star button's filled state only ever reflected same-session client
    state, never the real server-side record (a page reload silently lost
    it). Per-video, per-viewer, so this can't be batch-fetched the same way
    as the aggregate counts; omitted (each row gets credited=False) when
    there's no logged-in viewer, matching every other viewer-optional field
    elsewhere in this API (e.g. is_following)."""
    ids = [j["_id"] for j in jobs]
    tags_by_video = db.get_department_tags_for_videos(ids)
    engagement_by_video = db.get_engagement_counts_for_videos(ids)
    for j in jobs:
        video_id = j.pop("_id")
        j["job_id"] = video_id
        j["department_tags"] = tags_by_video.get(video_id, [])
        engagement = engagement_by_video.get(video_id, {"credits": 0, "comments": 0})
        j["credit_count"] = engagement["credits"]
        j["comment_count"] = engagement["comments"]
        j["credited"] = db.get_video_credit_state(video_id, viewer_id) if viewer_id else False
        if "pillar_results" in j:
            j["pillars"] = j.pop("pillar_results")
        file_path = j.get("file_path", "")
        if file_path.startswith("s3://"):
            object_name = file_path.split("/", 3)[-1]
            try:
                j["video_url"] = storage.get_presigned_url(object_name)
            except Exception:
                j["video_url"] = None
        else:
            j["video_url"] = None
    return jobs


@app.get("/feed")
def get_feed(limit: int = 50, token: Optional[str] = None) -> dict:
    """Smart feed — returns {enrouted, recommended} buckets.
    Pass ?token=<jwt> to personalise with enrouted content.
    Both buckets contain approved/flagged videos with presigned S3 URLs."""
    viewer_id = None
    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            viewer_id = payload["sub"]
        except JWTError:
            pass

    data = db.get_feed(limit, viewer_id)

    return {
        "enrouted":    _enrich(data["enrouted"], viewer_id),
        "recommended": _enrich(data["recommended"], viewer_id),
    }


@app.get("/videos")
def list_videos(limit: int = 50) -> list:
    jobs = db.list_jobs(limit)
    for j in jobs:
        j["job_id"] = j.pop("_id")
        if "pillar_results" in j:
            j["pillars"] = j.pop("pillar_results")
    return jobs


@app.get("/videos/{job_id}/status")
def get_status(job_id: str) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    job["job_id"] = job.pop("_id")
    if "pillar_results" in job:
        job["pillars"] = job.pop("pillar_results")
    job["department_tags"] = db.get_video_department_tags(job_id)
    return job


# ── Video department tags ────────────────────────────────────────────────────
# Post-upload editing of ADDITIONAL tags only — the primary tag is written
# once at upload time (set_video_department_tags) and is not reachable
# through either of these routes at all, by design (design doc edge case:
# "the primary can never be removed" is enforced by never exposing the
# operation, not by rejecting it after the fact).

def _require_video_owner(job_id: str, token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Video not found")
    if job.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Only the video's creator can do this")
    return user_id


class AddDepartmentTagRequest(BaseModel):
    department: str


@app.post("/videos/{job_id}/departments")
def add_department_tag(job_id: str, req: AddDepartmentTagRequest, _owner_id: str = Depends(_require_video_owner)) -> dict:
    if req.department not in DEPARTMENTS:
        raise HTTPException(status_code=400, detail="Invalid department")
    db.add_video_department_tag(job_id, req.department)
    return {"department_tags": db.get_video_department_tags(job_id)}


@app.delete("/videos/{job_id}/departments/{department}")
def remove_department_tag(job_id: str, department: str, _owner_id: str = Depends(_require_video_owner)) -> dict:
    db.remove_video_department_tag(job_id, department)
    return {"department_tags": db.get_video_department_tags(job_id)}


# ── Follow / Unfollow ─────────────────────────────────────────────────────────

def _require_auth(token: str = Depends(oauth2_scheme)) -> str:
    """Decode JWT, return user_id. Any logged-in user can use this."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Credits ───────────────────────────────────────────────────────────────────
# Requires login and is per-user, deduplicated (toggle: credit once, tap
# again to un-credit) — replaces the old POST /videos/{job_id}/credit, which
# had no auth check and no way to know who credited what, making it both
# spammable and unusable as a ranking signal (see docs/changelog.md's entry
# on this feature for the full rationale).

@app.post("/videos/{job_id}/credit")
def toggle_credit(job_id: str, viewer_id: str = Depends(_require_auth)) -> dict:
    return db.toggle_video_credit(job_id, viewer_id)


# ── Not interested ────────────────────────────────────────────────────────────

@app.post("/videos/{job_id}/dismiss")
def dismiss_video(job_id: str, viewer_id: str = Depends(_require_auth)) -> dict:
    """'Not interested' — hides this video from the caller's own feed going
    forward. Per-video only (no creator-level snooze), per the confirmed
    scope for this feature."""
    db.dismiss_video(viewer_id, job_id)
    return {"dismissed": True}


@app.post("/creators/{creator_id}/follow")
def follow(creator_id: str, viewer_id: str = Depends(_require_auth)) -> dict:
    db.follow_user(viewer_id, creator_id)
    return {"following": True}


@app.delete("/creators/{creator_id}/follow")
def unfollow(creator_id: str, viewer_id: str = Depends(_require_auth)) -> dict:
    db.unfollow_user(viewer_id, creator_id)
    return {"following": False}


@app.get("/creators/{creator_id}")
def get_creator(creator_id: str, token: Optional[str] = None) -> dict:
    viewer_id = None
    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            viewer_id = payload["sub"]
        except JWTError:
            pass
    profile = db.get_creator_profile(creator_id, viewer_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Creator not found")
    return profile


# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/search")
def search(q: str = "") -> dict:
    if not q.strip():
        return {"creators": [], "videos": []}
    return db.search(q.strip())


class SearchUsersByIdsRequest(BaseModel):
    ids: list[str]


@app.get("/search-users")
def search_users(q: str = "", user_id: str = Depends(_require_auth)) -> list:
    if not q.strip():
        return []
    return db.search_users(q.strip())


@app.post("/search-users/by-ids")
def search_users_by_ids(req: SearchUsersByIdsRequest, user_id: str = Depends(_require_auth)) -> list:
    if not req.ids:
        return []
    if len(req.ids) > 50:
        raise HTTPException(status_code=400, detail="Cannot look up more than 50 IDs per call")
    return db.search_users_by_ids(req.ids)


# ── Comments ──────────────────────────────────────────────────────────────────

class CommentRequest(BaseModel):
    body: str


@app.get("/videos/{job_id}/comments")
def list_comments(job_id: str) -> list:
    return db.get_comments(job_id)


@app.post("/videos/{job_id}/comments")
def post_comment(job_id: str, req: CommentRequest, token: Optional[str] = None) -> dict:
    user_id = None
    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            user_id = payload["sub"]
        except JWTError:
            pass
    if not req.body.strip():
        raise HTTPException(status_code=400, detail="Comment body cannot be empty")
    return db.add_comment(job_id, req.body.strip(), user_id)


# ── Houses ────────────────────────────────────────────────────────────────────
# Built-in Houses (one per department) have no table — derived from
# users.department at query time (KTD1). Custom Houses are owned entities
# curated by a creator via house_creator_members / house_video_members.

class CreateHouseRequest(BaseModel):
    name: str
    description: Optional[str] = None


def _require_house_owner(house_id: str, token: str = Depends(oauth2_scheme)) -> str:
    """First resource-ownership check in this codebase (KTD5). Decodes the
    token the same way _require_auth does, fetches the house, raises 404 if
    it doesn't exist, raises 403 if the caller isn't the owner. Returns the
    viewer_id so callers can reuse it without re-decoding."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        viewer_id = payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    house = db.get_house(house_id)
    if not house:
        raise HTTPException(status_code=404, detail="House not found")
    if house["owner_id"] != viewer_id:
        raise HTTPException(status_code=403, detail="Only the House owner can do this")
    return viewer_id


@app.get("/houses")
def list_houses() -> dict:
    """Returns {builtIn: [{name}], custom: [House]}. builtIn is the hardcoded
    DEPARTMENTS list (no DB query); custom is every real houses row with
    creator_count/video_count for the listing card."""
    return {
        "builtIn": [{"name": d} for d in DEPARTMENTS],
        "custom": db.list_custom_houses(),
    }


@app.post("/houses")
def create_house(req: CreateHouseRequest, owner_id: str = Depends(_require_creator)) -> dict:
    """Only creators can make a House (matches the confirmed requirement),
    reusing the existing role check exactly."""
    house_id = str(uuid.uuid4())
    return db.create_house(house_id, owner_id, req.name, req.description)


@app.delete("/houses/{house_id}")
def remove_house(house_id: str, _owner_id: str = Depends(_require_house_owner)) -> dict:
    db.delete_house(house_id)
    return {"deleted": True}


@app.get("/houses/department/{name}/feed")
def get_department_house_feed(name: str) -> dict:
    """Built-in House feed — every approved/flagged video from creators whose
    department exactly matches `name`. Flat list (KTD4), run through the
    shared _enrich() transform (job_id/pillars/video_url), not a re-implementation."""
    rows = db.get_department_house_feed(name)
    return {"videos": _enrich(rows)}


@app.get("/houses/{house_id}/feed")
def get_house_feed(house_id: str) -> dict:
    """Custom House feed — unioned creator+video membership, flat list (KTD4),
    run through the shared _enrich() transform. No ownership check: any
    House's feed is publicly browsable (KTD6)."""
    rows = db.get_house_feed(house_id)
    return {"videos": _enrich(rows)}


@app.post("/houses/{house_id}/members/creators/{creator_id}")
def add_house_creator(house_id: str, creator_id: str, _owner_id: str = Depends(_require_house_owner)) -> dict:
    db.add_house_creator_member(house_id, creator_id)
    return {"added": True}


@app.delete("/houses/{house_id}/members/creators/{creator_id}")
def remove_house_creator(house_id: str, creator_id: str, _owner_id: str = Depends(_require_house_owner)) -> dict:
    db.remove_house_creator_member(house_id, creator_id)
    return {"added": False}


@app.post("/houses/{house_id}/members/videos/{video_id}")
def add_house_video(house_id: str, video_id: str, _owner_id: str = Depends(_require_house_owner)) -> dict:
    """No ownership check on the video's creator (KTD2a, deliberate): a House
    owner can curate any existing public video into their House, regardless
    of who created it — matching follow_user()'s no-consent-required posture."""
    db.add_house_video_member(house_id, video_id)
    return {"added": True}


@app.delete("/houses/{house_id}/members/videos/{video_id}")
def remove_house_video(house_id: str, video_id: str, _owner_id: str = Depends(_require_house_owner)) -> dict:
    db.remove_house_video_member(house_id, video_id)
    return {"added": False}
