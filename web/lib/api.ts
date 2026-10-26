import { notFound } from "next/navigation";

export const API = (process.env.NEXT_PUBLIC_API_URL ?? "https://mkt-api.fly.dev").replace(/\/$/, "");

// Clips live next to the static dashboard (the daily run copies them there); the API only has the db.
export const CLIPS = (process.env.NEXT_PUBLIC_CLIPS_URL ?? "https://mkt-dashboard-eta.vercel.app/renders").replace(/\/$/, "");
// Poster frames (one jpg per downloaded video / clip) live beside the clips; `mkt frames` writes them.
export const FRAMES = (process.env.NEXT_PUBLIC_FRAMES_URL ?? "https://mkt-dashboard-eta.vercel.app/frames").replace(/\/$/, "");
export const frameUrl = (id: string) => `${FRAMES}/${id}.jpg`;
export const tiktokEmbed = (id: string) => `https://www.tiktok.com/embed/v2/${id}`;

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  if (r.status === 404) notFound();
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
  pacing: { pacing_bucket: string; n: number; mean_reward: number; stderr: number; win_rate: number }[];
  sound: { music_role: string; n: number; mean_reward: number; stderr: number; win_rate: number }[];
  product_early: { product_on_screen_by_5s: string; n: number; mean_reward: number; stderr: number; win_rate: number }[];
  stuck_accounts: { author: string; n?: number; median_views?: number }[];
  top_videos: { id: string; url: string; author: string; views: number; reward: number | null; hook_type: string; visual_style: string; desc: string; source_tag?: string; create_time?: number }[];
};
export type TraitDetail = { trait: string; value: string | boolean; ours: number; ours_n: number; market: number; market_n: number };
export type Concept = {
  id: number; name: string; description: string; early_score: number; prior: number; mean_reward: number | null; n: number; kind?: string;
  traits?: Record<string, string | boolean | null>; trait_bonus?: number; trait_detail?: TraitDetail[]; learned?: number; pick_share?: number;
  examples?: { id: string; author: string; url: string; views: number | null; reward?: number | null }[];
};
export type Script = { id: number; concept: string; product: string; created_at: number; hook: string; demo_score: number; captions: string[]; body: string; spoken?: string; hook_on_screen?: boolean; sound?: string; sound_url?: string; why?: ScriptWhy | null };
export type ScriptWhy = { pick_share?: number; head_start?: number; expected_lift?: number; own_mean_reward?: number | null; own_n?: number; kind?: string; traits?: { trait: string; value: string | boolean | null; ours: number; ours_n: number; market: number; market_n: number }[] };
export type Render = { id: number; script_id: number; created_at: number; model: string; cost_usd: number; hook: string; post_path: string | null; post_text: string[]; hold_reason: string | null; post_session_url: string | null; post_requested_at: number | null };
export type Campaign = {
  account: { handle: string; backup_hashtag: string };
  niche: { name: string; hashtags: string[] };
  product: { name: string; developer: string; website: string; app_store: string; description: string; hashtags: string[]; references: string[] };
  cycle: { clips: number; resolution: string; max_acu: number };
  path: string;
};
export type CycleFacts = {
  n_videos?: number; n_scored?: number; n_tagged?: number; own_posts?: number; own_mean_lift?: number | null; top_concept?: string;
  traits?: Record<string, { n: number; mean_reward: number; stderr?: number; win_rate: number }[] & Record<string, unknown>[]>;
  picks?: { name: string; share: number; n: number }[];
  own?: { url: string; concept: string | null; age_h: number; views: number | null; lift: number | null; engagement_per_1k: number | null }[];
};
export type Learning = { id: number; created_at: number; niche: string; product: string; kind: string; title: string; body: string; facts: CycleFacts };
export type Run = { id: number; created_at: number; session_id: string; url: string; niche: string; product: string; note: string; status?: string | null; stages?: string | null; finished_at?: number | null };
export type RunStage = { stage: string; status: string; seconds: number; note: string };

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
  video: { id: string; url: string; author: string; followers: number | null; create_time: number; duration: number | null; desc: string; music: string; hashtags: string[]; source_tag: string; niche: string | null; cohort_at: number | null; gone_at: number | null };
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

export type Logic = {
  niche: string;
  videos: { id: string; author: string; views: number | null; followers: number | null; create_time: number; observed_at: number | null; log_views: number; expected: number; creator_offset: number; baseline: number; reward: number | null; engagement_per_1k?: number; engagement_lift?: number | null; reward_total?: number | null }[];
  explore_sd: number; format_edge?: number; shrink_k?: number; market_trait_weight?: number; format_prior: number | null; min_age_h: number; min_age_h_own?: number; winsor_pct: number; engagement_weight?: number;
  curve: { a: number; b: number; c: number; n: number; sd: number; followers_fill: number } | null;
};
