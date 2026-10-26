import Link from "next/link";
import { API, get, type Campaign, type CycleFacts, type Learning, type Overview, type Render, type Run, type Script } from "@/lib/api";
import { startRenders, startResearch } from "../actions";
import { TraitBars, Trend, type RankRow } from "../charts";
import { Markdown } from "../md";
import { Card, H1, Note, Pill, button, formatName, ghost, times } from "../ui";

export const dynamic = "force-dynamic";

/** Server component: read once per request. */
const nowSec = () => Math.floor(Date.now() / 1000);

const when = (ts: number) => new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC";

const TABLES: [keyof NonNullable<CycleFacts["traits"]>, string, string][] = [
  ["hooks", "hook_type", "Hook type"],
  ["styles", "visual_style", "Visual style"],
  ["pacing", "pacing_bucket", "Pacing (cuts per 10s)"],
  ["sound", "music_role", "Sound"],
  ["product_early", "product_on_screen_by_5s", "Product on screen by 5s"],
];
const LIVE: Record<string, keyof Overview> = { hooks: "hooks", styles: "styles", pacing: "pacing", sound: "sound", product_early: "product_early" };

export default async function Page() {
  const [rows, o, scripts, renders, runs, c] = await Promise.all([
    get<Learning[]>("/learnings?limit=100"), get<Overview>("/overview"),
    get<Script[]>("/scripts?days=14&limit=200"), get<Render[]>("/renders"), get<Run[]>("/runs?limit=5"), get<Campaign>("/campaign"),
  ]);
  const newest = scripts.reduce((m, s) => Math.max(m, s.created_at), 0);
  const batch = scripts.filter((s) => s.created_at >= newest - 20 * 60).sort((a, b) => b.demo_score - a.demo_score || a.id - b.id);
  const rendered = new Set(renders.map((r) => r.script_id));
  const now = nowSec();
  const running = runs.find((r) => !r.finished_at && now - r.created_at < 3 * 3600);
  const cycles = rows.filter((e) => e.kind === "cycle" && e.facts).sort((a, b) => a.created_at - b.created_at);
  const latest = cycles[cycles.length - 1]?.facts;
  const tables = TABLES.map(([key, col, title]) => ({ key, col, title, rows: ((latest?.traits?.[key] as RankRow[] | undefined) ?? (o[LIVE[key]] as RankRow[])) ?? [] })).filter((t) => t.rows.length);
  const scoredPts = cycles.filter((c) => c.facts.n_scored != null).map((c) => ({ t: c.created_at, v: c.facts.n_scored as number }));
  const taggedPts = cycles.filter((c) => c.facts.n_tagged != null).map((c) => ({ t: c.created_at, v: c.facts.n_tagged as number }));
  const ownPts = cycles.filter((c) => c.facts.own_mean_lift != null).map((c) => ({ t: c.created_at, v: c.facts.own_mean_lift as number }));
  const clonePts = cycles.flatMap((c) => { const p = c.facts.picks?.find((x) => /clone/i.test(x.name)); return p ? [{ t: c.created_at, v: p.share }] : []; });
  const nScored = latest?.n_scored ?? o.scored, nTagged = latest?.n_tagged ?? o.tagged, nVideos = latest?.n_videos ?? o.videos;
  return (
    <>
      <H1 sub="What the data says, what the agent wrote about it, and what it proposes to make next.">Learnings</H1>

      <Card title="Research again" className="mb-4">
        <form action={startResearch} className="flex flex-wrap items-center gap-3">
          <button className={ghost} disabled={!!running}>Research again</button>
          <Note>
            Re-measures our posts, re-scrapes the market and rewrites the learnings and the proposed scripts below. About 15 minutes, no clips, so no fal cost.
            {running && <> A run is already going: <Link href="/runs" className="text-sky-300 hover:underline">see Runs</Link>.</>}
          </Note>
        </form>
      </Card>

      <Card title="What the numbers say now">
        <Note>
          {nVideos} {o.niche} videos tracked, {nScored} scored (a day old, views against {o.niche} videos of the same age and account size), {nTagged} classified by the vision model. Each bar is the mean lift of videos with that trait: 1x means the same views as videos like it, 10x ten times more. The thin white tick is one standard error, the number on the right is how many scored videos the bar rests on, and faint bars rest on fewer.
          {nTagged < 30 && <> With {nTagged} classified so far these are early reads, not verdicts; they firm up as each cycle classifies more.</>}
        </Note>
        {tables.length === 0 ? (
          <Note className="mt-3">No trait has two scored, classified videos yet. The bars appear once a cycle classifies videos that are a day old.</Note>
        ) : (
          <div className="mt-4 grid gap-6 sm:grid-cols-2">
            {tables.map((t) => <TraitBars key={t.key} rows={t.rows} column={t.col} title={t.title} />)}
          </div>
        )}
      </Card>

      {cycles.length > 0 && (
        <Card title="Cycle to cycle" className="mt-4">
          <Note>One point per cycle entry. These are the numbers the &quot;Changed since last cycle&quot; lines are computed from.</Note>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Trend points={scoredPts} label="Research videos scored" fmt={(v) => String(Math.round(v))} />
            <Trend points={taggedPts} label="Videos classified" fmt={(v) => String(Math.round(v))} />
            <Trend points={ownPts} label="Our posts, mean lift" fmt={(v) => `${times(v)} videos like them`} />
            <Trend points={clonePts} label="Clone format's pick share" fmt={(v) => `${Math.round(v * 100)}%`} />
          </div>
          {ownPts.length === 0 && <Note className="mt-2">Our posts have no measured lift yet (a post counts once it is 6 hours old).</Note>}
        </Card>
      )}

      <Card title="Proposed next scripts" className="mt-4">
        {batch.length === 0 ? <Note>No scripts yet. Research again writes the first batch.</Note> : (
          <>
            <Note>The latest batch, best demo score first, all in the format {formatName(batch[0].concept)}. Written {when(newest)}.</Note>
            <ul className="mt-3 divide-y divide-neutral-800 text-sm">
              {batch.map((s) => (
                <li key={s.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
                  <span className="w-12 shrink-0 text-xs text-neutral-500">s{s.id}</span>
                  <Link href={`/scripts#s${s.id}`} className="font-medium text-neutral-100 hover:underline">{s.hook}</Link>
                  <span className="text-xs text-neutral-500">demo {s.demo_score}/5</span>
                  {rendered.has(s.id) && <Link href="/clips" className="text-xs text-emerald-300 hover:underline">clip ready</Link>}
                </li>
              ))}
            </ul>
            <form action={startRenders} className="mt-4 flex flex-wrap items-center gap-3">
              <button className={button} disabled={!!running}>Generate clips</button>
              <Note>Renders the best {c.cycle.clips} not-yet-rendered scripts above at {c.cycle.resolution}, about ${(c.cycle.clips * (c.cycle.resolution === "1080p" ? 9.6 : c.cycle.resolution === "480p" ? 2.65 : 5.68)).toFixed(0)} on fal. Clips land on the Clips page for you to post; nothing is posted automatically.</Note>
            </form>
          </>
        )}
      </Card>

      <Note className="my-4">
        The same text as one file: <a href={`${API}/learnings.md`} className="text-sky-300 hover:underline" target="_blank">learnings.md</a>
      </Note>
      {rows.length === 0 && <Card><Note>Nothing yet. The first cycle writes the first entry.</Note></Card>}
      <div className="space-y-4">
        {rows.map((e) => (
          <Card key={e.id}>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="font-semibold text-neutral-100">{e.title}</span>
              <Pill tone={e.kind === "cycle" ? "neutral" : "good"}>{e.kind === "cycle" ? "measured" : "observation"}</Pill>
              <span className="text-xs text-neutral-500">{when(e.created_at)} · {e.niche}</span>
              {e.kind === "cycle" && e.facts?.n_scored != null && (
                <span className="text-xs text-neutral-500">· {e.facts.n_scored} scored · {e.facts.n_tagged ?? 0} classified · {e.facts.own_posts ?? 0} of ours{e.facts.own_mean_lift != null && <>, mean {times(e.facts.own_mean_lift)}</>}</span>
              )}
            </div>
            <Markdown text={formatName(e.body)} />
          </Card>
        ))}
      </div>
    </>
  );
}
