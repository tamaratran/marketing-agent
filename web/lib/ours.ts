export type OursPost = { id: string; url: string; author: string; desc: string; create_time: number; age_h: number; script_id: number | null; hook: string | null; concept: string | null; concept_id: number | null; views_now: number | null; views_72h: number | null; baseline_log: number | null; lift_72h: number | null; lift_now: number | null; n_obs: number };
export type Ours = {
  accounts: { handle: string; campaign_tag: string; product: string; added_at: number }[];
  posts: OursPost[];
  rewards: Record<string, { mean_reward: number; n: number }>;
};
