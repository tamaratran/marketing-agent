import Link from "next/link";
import { get, usd, type Findings, type Overview } from "@/lib/api";
import { Card, H1, Stat, Table, reward } from "./ui";
import { Thumb } from "./thumb";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [o, fs] = await Promise.all([get<Overview>("/overview"), get<Findings>("/findings")]);
  return (
    <>
      <H1 sub={`${o.niche}: what the loop has seen and what is beating the account baseline`}>Overview</H1>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-6">
        <Stat label="videos tracked" value={o.videos} />
        <Stat label="scored" value={o.scored} />
        <Stat label="tagged by classifier" value={o.tagged} />
        <Stat label="concepts" value={o.concepts} />
        <Stat label="spent on clips" value={usd(o.spent_usd)} />
        <Stat label="owed to creators" value={usd(o.owed_usd)} />
      </div>
      <Card title="Learning status">
        <p className="text-sm text-neutral-300">
          {fs.status.videos} cohort videos being followed, {fs.status.tagged ?? 0} tagged, {fs.status.reached["72h"] ?? 0} have reached 72h.
          {fs.collecting
            ? ` Still collecting: no trait is called better or worse until ${fs.min_n ?? 20} videos per cell reach 72h${fs.status.eta_72h ? ` (first ones around ${new Date(fs.status.eta_72h * 1000).toUTCString()})` : ""}.`
            : " Controlled findings are in."}
          {" "}<Link href="/findings" className="text-sky-300 hover:underline">Findings</Link>
        </p>
      </Card>
      {o.stuck_accounts.length > 0 && (
        <Card title="Accounts that look throttled" className="mt-4">
          <Table head={["account", "posts", "median views"]} rows={o.stuck_accounts.map((a) => [a.author, a.n ?? "", a.median_views ?? ""])} />
        </Card>
      )}
      <Card title="Top tagged videos (reward = log views vs the account baseline, uncontrolled)" className="mt-4">
        <Table
          head={["", "video", "author", "views", "reward", "hook", "style"]}
          rows={o.top_videos.map((v) => [
            <Thumb key={`t${v.id}`} id={v.id} href={`/videos/${v.id}`} />,
            <Link key={v.id} href={`/videos/${v.id}`} className="text-sky-300 hover:underline">{(v.desc || v.id).slice(0, 60)}</Link>,
            <Link key={`a${v.id}`} href={`/creators/${v.author}`} className="hover:underline">@{v.author}</Link>, v.views.toLocaleString(), reward(v.reward), v.hook_type, v.visual_style,
          ])}
        />
      </Card>
    </>
  );
}
