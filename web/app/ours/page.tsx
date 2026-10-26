import Link from "next/link";
import { dateOf, fmt, get } from "@/lib/api";
import { Card, H1, Pill, Stat, Table } from "../ui";
import { Thumb } from "../thumb";

export const dynamic = "force-dynamic";

type Ours = {
  accounts: { handle: string; campaign_tag: string; product: string; added_at: number }[];
  posts: { id: string; url: string; author: string; desc: string; create_time: number; age_h: number; script_id: number | null; hook: string | null; concept: string | null; concept_id: number | null; views_now: number | null; views_72h: number | null; baseline_log: number | null; lift_72h: number | null; lift_now: number | null; n_obs: number }[];
  rewards: Record<string, { mean_reward: number; n: number }>;
};

export default async function Page() {
  const o = await get<Ours>("/ours");
  const beat = o.posts.filter((p) => (p.lift_72h ?? p.lift_now ?? 0) > 0).length;
  return (
    <>
      <H1 sub="Posts discovered on our accounts since tracking began. Caption matches connect posts to scripts; only matched posts can reward the concept picker. Older posts provide a baseline, not campaign results.">Our posts</H1>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="accounts watched" value={o.accounts.length} />
        <Stat label="posts found" value={o.posts.length} />
        <Stat label="beating own baseline" value={o.posts.length ? `${beat}/${o.posts.length}` : "-"} />
        <Stat label="concepts with reward" value={Object.keys(o.rewards).length} />
      </div>
      {o.accounts.length === 0 ? (
        <Card className="mb-4"><p className="text-sm text-amber-200">No posting account configured yet. Verify the browser session with <code>mkt own login</code>, then register it with <code>mkt own add @handle</code>. The next sync reads the profile directly; no campaign hashtag is required.</p></Card>
      ) : (
        <Card title="Accounts" className="mb-4">
          <Table head={["handle", "fallback tag", "product", "since"]} rows={o.accounts.map((a) => [<Link key={a.handle} href={`/creators/${a.handle}`} className="text-sky-300 hover:underline">@{a.handle}</Link>, a.campaign_tag ? `#${a.campaign_tag}` : "none", a.product, dateOf(a.added_at)])} />
        </Card>
      )}
      <Card title="Posts">
        {o.posts.length === 0 ? <p className="text-sm text-neutral-500">No campaign posts recorded. This does not mean the account has no existing TikTok posts.</p> : (
          <Table head={["", "posted", "post", "script / concept", "views now", "views 72h", "lift now", "lift 72h", ""]} rows={o.posts.map((p) => [
            <Thumb key={`t${p.id}`} id={p.id} href={`/videos/${p.id}`} />,
            dateOf(p.create_time),
            <Link key={p.id} href={`/videos/${p.id}`} className="text-sky-300 hover:underline">{(p.desc || p.id).slice(0, 60)}</Link>,
            p.script_id ? `#${p.script_id} · ${p.concept ?? "?"}` : <Pill key="u" tone="warn">no script matched</Pill>,
            p.views_now?.toLocaleString() ?? "", p.views_72h ? Math.round(p.views_72h).toLocaleString() : "not yet",
            fmt(p.lift_now), p.lift_72h == null ? (p.baseline_log == null ? "no baseline" : "not yet") : fmt(p.lift_72h),
            <span key="n" className="text-neutral-500">{p.n_obs} polls</span>,
          ])} />
        )}
      </Card>
      <Card title="What the picker is rewarded by (per concept, from our posts)" className="mt-4">
        {Object.keys(o.rewards).length === 0 ? <p className="text-sm text-neutral-500">No reward yet; picks follow the radar prior and exploration until a post of ours has a baseline and a curve.</p> : (
          <Table head={["concept id", "mean lift", "n"]} rows={Object.entries(o.rewards).map(([cid, r]) => [cid, fmt(r.mean_reward), r.n])} />
        )}
      </Card>
    </>
  );
}
