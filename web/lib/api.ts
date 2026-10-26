export const API = (process.env.NEXT_PUBLIC_API_URL ?? "https://mkt-api.fly.dev").replace(/\/$/, "");

// Clips live next to the static dashboard (the daily run copies them there); the API only has the db.
export const CLIPS = (process.env.NEXT_PUBLIC_CLIPS_URL ?? "https://mkt-dashboard-eta.vercel.app/renders").replace(/\/$/, "");
// Poster frames (one jpg per downloaded video / clip) live beside the clips; `mkt frames` writes them.
export const FRAMES = (process.env.NEXT_PUBLIC_FRAMES_URL ?? "https://mkt-dashboard-eta.vercel.app/frames").replace(/\/$/, "");
export const frameUrl = (id: string) => `${FRAMES}/${id}.jpg`;
export const tiktokEmbed = (id: string) => `https://www.tiktok.com/embed/v2/${id}`;

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const dateOf = (ts: number) => new Date(ts * 1000).toISOString().slice(0, 10);
export const usd = (n: number) => `$${(n ?? 0).toFixed(2)}`;

export type Overview = {
  niche: string; videos: number; scored: number; tagged: number; concepts: number;
  spent_usd: number; winning: string;
  hooks: { hook_type: string; n: number; mean_reward: number; win_rate: number }[];
  styles: { visual_style: string; n: number; mean_reward: number; win_rate: number }[];
  stuck_accounts: { author: string; n?: number; median_views?: number }[];
  top_videos: { id: string; url: string; author: string; views: number; reward: number; hook_type: string; visual_style: string; desc: string }[];
};
export type Concept = { id: number; name: string; description: string; early_score: number; prior: number; mean_reward: number | null; n: number };
export type Script = { id: number; concept: string; product: string; created_at: number; hook: string; demo_score: number; captions: string[]; body: string; spoken?: string; hook_on_screen?: boolean; sound?: string; sound_url?: string };
export type Render = { id: number; script_id: number; created_at: number; model: string; cost_usd: number; hook: string };
export type Run = { id: number; created_at: number; session_id: string; url: string; niche: string; product: string; note: string };

export type Level = { level: string; n: number; coef: number; se: number; lo: number; hi: number; raw_mean: number; reference: boolean; verdict: string; travels?: boolean };
export type Fit = { n: number; k?: number; r2?: number; reference?: string; levels: Level[] };
export type Findings = {
  built_at?: number; collecting: boolean; min_n?: number;
  status: { videos: number; tagged?: number; with_baseline?: number; reached: Record<string, number>; eta_72h?: number | null; niches?: Record<string, number> };
  outcomes?: Record<string, string>;
  fits: Record<string, { pooled: Record<string, Fit>; per_niche: Record<string, Record<string, Fit>> }>;
};
export type Observation = { video_id: string; observed_at: number; views: number | null; likes: number | null; comments: number | null; shares: number | null; saves: number | null };
export type Features = Record<string, number | string | boolean | string[] | null>;
export type VideoDetail = {
  video: { id: string; url: string; author: string; followers: number | null; create_time: number; duration: number | null; desc: string; music: string; hashtags: string[]; source_tag: string; niche: string | null; cohort_at: number | null };
  observations: Observation[];
  tags: { tags: Record<string, unknown>; run: { model: string; prompt_version: string; latency_s: number; transcript: string; frame_times: number[] } } | null;
  tagged_at: number | null;
  features: Features | null;
  creator: { followers: number | null; n_posts: number; median_views: number | null; video_count: number | null; heart_count: number | null; taken_at: number } | null;
};
export type CreatorDetail = {
  handle: string;
  videos: { id: string; url: string; desc: string; create_time: number; duration: number | null; music: string; source_tag: string; niche: string | null; cohort_at: number | null; views: number | null; likes: number | null; lift_72h: number | null }[];
  snapshots: { taken_at: number; followers: number | null; n_posts: number; median_views: number | null; video_count: number | null; heart_count: number | null }[];
};
export const ageH = (createTime: number, at: number) => (at - createTime) / 3600;
export const fmt = (n: number | null | undefined, d = 2) => (n === null || n === undefined ? "" : n.toFixed(d));
