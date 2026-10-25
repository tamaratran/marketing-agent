export const API = (process.env.NEXT_PUBLIC_API_URL ?? "https://mkt-api.fly.dev").replace(/\/$/, "");

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const dateOf = (ts: number) => new Date(ts * 1000).toISOString().slice(0, 10);
export const usd = (n: number) => `$${(n ?? 0).toFixed(2)}`;

export type Overview = {
  niche: string; videos: number; scored: number; tagged: number; concepts: number;
  spent_usd: number; owed_usd: number; winning: string;
  hooks: { hook_type: string; n: number; mean_reward: number; win_rate: number }[];
  styles: { visual_style: string; n: number; mean_reward: number; win_rate: number }[];
  stuck_accounts: { author: string; n?: number; median_views?: number }[];
  top_videos: { id: string; url: string; author: string; views: number; reward: number; hook_type: string; visual_style: string; desc: string }[];
};
export type Concept = { id: number; name: string; description: string; early_score: number; prior: number; mean_reward: number | null; n: number };
export type Script = { id: number; concept: string; product: string; created_at: number; hook: string; demo_score: number; captions: string[]; body: string };
export type Render = { id: number; script_id: number; created_at: number; model: string; cost_usd: number; hook: string };
export type Creator = { handle: string; channel: string; rate_per_1k: number; posts: number; median_views: number | null; last_post: string | null; days_since: number | null; status: string };
export type Brief = { id: number; created_at: number; product: string; script_ids: string; rate_per_1k: number; cap_usd: number; deadline_days: number; body: string; status: string };
export type Payout = { creator: string; video_id: string; url: string; age_days: number; views: number; rate_per_1k: number; owed_usd: number; settled: boolean; paid_usd: number };
export type Run = { id: number; created_at: number; session_id: string; url: string; niche: string; product: string; note: string };
