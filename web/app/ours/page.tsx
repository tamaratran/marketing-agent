import Link from "next/link";
import { dateOf, get, type Concept } from "@/lib/api";
import type { Ours } from "@/lib/ours";
import { Card, H1, Note, Pill, Stat, Table, reward, formatName } from "../ui";
import { Thumb } from "../thumb";
import { addPost } from "../actions";

export const dynamic = "force-dynamic";


export default async function Page() {
  const [o, concepts] = await Promise.all([get<Ours>("/ours"), get<Concept[]>("/concepts")]);
  const conceptName = new Map(concepts.map((c) => [String(c.id), formatName(c.name)]));
  const beat = o.posts.filter((p) => (p.lift_matched ?? p.lift_72h ?? p.lift_now ?? 0) > 0).length;
  return (
    <>
      <H1 sub="How our own TikTok posts are doing. This is the only page that uses our account's results; everything else is research on other accounts.">Our posts</H1>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="accounts we post from" value={o.accounts.length} />
        <Stat label="posts since registering" value={o.posts.length} hint="Older posts only set the account's usual views." />
        <Stat label="ahead of videos like them" value={o.posts.length ? `${beat}/${o.posts.length}` : "none yet"} hint="Same age, same account size, this niche." />
        <Stat label="concepts with results" value={Object.keys(o.rewards).length} hint="Concepts at least one matched post has tested." />
      </div>
      {o.accounts.length === 0 ? (
        <Card className="mb-4"><p className="text-sm text-amber-200">No posting account configured yet. Verify the browser session with <code>mkt own login</code>, then register it with <code>mkt own add @handle</code>. The next sync reads the profile directly; no campaign hashtag is required.</p></Card>
      ) : (
        <Card title="Accounts" className="mb-4">
          <Table head={["handle", "backup hashtag", "product", "registered"]} rows={o.accounts.map((a) => [<Link key={a.handle} href={`/creators/${a.handle}`} className="text-sky-300 hover:underline">@{a.handle}</Link>, a.campaign_tag ? `#${a.campaign_tag}` : "none", a.product, dateOf(a.added_at)])} />
        </Card>
      )}
      <Card title="I posted a clip" className="mb-4">
        <Note className="mb-3">Paste the TikTok link of a post you made from our account, plus the caption you used so it links to its script right away. Its stats refresh at the start of every run cycle or when you choose &quot;Check post performance&quot;. A post still under review fills in once TikTok makes it public.</Note>
        <form action={addPost} className="flex flex-wrap items-center gap-2">
          <input name="url" required placeholder="https://www.tiktok.com/@handle/video/..." className="min-w-[18rem] flex-1 rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm" />
          <input name="caption" placeholder="caption you used (optional)" className="min-w-[18rem] flex-1 rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm" />
          <button className="rounded-md bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500">Add post</button>
        </form>
      </Card>
      <Card title="Posts">
        <Note className="mb-3">Each post is matched to the script it came from by caption. &quot;vs videos like it&quot; compares its views with what a video of the same age from an account of the same size typically has in this niche right now; that, plus half of how its shares and saves per 1k views compare with the niche (log10), is what the picker learns from once the post is 6 hours old. &quot;vs our usual&quot; compares with the account&apos;s own posts, whatever their age, which flatters or punishes a fresh post, so it is shown for reference only.</Note>
        {o.posts.length === 0 ? <p className="text-sm text-neutral-500">No posts since the account was registered. Post a clip from the Clips page, then add its link above.</p> : (
          <Table head={["", "posted", "post", "script / concept", "views now", "views at 3 days", "vs videos like it", "shares+saves per 1k", "vs our usual at 3 days", ""]} rows={o.posts.map((p) => [
            <Thumb key={`t${p.id}`} id={p.id} href={`/videos/${p.id}`} />,
            dateOf(p.create_time),
            <Link key={p.id} href={`/videos/${p.id}`} className="text-sky-300 hover:underline">{(p.desc || p.id).slice(0, 60)}</Link>,
            p.script_id ? `#${p.script_id} · ${p.concept ? formatName(p.concept) : "?"}` : <Pill key="u" tone="warn">no script matched</Pill>,
            p.views_now?.toLocaleString() ?? "", p.views_72h ? Math.round(p.views_72h).toLocaleString() : "not yet",
            reward(p.lift_matched, p.views_now ? "no reference videos yet" : "no views yet"),
            p.engagement_per_1k != null ? <span key="e">{p.engagement_per_1k} <span className="text-neutral-500">({p.engagement_lift != null ? `${p.engagement_lift > 0 ? "+" : ""}${p.engagement_lift.toFixed(2)} vs niche` : "no niche median"})</span></span> : "",
            reward(p.lift_72h, p.baseline_log == null ? "no baseline" : "not yet"),
            <span key="n" className="text-neutral-500">{p.n_obs} polls</span>,
          ])} />
        )}
      </Card>
      <Card title="What the picker has learned from our posts" className="mt-4">
        {Object.keys(o.rewards).length === 0 ? <p className="text-sm text-neutral-500">Nothing yet. Until one of our posts has results, the daily pick follows what is working for other accounts, with some exploring.</p> : (
          <Table head={["concept", "average vs videos like it, age-weighted", "posts"]} rows={Object.entries(o.rewards).map(([cid, r]) => [conceptName.get(cid) ?? `#${cid}`, reward(r.mean_reward), r.n])} />
        )}
      </Card>
    </>
  );
}
