export type OursPost = { id: string; url: string; author: string; desc: string; create_time: number; age_h: number; script_id: number | null; hook: string | null; concept: string | null; concept_id: number | null; views_now: number | null; views_72h: number | null; baseline_log: number | null; lift_72h: number | null; lift_now: number | null; n_obs: number; followers: number | null; expected_log: number | null; lift_matched: number | null; account_offset: number; engagement_per_1k: number | null; engagement_lift: number | null };
export type Ours = {
  accounts: { handle: string; campaign_tag: string; product: string; added_at: number }[];
  posts: OursPost[];
  rewards: Record<string, { mean_reward: number; n: number }>;
};
