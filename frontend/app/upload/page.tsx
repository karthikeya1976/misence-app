"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { uploadVideo, getJobStatus, type Job } from "@/lib/api";
import { isLoggedIn, isCreator, getUser } from "@/lib/auth";

// Kept as a third manually-synced copy of the canonical department list
// (frontend/app/profile/page.tsx, backend/app/main.py) — matches this
// project's established convention of short, human-maintained duplicated
// lists rather than a shared source across the frontend/backend boundary.
// MUST stay byte-for-byte identical: a mismatch here would offer an
// "additional department" option the backend's /videos upload rejects
// with a 400.
const DEPARTMENTS = [
  "Cinematography", "Directing", "Screenwriting", "Editing",
  "Sound Design", "Visual Effects", "Production Design", "Acting",
  "Producing", "Camera", "Grip & Electric", "Art Department",
  "Set Decoration", "Costume Design", "Hair & Makeup", "Sound Recording",
  "Music", "Special Effects", "Stunts", "Casting",
  "Production Management", "Script Supervision", "Choreography",
  "Foley Artistry", "Storyboarding / Previsualization",
  "Prosthetics & Creature Design", "Colorist / Post-Production",
  "Animation", "Other",
];

// Mirrors the backend's MAX_ADDITIONAL_DEPARTMENTS (backend/app/main.py) —
// kept in sync manually like DEPARTMENTS above. Enforced here for immediate
// UI feedback; the server re-validates independently (edge case: never trust
// client-side enforcement alone).
const MAX_ADDITIONAL_DEPARTMENTS = 5;

const RESULT_STYLE: Record<string, React.CSSProperties> = {
  approved: { border: "1px solid #c2542344", background: "#c254230d" },
  flagged:  { border: "1px solid #b4550044", background: "#b455000d" },
  blocked:  { border: "1px solid #7f1d1d55", background: "#7f1d1d0d" },
  needs_review: { border: "1px solid #b4550044", background: "#b455000d" },
};
const RESULT_COLOR: Record<string, string> = {
  approved: "#e08a5f",
  flagged:  "#fb923c",
  blocked:  "#f87171",
  needs_review: "#fb923c",
};

type Format = "scene" | "shot";

const FORMAT_OPTIONS: { id: Format; label: string; sub: string; ratio: string; icon: React.ReactNode }[] = [
  {
    id: "scene",
    label: "Scene",
    sub: "16:9",
    ratio: "16 / 9",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="5" width="20" height="14" rx="2" />
        <polygon points="10 9 15 12 10 15 10 9" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    id: "shot",
    label: "Shot",
    sub: "9:16",
    ratio: "9 / 16",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="6" y="2" width="12" height="20" rx="2" />
        <polygon points="10 9 15 12 10 15 10 9" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
];

export default function UploadPage() {
  const router    = useRouter();
  const inputRef  = useRef<HTMLInputElement>(null);
  const [format, setFormat]       = useState<Format>("shot");
  const [file, setFile]           = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError]         = useState("");
  const [job, setJob]             = useState<Job | null>(null);
  const [additionalDepts, setAdditionalDepts] = useState<string[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // The primary department is read once from the locally-cached user (set at
  // login/upgrade) purely for display — it's never sent to the server as
  // part of the upload. The server independently re-derives it from
  // users.department at upload time (edge case: a stale/tampered client
  // value here can never become the written primary tag).
  const primaryDept = getUser()?.department ?? null;
  const selectableDepts = DEPARTMENTS.filter(d => d !== primaryDept);

  function toggleDept(d: string) {
    setAdditionalDepts(prev =>
      prev.includes(d)
        ? prev.filter(x => x !== d)
        : prev.length >= MAX_ADDITIONAL_DEPARTMENTS ? prev : [...prev, d]
    );
  }

  useEffect(() => {
    if (!isLoggedIn()) { router.replace("/"); return; }
    if (!isCreator())  { router.replace("/profile"); }
  }, [router]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // Clear selected file when format changes — aspect ratios differ
  function switchFormat(f: Format) {
    setFormat(f as Format);
    setFile(null);
    setJob(null);
    setError("");
  }

  async function handleUpload() {
    if (!file) return;
    setError(""); setUploading(true); setJob(null);
    try {
      const { task_id } = await uploadVideo(file, additionalDepts);
      pollRef.current = setInterval(async () => {
        const s = await getJobStatus(task_id);
        if (s.status === "done" || s.status === "failed") {
          clearInterval(pollRef.current!);
          setJob(s);
          setUploading(false);
        }
      }, 2000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setUploading(false);
    }
  }

  const status = job?.overall_status ?? "";
  const isClip = format === "shot";

  return (
    <div style={{ maxWidth: "560px", margin: "0 auto" }}>
      <div style={{ marginBottom: "24px" }}>
        <h1 style={{ fontSize: "22px", fontWeight: 700, color: "var(--fg)" }}>Upload</h1>
        <p style={{ fontSize: "13px", color: "var(--fg-muted)", marginTop: "4px" }}>
          Submit your showreel for AI moderation
        </p>
      </div>

      {/* Format toggle */}
      <div style={{ marginBottom: "24px" }}>
        <p style={{ fontSize: "12px", fontWeight: 600, color: "var(--fg-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "10px" }}>
          Format
        </p>
        <div style={{ display: "flex", gap: "10px" }}>
          {FORMAT_OPTIONS.map(opt => {
            const active = format === opt.id;
            return (
              <button
                key={opt.id}
                onClick={() => switchFormat(opt.id)}
                style={{
                  flex: 1, display: "flex", alignItems: "center", gap: "12px",
                  padding: "14px 16px", borderRadius: "12px", cursor: "pointer",
                  background: active ? "var(--accent)" : "var(--surface)",
                  border: active ? "none" : "1px solid var(--border)",
                  color: active ? "#fff" : "var(--fg-muted)",
                  transition: "all 0.15s", textAlign: "left",
                }}
              >
                {/* Aspect-ratio preview thumbnail */}
                <div style={{
                  flexShrink: 0,
                  width: opt.id === "scene" ? "36px" : "20px",
                  height: opt.id === "scene" ? "20px" : "36px",
                  borderRadius: "4px",
                  background: active ? "rgba(255,255,255,0.25)" : "var(--bg)",
                  border: active ? "none" : "1px solid var(--border)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  color: active ? "#fff" : "var(--fg-muted)",
                }}>{opt.icon}</div>

                <div>
                  <p style={{ fontWeight: 700, fontSize: "14px", margin: 0, color: active ? "#fff" : "var(--fg)" }}>
                    {opt.label}
                  </p>
                  <p style={{ fontSize: "11px", margin: "2px 0 0", opacity: active ? 0.8 : 0.6 }}>
                    {opt.sub}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Department tags */}
      {primaryDept && (
        <div style={{ marginBottom: "24px" }}>
          <p style={{ fontSize: "12px", fontWeight: 600, color: "var(--fg-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "10px" }}>
            Departments
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
            {/* Primary — locked, always included, cannot be toggled off */}
            <span
              title="Your home department — automatically tagged and cannot be removed"
              style={{
                display: "inline-flex", alignItems: "center", gap: "6px",
                fontSize: "12.5px", fontWeight: 600, padding: "6px 12px",
                borderRadius: "999px", background: "var(--accent)", color: "#fff",
              }}
            >
              <span aria-hidden="true">🔒</span>
              {primaryDept} — Main Department
            </span>

            {selectableDepts.map(d => {
              const active = additionalDepts.includes(d);
              const disabled = !active && additionalDepts.length >= MAX_ADDITIONAL_DEPARTMENTS;
              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => toggleDept(d)}
                  disabled={disabled}
                  style={{
                    fontSize: "12.5px", fontWeight: 600, padding: "6px 12px",
                    borderRadius: "999px", cursor: disabled ? "not-allowed" : "pointer",
                    background: active ? "var(--surface-2, var(--surface))" : "var(--surface)",
                    border: active ? "1px solid var(--accent)" : "1px solid var(--border)",
                    color: active ? "var(--fg)" : "var(--fg-muted)",
                    opacity: disabled ? 0.4 : 1,
                  }}
                >
                  {d}
                </button>
              );
            })}
          </div>
          <p style={{ fontSize: "11px", color: "var(--fg-muted)", marginTop: "8px", opacity: 0.7 }}>
            Optional — tag up to {MAX_ADDITIONAL_DEPARTMENTS} more departments this content is relevant to. It will appear in each tagged department&apos;s feed.
          </p>
        </div>
      )}

      {/* Drop zone — shape matches selected format */}
      <div style={{ display: "flex", justifyContent: isClip ? "center" : "stretch" }}>
        <div
          onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) setFile(f); }}
          onDragOver={e => e.preventDefault()}
          onClick={() => inputRef.current?.click()}
          style={{
            border: `2px dashed ${file ? "var(--accent)" : "var(--border)"}`,
            borderRadius: "14px",
            cursor: "pointer",
            background: "var(--surface)",
            transition: "border-color 0.15s",
            display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center",
            textAlign: "center",
            // Clip: narrow portrait box; Video: full-width landscape box
            ...(isClip
              ? { width: "160px", aspectRatio: "9 / 16", padding: "16px 12px" }
              : { width: "100%",  aspectRatio: "16 / 9", padding: "24px" }),
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept="video/*"
            style={{ display: "none" }}
            onChange={e => setFile(e.target.files?.[0] ?? null)}
          />
          {file ? (
            <>
              <p style={{ fontWeight: 600, color: "var(--fg)", fontSize: "13px", wordBreak: "break-all" }}>{file.name}</p>
              <p style={{ fontSize: "11px", color: "var(--fg-muted)", marginTop: "4px" }}>
                {(file.size / 1024 / 1024).toFixed(1)} MB
              </p>
            </>
          ) : (
            <>
              {/* Icon */}
              <div style={{ marginBottom: "10px", opacity: 0.4, color: "var(--fg-muted)" }}>
                {isClip ? (
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect x="6" y="2" width="12" height="20" rx="2" />
                    <polygon points="10 9 15 12 10 15 10 9" fill="currentColor" stroke="none" />
                  </svg>
                ) : (
                  <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect x="2" y="5" width="20" height="14" rx="2" />
                    <polygon points="10 9 15 12 10 15 10 9" fill="currentColor" stroke="none" />
                  </svg>
                )}
              </div>
              <p style={{ fontWeight: 500, color: "var(--fg-muted)", fontSize: "13px" }}>
                Drop {isClip ? "a shot" : "a scene"} here
              </p>
              <p style={{ fontSize: "11px", color: "var(--fg-muted)", marginTop: "4px", opacity: 0.6 }}>
                or click to browse
              </p>
              <p style={{ fontSize: "10px", color: "var(--fg-muted)", marginTop: "8px", opacity: 0.45 }}>
                {isClip ? "Shot · 9:16" : "Scene · 16:9"}
              </p>
            </>
          )}
        </div>
      </div>

      {error && (
        <p style={{ marginTop: "12px", fontSize: "13px", color: "#f87171", background: "#7f1d1d22", border: "1px solid #7f1d1d55", borderRadius: "8px", padding: "10px 12px" }}>
          {error}
        </p>
      )}

      <button
        onClick={handleUpload}
        disabled={!file || uploading}
        style={{
          marginTop: "16px", width: "100%", padding: "11px",
          fontSize: "14px", fontWeight: 600, borderRadius: "9px", border: "none",
          background: "var(--accent)", color: "#fff",
          cursor: (!file || uploading) ? "not-allowed" : "pointer",
          opacity: (!file || uploading) ? 0.45 : 1, transition: "opacity 0.15s",
        }}
      >
        {uploading ? "Processing…" : `Submit ${format === "shot" ? "shot" : "scene"} for moderation`}
      </button>

      {/* Result */}
      {job && (
        <div style={{ marginTop: "24px", borderRadius: "14px", padding: "20px", ...(RESULT_STYLE[status] ?? { border: "1px solid var(--border)", background: "var(--surface)" }) }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <p style={{ fontWeight: 600, color: "var(--fg)" }}>{job.filename}</p>
            <span style={{ fontSize: "13px", fontWeight: 600, color: RESULT_COLOR[status] ?? "var(--fg)", textTransform: "capitalize" }}>
              {status === "needs_review" ? "Held for review" : status}
            </span>
          </div>

          {job.department_tags && job.department_tags.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "14px" }}>
              {job.department_tags.map(t => (
                <span
                  key={t.department}
                  style={{
                    fontSize: "11px", fontWeight: 600, padding: "4px 10px", borderRadius: "999px",
                    background: t.is_primary ? "var(--accent)" : "var(--bg)",
                    color: t.is_primary ? "#fff" : "var(--fg-muted)",
                    border: t.is_primary ? "none" : "1px solid var(--border)",
                  }}
                >
                  {t.is_primary ? "🔒 " : ""}{t.department}{t.is_primary ? " — Main" : ""}
                </span>
              ))}
            </div>
          )}

          {job.reasons && job.reasons.length > 0 && (
            <ul style={{ fontSize: "12px", color: "var(--fg-muted)", marginBottom: "14px", display: "flex", flexDirection: "column", gap: "4px" }}>
              {job.reasons.map((r, i) => <li key={i}>• {r}</li>)}
            </ul>
          )}

          {job.pillars && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
              {job.pillars.map(p => (
                <div key={p.pillar}>
                  <p style={{ fontSize: "11px", color: "var(--fg-muted)", marginBottom: "4px" }}>
                    {p.pillar.replace(/_/g, " ")}
                  </p>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <div style={{ flex: 1, height: "4px", borderRadius: "999px", background: "var(--border)" }}>
                      <div style={{ height: "4px", borderRadius: "999px", background: "var(--accent)", width: `${Math.round(p.score * 100)}%` }} />
                    </div>
                    <span style={{ fontSize: "11px", fontFamily: "monospace", color: "var(--accent)" }}>{p.score}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
