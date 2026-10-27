import type { Render } from "@/lib/api";

export const POST_RETRY_AFTER_S = 3600;
export const MAX_POST_ATTEMPTS = 4;
export const hoursSince = (t: number | null) => Math.round((Date.now() / 1000 - (t ?? 0)) / 3600);
export const stale = (r: Render) => !!r.post_session_url && hoursSince(r.post_requested_at) >= POST_RETRY_AFTER_S / 3600;
export const gaveUp = (r: Render) => stale(r) && (r.post_attempts ?? 0) >= MAX_POST_ATTEMPTS;

export type Status = "posted" | "on hold" | "posting" | "waiting" | "ready" | "rendered";
export const statusOf = (r: Render, posted: boolean): Status =>
  posted ? "posted" : r.hold_reason ? "on hold" : r.post_session_url && !stale(r) ? "posting" : r.post_session_url && !gaveUp(r) ? "waiting" : r.post_path ? "ready" : "rendered";
export const tone = (s: Status) => (s === "posted" ? "good" : s === "on hold" ? "bad" : s === "ready" ? "warn" : "neutral") as "good" | "bad" | "warn" | "neutral";

export const age = (h: number) => (h < 48 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`);
export const views = (n: number | null | undefined) => (n == null ? "" : n.toLocaleString("en-US"));
