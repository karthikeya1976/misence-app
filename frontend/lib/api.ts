import { getToken } from "./auth";

// All API calls go through Next.js's rewrite proxy at /api/backend.
// next.config.ts maps  /api/backend/* → https://redactor-api.duckdns.org/*  on Vercel,
// and  /api/backend/* → http://localhost:8088/*  locally (via the rewrites source/destination).
// This avoids mixed-content blocks (HTTPS Vercel page → HTTP EC2) entirely — the browser
// always calls its own origin; Next.js does the server-side proxy hop.
const API = "/api/backend";

// ── Types ──────────────────────────────────────────────────────────────────

export type PillarFlag = {
  timestamp?: string;
  label: string;
  detail?: string;
  reference_id?: string;
};

export type PillarResult = {
  pillar: string;
  score: number;
  flags: PillarFlag[];
};

export type DepartmentTag = {
  department: string;
  is_primary: boolean;
};

export type Job = {
  job_id: string;
  filename: string;
  file_path?: string;
  status: "pending" | "processing" | "done" | "failed";
  // "needs_review": moderation failed after retries; hidden from every feed until a human decides
  overall_status?: "approved" | "flagged" | "blocked" | "needs_review";
  pillars?: PillarResult[];
  reasons?: string[];
  size_bytes?: number;
  user_id?: string;
  creator_name?: string;
  creator_department?: string;
  department_tags?: DepartmentTag[];
  // Batch-fetched per-video engagement counts (credit_count/comment_count)
  // and the current viewer's own credit state (credited) — see backend's
  // _enrich() docstring. credited defaults to false server-side when
  // there's no logged-in viewer, same as every other viewer-optional field.
  credit_count?: number;
  comment_count?: number;
  credited?: boolean;
  video_url?: string | null;
  created_at: string;
  updated_at: string;
};

export type User = {
  id: string;
  name: string;
  email: string;
  account_type: "viewer" | "creator";
  department?: string;
  created_at?: string;
};

// ── Auth ───────────────────────────────────────────────────────────────────

export async function register(
  name: string,
  email: string,
  password: string
): Promise<{ message: string; user: User }> {
  const res = await fetch(`${API}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, password }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Registration failed");
  }
  return res.json();
}

export async function login(
  email: string,
  password: string
): Promise<{ access_token: string; token_type: string }> {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Login failed");
  }
  return res.json();
}

export async function upgradeToCreator(
  department: string
): Promise<{ message: string; user: User }> {
  const token = getToken();
  const res = await fetch(`${API}/auth/upgrade`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ department }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Upgrade failed");
  }
  return res.json();
}

// ── Videos ─────────────────────────────────────────────────────────────────

export async function uploadVideo(
  file: File,
  additionalDepartments: string[] = []
): Promise<{ task_id: string; status: string }> {
  const token = getToken();
  const form = new FormData();
  form.append("file", file);
  if (additionalDepartments.length > 0) {
    form.append("departments", additionalDepartments.join(","));
  }
  const res = await fetch(`${API}/videos`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? `Upload failed: ${res.status}`);
  }
  return res.json();
}

// Post-upload editing of ADDITIONAL tags only — there is no client-facing way
// to change or remove a video's primary department tag; the server never
// exposes that operation (see backend's _require_video_owner routes).

export async function addDepartmentTag(jobId: string, department: string): Promise<{ department_tags: DepartmentTag[] }> {
  const token = getToken();
  const res = await fetch(`${API}/videos/${jobId}/departments`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ department }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Add department failed");
  }
  return res.json();
}

export async function removeDepartmentTag(jobId: string, department: string): Promise<{ department_tags: DepartmentTag[] }> {
  const token = getToken();
  const res = await fetch(`${API}/videos/${jobId}/departments/${encodeURIComponent(department)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Remove department failed");
  return res.json();
}

export async function getJobStatus(job_id: string): Promise<Job> {
  const res = await fetch(`${API}/videos/${job_id}/status`);
  if (!res.ok) throw new Error(`Status fetch failed: ${res.status}`);
  return res.json();
}

export async function listJobs(): Promise<Job[]> {
  const res = await fetch(`${API}/videos`);
  if (!res.ok) throw new Error(`List failed: ${res.status}`);
  return res.json();
}

export type FeedResponse = {
  enrouted: Job[];
  recommended: Job[];
};

export async function getFeed(): Promise<FeedResponse> {
  const token = getToken();
  const url = token ? `${API}/feed?token=${token}` : `${API}/feed`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Feed failed: ${res.status}`);
  return res.json();
}

// ── Credits ────────────────────────────────────────────────────────────────

// Requires login; toggles this viewer's own credit on/off (tap again to
// un-credit) — replaces the old unauthenticated, non-deduplicated version.
export async function toggleCredit(jobId: string): Promise<{ credited: boolean; credits: number }> {
  const token = getToken();
  const res = await fetch(`${API}/videos/${jobId}/credit`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Credit failed");
  return res.json();
}

// "Not interested" — hides this video from the caller's own feed going
// forward. Per-video only, requires login.
export async function dismissVideo(jobId: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API}/videos/${jobId}/dismiss`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Dismiss failed");
}

// ── Follow ─────────────────────────────────────────────────────────────────

export async function followCreator(creatorId: string): Promise<void> {
  const token = getToken();
  await fetch(`${API}/creators/${creatorId}/follow`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function unfollowCreator(creatorId: string): Promise<void> {
  const token = getToken();
  await fetch(`${API}/creators/${creatorId}/follow`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export type CreatorProfile = {
  id: string;
  name: string;
  department?: string;
  account_type: string;
  credits: number;
  follower_count: number;
  video_count: number;
  is_following: boolean;
};

export async function getCreatorProfile(creatorId: string): Promise<CreatorProfile> {
  const token = getToken();
  const url = token
    ? `${API}/creators/${creatorId}?token=${token}`
    : `${API}/creators/${creatorId}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Creator not found");
  return res.json();
}

// ── Search ─────────────────────────────────────────────────────────────────

export type SearchResult = {
  creators: {
    id: string;
    name: string;
    department?: string;
    credits: number;
    follower_count: number;
  }[];
  videos: {
    id: string;
    filename: string;
    overall_status: string;
    creator_name?: string;
    creator_department?: string;
  }[];
};

export async function searchAll(q: string): Promise<SearchResult> {
  const res = await fetch(`${API}/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) throw new Error("Search failed");
  return res.json();
}

// ── Comments ───────────────────────────────────────────────────────────────────

export type Comment = {
  id: string;
  body: string;
  author_name?: string;
  created_at: string;
};

export async function getComments(jobId: string): Promise<Comment[]> {
  const res = await fetch(`${API}/videos/${jobId}/comments`);
  if (!res.ok) throw new Error("Comments fetch failed");
  return res.json();
}

export async function postComment(jobId: string, body: string): Promise<Comment> {
  const token = getToken();
  const url = token
    ? `${API}/videos/${jobId}/comments?token=${token}`
    : `${API}/videos/${jobId}/comments`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
  if (!res.ok) throw new Error("Post comment failed");
  return res.json();
}

// ── Houses ─────────────────────────────────────────────────────────────────
// Built-in Houses (one per department) have no id/table — the Houses page
// lists them by name only. Custom Houses are owned, curated entities.

export type House = {
  id: string;
  owner_id: string;
  name: string;
  description?: string;
  created_at: string;
  creator_count?: number;
  video_count?: number;
};

export type HousesListResponse = {
  builtIn: { name: string }[];
  custom: House[];
};

export type HouseFeedResponse = {
  videos: Job[];
};

export async function listHouses(): Promise<HousesListResponse> {
  const res = await fetch(`${API}/houses`);
  if (!res.ok) throw new Error(`Houses fetch failed: ${res.status}`);
  return res.json();
}

export async function createHouse(
  name: string,
  description?: string
): Promise<House> {
  const token = getToken();
  const res = await fetch(`${API}/houses`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Create House failed");
  }
  return res.json();
}

export async function deleteHouse(houseId: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API}/houses/${houseId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Delete House failed");
}

export async function getHouseFeed(houseId: string): Promise<HouseFeedResponse> {
  const res = await fetch(`${API}/houses/${houseId}/feed`);
  if (!res.ok) throw new Error(`House feed failed: ${res.status}`);
  return res.json();
}

export async function getDepartmentHouseFeed(
  name: string
): Promise<HouseFeedResponse> {
  const res = await fetch(`${API}/houses/department/${encodeURIComponent(name)}/feed`);
  if (!res.ok) throw new Error(`Department House feed failed: ${res.status}`);
  return res.json();
}

export async function addHouseCreatorMember(
  houseId: string,
  creatorId: string
): Promise<void> {
  const token = getToken();
  const res = await fetch(
    `${API}/houses/${houseId}/members/creators/${creatorId}`,
    { method: "POST", headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) throw new Error("Add creator member failed");
}

export async function removeHouseCreatorMember(
  houseId: string,
  creatorId: string
): Promise<void> {
  const token = getToken();
  const res = await fetch(
    `${API}/houses/${houseId}/members/creators/${creatorId}`,
    { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) throw new Error("Remove creator member failed");
}

export async function addHouseVideoMember(
  houseId: string,
  videoId: string
): Promise<void> {
  const token = getToken();
  const res = await fetch(
    `${API}/houses/${houseId}/members/videos/${videoId}`,
    { method: "POST", headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) throw new Error("Add video member failed");
}

export async function removeHouseVideoMember(
  houseId: string,
  videoId: string
): Promise<void> {
  const token = getToken();
  const res = await fetch(
    `${API}/houses/${houseId}/members/videos/${videoId}`,
    { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) throw new Error("Remove video member failed");
}
