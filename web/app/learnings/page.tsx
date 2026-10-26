import Link from "next/link";
import { API, get, type Campaign, type CycleFacts, type Findings, type Learning, type Render, type Run, type Script } from "@/lib/api";
import { startRenders, startResearch } from "../actions";
import { Trend, traitValue, type RankRow } from "../charts";
import { Markdown } from "../md";
import { Card, Fold, H1, NextStep, Note, Pill, button, formatName, ghost, times } from "../ui";

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

export default async function Page() {
  const [rows, scripts, renders, runs, c, fs] = await Promise.all([
    get<Learning[]>("/learnings?limit=100"),
    get<Script[]>("/scripts?days=14&limit=200"), get<Render[]>("/renders"), get<Run[]>("/runs?limit=5"), get<Campaign>("/campaign"),
    get<Findings>("/findings"),
  ]);
  const minN = fs.min_n ?? 20;
  const newest = scripts.reduce((m, s) => Math.max(m, s.created_at), 0);
  const lift = (s: Script) => s.why?.expected_lift ?? 0;
  const batch = scripts.filter((s) => s.created_at >= newest - 20 * 60).sort((a, b) => lift(b) - lift(a) || b.demo_score - a.demo_score || a.id - b.id);
  const batchFormats = [...new Set(batch.map((s) => s.concept))];
  const rendered = new Set(renders.map((r) => r.script_id));
  const now = nowSec();
  const running = runs.find((r) => !r.finished_at && now - r.created_at < 3 * 3600);
  const cycles = rows.filter((e) => e.kind === "cycle" && e.facts).sort((a, b) => a.created_at - b.created_at);
  const latest = cycles[cycles.length - 1]?.facts;
  const prev = cycles[cycles.length - 2]?.facts;
  const scoredPts = cycles.filter((c) => c.facts.n_scored != null).map((c) => ({ t: c.created_at, v: c.facts.n_scored as number }));
  const taggedPts = cycles.filter((c) => c.facts.n_tagged != null).map((c) => ({ t: c.created_at, v: c.facts.n_tagged as number }));
  const ownPts = cycles.filter((c) => c.facts.own_mean_lift != null).map((c) => ({ t: c.created_at, v: c.facts.own_mean_lift as number }));
  const clonePts = cycles.flatMap((c) => { const p = c.facts.picks?.find((x) => /clone/i.test(x.name)); return p ? [{ t: c.created_at, v: p.share }] : []; });
  return (
    <>
      <H1 sub="What the data says, what the agent wrote about it, and what it proposes to make next.">Learnings</H1>

      <Card title="Research again" className="mb-4">
        <form action={startResearch} className="flex flex-wrap items-center gap-3">
          <button className={ghost} disabled={!!running}>Research again</button>
          <Note>
            About an hour the first time, then about 15 minutes. No clips, so no fal cost.
            {running && <> A run is already going: <Link href="/runs" className="text-sky-300 hover:underline">see Runs</Link>.</>}
          </Note>
        </form>
      </Card>

      <Card title="What the data says">
        <Note>
          {latest ? <>From the cycle of {when(cycles[cycles.length - 1].created_at)}: {latest.n_scored ?? 0} research videos scored against videos of the same age and account size, {latest.n_tagged ?? 0} of them classified by trait. </> : null}
          What wins now is on <Link href="/" className="text-sky-300 hover:underline">Formats</Link>.
        </Note>
        {!latest ? (
          <Note className="mt-3">No cycle entry yet. Research again writes the first one.</Note>
        ) : (
          <>
            <TraitSentences latest={latest} prev={prev} minN={minN} />
            {prev && (
              <>
                <h3 className="mt-5 text-sm font-medium text-neutral-200">Since the cycle of {when(cycles[cycles.length - 2].created_at)}</h3>
                <dl className="mt-2 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-5">
                  <Delta label="Videos scored" was={prev.n_scored} now={latest.n_scored} fmt={(v) => String(Math.round(v))} />
                  <Delta label="Videos classified" was={prev.n_tagged} now={latest.n_tagged} fmt={(v) => String(Math.round(v))} />
                  <Delta label="Our posts measured" was={prev.own_posts} now={latest.own_posts} fmt={(v) => String(Math.round(v))} />
                  <Delta label="Our posts, mean lift" was={prev.own_mean_lift} now={latest.own_mean_lift} fmt={(v) => `${times(v)} videos like them`} />
                  <Delta label="Clone format's pick share" was={cloneShare(prev)} now={cloneShare(latest)} fmt={(v) => `${Math.round(v * 100)}%`} />
                </dl>
              </>
            )}
          </>
        )}
      </Card>

      {cycles.length > 0 && (
        <Card title="Cycle to cycle" className="mt-4">

          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Trend points={scoredPts} label="Research videos scored" fmt={(v) => String(Math.round(v))} />
            <Trend points={taggedPts} label="Videos classified" fmt={(v) => String(Math.round(v))} />
            <Trend points={ownPts} label="Our posts, mean lift" fmt={(v) => `${times(v)} videos like them`} />
            <Trend points={clonePts} label="Clone format's pick share" fmt={(v) => `${Math.round(v * 100)}%`} />
          </div>
          {scoredPts.length + taggedPts.length + clonePts.length === 0 && <Note className="mt-2">Nothing to plot yet; the next cycle adds the first point.</Note>}
          {ownPts.length === 0 && <Note className="mt-2">No post is 6 hours old yet.</Note>}
        </Card>
      )}

      <Card title="Proposed next scripts" className="mt-4">
        {batch.length === 0 ? <Note>No scripts yet. Research again writes the first batch.</Note> : (
          <>
            <Note>
              {batch.length} scripts across {batchFormats.length} format{batchFormats.length === 1 ? "" : "s"} ({batchFormats.map(formatName).join(", ")}), written {when(newest)}.

            </Note>
            <ul className="mt-3 space-y-2 text-sm">
              {batch.map((s) => (
                <li key={s.id}>
                  <Fold summary={
                    <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <span className="w-12 shrink-0 text-xs text-neutral-500">s{s.id}</span>
                      <span className="font-medium text-neutral-100">{s.hook}</span>
                      <span className="text-xs text-neutral-400">{formatName(s.concept)}</span>
                      {s.why?.expected_lift != null && <span className={`text-xs ${s.why.expected_lift >= 0 ? "text-emerald-300" : "text-red-300"}`}>{times(s.why.expected_lift)} expected</span>}
                      <span className="text-xs text-neutral-500">demo {s.demo_score}/5</span>
                      {rendered.has(s.id) && <Link href="/clips" className="text-xs text-emerald-300 hover:underline">clip ready</Link>}
                    </span>
                  }>
                    <Why s={s} />
                  </Fold>
                </li>
              ))}
            </ul>
            <form action={startRenders} className="mt-4 flex flex-wrap items-center gap-3">
              <button className={button} disabled={!!running}>Generate clips</button>
              <Note>{c.cycle.clips} clips at {c.cycle.resolution}, about ${(c.cycle.clips * (c.cycle.resolution === "1080p" ? 9.6 : c.cycle.resolution === "480p" ? 2.65 : 5.68)).toFixed(0)} on fal. Each finished clip is posted to our account and tracked on Our posts; held clips are not posted.</Note>
            </form>
          </>
        )}
      </Card>

      <Note className="my-4">
        The same text as one file: <a href={`${API}/learnings.md`} className="text-sky-300 hover:underline" target="_blank">learnings.md</a>
      </Note>
      {rows.length === 0 && <Card><Note>Nothing yet. The first cycle writes the first entry.</Note></Card>}
      <div className="space-y-2">
        {rows.map((e, i) => (
          <Fold key={e.id} open={i === 0} summary={
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-neutral-100">{e.title}</span>
              <Pill tone={e.kind === "cycle" ? "neutral" : "good"}>{e.kind === "cycle" ? "measured" : "observation"}</Pill>
              <span className="text-xs text-neutral-500">{when(e.created_at)} · {e.niche}</span>
              {e.kind === "cycle" && e.facts?.n_scored != null && (
                <span className="text-xs text-neutral-500">· {e.facts.n_scored} scored · {e.facts.n_tagged ?? 0} classified · {e.facts.own_posts ?? 0} of ours{e.facts.own_mean_lift != null && <>, mean {times(e.facts.own_mean_lift)}</>}</span>
              )}
            </span>
          }>
            <Markdown text={formatName(e.body)} />
          </Fold>
        ))}
      </div>
      <NextStep from="/learnings" />
    </>
  );
}

const TRAIT_LABEL: Record<string, string> = { hook_type: "hook", visual_style: "style", product_on_screen_by_5s: "product by 5s", pacing_bucket: "pace" };

/** Why the picker proposed this script's format, in the words of its stored evidence. */
function Why({ s }: { s: Script }) {
  const w = s.why;
  return (
    <div className="space-y-2 text-sm text-neutral-300">
      {w ? (
        <ul className="space-y-1">
          {w.pick_share != null && <li>The picker chooses {formatName(s.concept)} {Math.round(w.pick_share * 100)}% of the time{w.kind === "format" ? " (our clone of the product's own best videos, which gets a head start)" : ""}.</li>}
          {w.head_start != null && <li>Head start {w.head_start.toFixed(2)} from early traction{w.expected_lift != null && <>, plus {w.expected_lift >= 0 ? "+" : ""}{w.expected_lift.toFixed(2)} learned ({times(w.expected_lift)} expected against videos like it)</>}.</li>}
          <li>{w.own_n ? <>Our posts in it: {w.own_n}, mean {times(w.own_mean_reward ?? 0)} videos like them.</> : "We have not posted in this format yet, so the learned part comes from its traits."}</li>
          {w.traits?.length ? (
            <li>
              Trait evidence:{" "}
              {w.traits.map((t, i) => (
                <span key={t.trait}>
                  {i > 0 && ", "}
                  {TRAIT_LABEL[t.trait] ?? t.trait} {String(t.value)} ({t.ours_n ? `${times(t.ours)} on ${t.ours_n} of ours` : "none of ours"}{t.market_n ? `, ${times(t.market / 0.25)} on ${t.market_n} panel videos` : ""})
                </span>
              ))}
            </li>
          ) : null}
        </ul>
      ) : (
        <p className="text-neutral-500">Written before the picker stored its reasons; the next batch carries them.</p>
      )}
      <p className="text-xs text-neutral-500">Demo {s.demo_score}/5 is the writer grading whether the product shows within 5 seconds; it gates a script, it does not predict views. <Link href={`/scripts#s${s.id}`} className="hover:underline">Full script</Link></p>
    </div>
  );
}

const cloneShare = (f: CycleFacts) => f.picks?.find((x) => /clone/i.test(x.name))?.share;

function Delta({ label, was, now, fmt }: { label: string; was?: number | null; now?: number | null; fmt: (v: number) => string }) {
  const has = (v?: number | null): v is number => v != null;
  return (
    <div className="rounded-lg border border-neutral-800 px-3 py-2">
      <dt className="text-xs text-neutral-500">{label}</dt>
      <dd className="mt-0.5 text-neutral-100">
        {has(now) ? fmt(now) : "none yet"}
        {has(was) && has(now) && was !== now && <span className={`ml-2 text-xs ${now > was ? "text-emerald-300" : "text-red-300"}`}>was {fmt(was)}</span>}
        {has(was) && has(now) && was === now && <span className="ml-2 text-xs text-neutral-500">unchanged</span>}
        {!has(was) && has(now) && <span className="ml-2 text-xs text-neutral-500">first measurement</span>}
      </dd>
    </div>
  );
}

type Row = RankRow & Record<string, unknown>;

/** One plain paragraph per trait: the values ranked by how many times the views of videos like them
 *  they got, with the video count, values under the minimum set aside as too few, and a change since
 *  the previous cycle only where the previous cycle measured that value and it moved by 0.1 (about 25%). */
function TraitSentences({ latest, prev, minN }: { latest: CycleFacts; prev?: CycleFacts; minN: number }) {
  const blocks = TABLES.flatMap(([key, col, title]) => {
    const rows = ((latest.traits?.[key] as Row[] | undefined) ?? []).slice().sort((a, b) => b.mean_reward - a.mean_reward);
    if (!rows.length) return [];
    const was = new Map(((prev?.traits?.[key] as Row[] | undefined) ?? []).map((r) => [String(r[col]), r]));
    const solid = rows.filter((r) => r.n >= minN), thin = rows.filter((r) => r.n < minN);
    const change = (r: Row) => {
      const w = was.get(String(r[col]));
      if (!w || Math.abs(r.mean_reward - w.mean_reward) < 0.1) return null;
      return <span className={r.mean_reward > w.mean_reward ? "text-emerald-300" : "text-red-300"}> (was {times(w.mean_reward)} last cycle)</span>;
    };
    return [(
      <div key={key} className="text-sm text-neutral-300">
        <span className="text-neutral-500">{title}: </span>
        {solid.length === 0 ? (
          <span>no value has {minN} videos yet.</span>
        ) : (
          <>
            {solid.map((r, i) => (
              <span key={String(r[col])}>
                {i > 0 && (i === solid.length - 1 ? " and " : ", ")}
                <span className={i === 0 && r.mean_reward > 0 ? "font-medium text-neutral-100" : ""}>{traitValue(r[col])}</span>{" "}
                <span className={r.mean_reward >= 0 ? "text-emerald-300" : "text-red-300"}>{times(r.mean_reward)}</span>
                <span className="text-neutral-500"> ({r.n} videos{r.win_rate != null ? `, ${Math.round(r.win_rate * 100)}% beat their match` : ""})</span>
                {change(r)}
              </span>
            ))}
            .
          </>
        )}
        {thin.length > 0 && (
          <span className="text-neutral-500"> Too few to trust yet: {thin.map((r) => `${traitValue(r[col])} ${times(r.mean_reward)} on ${r.n}`).join(", ")}.</span>
        )}
      </div>
    )];
  });
  if (!blocks.length) return <Note className="mt-3">This cycle did not record trait counts; the next Research again will.</Note>;
  return (
    <div className="mt-3 space-y-2">
      {blocks}
      <Note>&quot;1.9x&quot; means those videos got 1.9 times the views of videos of the same age from accounts of the same size. A value needs {minN} videos before it counts as evidence; the step 6 check on <Link href="/how#check" className="text-sky-300 hover:underline">How it decides</Link> also controls for length and posting hour.</Note>
    </div>
  );
}
