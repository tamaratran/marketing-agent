import { get, usd, type Overview } from "@/lib/api";
import { Card, H1, Stat, Table, reward } from "./ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const o = await get<Overview>("/overview");
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
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Hooks">
          <Table head={["hook", "n", "reward", "win rate"]} rows={o.hooks.map((h) => [h.hook_type, h.n, reward(h.mean_reward), `${Math.round(h.win_rate * 100)}%`])} />
        </Card>
        <Card title="Styles">
          <Table head={["style", "n", "reward", "win rate"]} rows={o.styles.map((s) => [s.visual_style, s.n, reward(s.mean_reward), `${Math.round(s.win_rate * 100)}%`])} />
        </Card>
      </div>
      <Card title="Fed into tomorrow's scripts" className="mt-4">
        <pre className="whitespace-pre-wrap text-sm text-neutral-300">{o.winning || "Nothing beats baseline yet."}</pre>
      </Card>
      {o.stuck_accounts.length > 0 && (
        <Card title="Accounts that look throttled" className="mt-4">
          <Table head={["account", "posts", "median views"]} rows={o.stuck_accounts.map((a) => [a.author, a.n ?? "", a.median_views ?? ""])} />
        </Card>
      )}
      <Card title="Top tagged videos" className="mt-4">
        <Table
          head={["video", "author", "views", "reward", "hook", "style"]}
          rows={o.top_videos.map((v) => [
            <a key={v.id} href={v.url} target="_blank" className="text-sky-300 hover:underline">{(v.desc || v.id).slice(0, 60)}</a>,
            `@${v.author}`, v.views.toLocaleString(), reward(v.reward), v.hook_type, v.visual_style,
          ])}
        />
      </Card>
    </>
  );
}
