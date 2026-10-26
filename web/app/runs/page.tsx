/* eslint-disable @next/next/no-img-element */
import { dateOf, get, type Campaign, type Run } from "@/lib/api";
import { startRun } from "../actions";
import { button, Card, H1, Note, Table } from "../ui";
import { RefreshButtons } from "../refresh";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [rows, c] = await Promise.all([get<Run[]>("/runs"), get<Campaign>("/campaign")]);
  const perClip = { "480p": 2.65, "720p": 5.7, "1080p": 9.6 }[c.cycle.resolution] ?? 5.7;
  return (
    <>
      <H1 sub="A cycle is one pass of the loop, done by a Devin session on demand: re-read the product's best TikToks and how our own posts did, write better scripts, render the clips and put them on Clips with caption and sound, ready for a human to post. Nothing runs on a schedule and nothing is posted automatically.">Runs</H1>
      <Card title="Run a cycle" className="mb-5">
        <form action={startRun} className="flex flex-wrap items-center gap-3">
          <button className={button}>Run cycle</button>
          <Note>About 30 to 60 minutes. Costs a Devin session (capped at {c.cycle.max_acu} ACUs) plus fal: about ${perClip.toFixed(2)} per 12s clip at {c.cycle.resolution}, {c.cycle.clips} clips per cycle.</Note>
        </form>
      </Card>
      <Card title="What a cycle works on" className="mb-5">
        <Note className="mb-3">From <code>campaign.toml</code> in the repo. To market something else, edit that file and merge; nothing on this page needs changing.</Note>
        <Table
          head={["", ""]}
          rows={[
            ["posting account", c.account.handle ? <a key="a" href={`https://www.tiktok.com/@${c.account.handle}`} target="_blank" className="text-sky-300 hover:underline">@{c.account.handle}</a> : "none registered"],
            ["niche watched", `${c.niche.name}: ${c.niche.hashtags.map((t) => `#${t}`).join(" ")}`],
            ["product", <span key="p">{c.product.name}{c.product.developer ? ` by ${c.product.developer}` : ""}{c.product.website ? <> · <a href={c.product.website} target="_blank" className="text-sky-300 hover:underline">site</a></> : null}{c.product.app_store ? <> · <a href={c.product.app_store} target="_blank" className="text-sky-300 hover:underline">App Store</a></> : null}</span>],
            ["how scripts describe it", c.product.description],
            ["TikToks whose format is cloned", c.product.hashtags.length ? c.product.hashtags.map((t) => `#${t}`).join(" ") : "none, niche concepts only"],
            ["reference images for renders", <span key="r" className="flex gap-2">{c.product.references.map((u) => <a key={u} href={u} target="_blank"><img src={u} alt="" className="h-14 rounded border border-neutral-800" /></a>)}</span>],
            ["per cycle", `${c.cycle.clips} clips at ${c.cycle.resolution}`],
          ]}
        />
      </Card>
      <Card title="Refresh without a full run" className="mb-5">
        <RefreshButtons />
      </Card>
      <Card title="Runs started here">
        <Table
          head={["started", "niche", "product", "session", "note"]}
          rows={rows.map((r) => [dateOf(r.created_at), r.niche, r.product, <a key="u" href={r.url} target="_blank" className="text-sky-300 hover:underline">{r.session_id}</a>, r.note])}
          empty="None yet. Cycles started from the CLI are listed too; their results show up on the other pages."
        />
      </Card>
    </>
  );
}
