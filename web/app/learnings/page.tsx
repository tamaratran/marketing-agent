import Link from "next/link";
import { get, type Campaign, type CycleFacts, type Findings, type Learning, type Render, type Run, type Script } from "@/lib/api";
import { startRenders, startResearch } from "../actions";
import { TraitBars, traitValue, type RankRow } from "../charts";
import { Markdown } from "../md";
import { HowItDecides, type HowParams } from "../how";
import { RunsPanel } from "../runs-panel";
import { ScriptCards } from "../script-cards";
import { Card, Fold, H1, Note, button, formatName, ghost, times } from "../ui";

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

export default async function Page({ searchParams }: { searchParams: Promise<HowParams> }) {
  const sp = await searchParams;
  const [rows, scripts, renders, runs, c, fs] = await Promise.all([
    get<Learning[]>("/learnings?limit=100"),
    get<Script[]>("/scripts?days=14&limit=200"), get<Render[]>("/renders"), get<Run[]>("/runs"), get<Campaign>("/campaign"),
    get<Findings>("/findings"),
  ]);
  const minN = fs.min_n ?? 20;
  const newest = scripts.reduce((m, s) => Math.max(m, s.created_at), 0);
  const lift = (s: Script) => s.why?.expected_lift ?? 0;
  const batch = scripts.filter((s) => s.created_at >= newest - 20 * 60).sort((a, b) => lift(b) - lift(a) || b.demo_score - a.demo_score || a.id - b.id);
  const batchFormats = [...new Set(batch.map((s) => s.concept))];
  const rendered = new Set(renders.map((r) => r.script_id));
  const now = nowSec();
  const running = runs.find((r) => !r.finished_at && !r.note?.startsWith("post s") && now - r.created_at < 3 * 3600);
  const cycles = rows.filter((e) => e.kind === "cycle" && e.facts).sort((a, b) => a.created_at - b.created_at);
  const notes = rows.filter((e) => e.kind !== "cycle");
  const latest = cycles[cycles.length - 1]?.facts;
  const prev = cycles[cycles.length - 2]?.facts;
  return (
    <>
      <H1 sub="What the data says, what the agent wrote about it, and what it proposes to make next.">Learnings</H1>

      <Card title="What the data says" className="mt-0">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <Note>
            {latest ? <>As of {when(cycles[cycles.length - 1].created_at)}: {latest.n_scored ?? 0} videos scored against videos of the same age and account size, {latest.n_tagged ?? 0} classified by trait. Values under {minN} videos are faded.</> : "No cycle entry yet. Research again writes the first one."}
          </Note>
          <form action={startResearch} className="flex items-baseline gap-3">
            <button className={ghost} disabled={!!running}>Research again</button>
            <span className="text-xs text-neutral-600">{running ? <>a run is going, <Link href="#runs" className="text-gold hover:underline">see runs</Link></> : "about 15 minutes, no fal cost"}</span>
          </form>
        </div>
        {latest && <TraitPanel latest={latest} prev={prev} minN={minN} />}
      </Card>


      <Card title="Proposed next scripts">
        {batch.length === 0 ? <Note>No scripts yet. Research again writes the first batch.</Note> : (
          <>
            <Note>
              {batch.length} scripts across {batchFormats.length} format{batchFormats.length === 1 ? "" : "s"}, written {when(newest)}, ranked by expected lift.
            </Note>
            <ol className="mt-4">
              {batch.map((s, i) => (
                <li key={s.id}>
                  <Fold summary={
                    <span className="grid grid-cols-[1.5rem_minmax(0,1fr)_4.5rem] items-baseline gap-x-3 sm:grid-cols-[2rem_minmax(0,1fr)_10rem_5rem_5rem]">
                      <span className="text-xs tabular-nums text-neutral-600">{i + 1}</span>
                      <span className="text-base font-medium leading-snug text-neutral-50">{s.hook}</span>
                      <span className="hidden truncate text-xs text-neutral-500 sm:block">{formatName(s.concept)}</span>
                      <span className="text-right text-xs tabular-nums sm:text-left">{s.why?.expected_lift != null ? <span className={s.why.expected_lift >= 0 ? "text-neutral-50" : "text-neutral-400"}>{times(s.why.expected_lift)}</span> : <span className="text-neutral-600">–</span>}</span>
                      <span className="hidden text-xs text-neutral-500 sm:block">{rendered.has(s.id) ? <Link href="/clips" className="text-gold hover:underline">clip ready</Link> : `s${s.id}`}</span>
                    </span>
                  }>
                    <Why s={s} />
                  </Fold>
                </li>
              ))}
            </ol>
            <form action={startRenders} className="mt-6 flex flex-wrap items-center gap-3">
              <button className={button} disabled={!!running}>Generate clips</button>
              <Note>{c.cycle.clips} clips at {c.cycle.resolution}, about ${(c.cycle.clips * (c.cycle.resolution === "1080p" ? 9.6 : c.cycle.resolution === "480p" ? 2.65 : 5.68)).toFixed(0)} on fal. Each finished clip is posted to our account and tracked on Our posts; held clips are not posted.</Note>
            </form>
          </>
        )}
      </Card>

      <div className="mt-14">
        <Fold summary={<span className="text-sm font-medium text-neutral-200">All scripts, last 14 days</span>}>
          <div className="pt-2"><ScriptCards rows={scripts} rendered={rendered} /></div>
        </Fold>
        <Fold summary={<span className="text-sm font-medium text-neutral-200">How the writer is briefed, and whether a pattern is real</span>}>
          <div className="pt-2"><HowItDecides part="learnings" sp={sp} /></div>
        </Fold>
        <div id="runs" className="scroll-mt-4">
          <Fold summary={<span className="text-sm font-medium text-neutral-200">Runs, the full cycle and what it works on</span>}>
            <div className="pt-2"><RunsPanel rows={runs} c={c} /></div>
          </Fold>
        </div>
      </div>

      {rows.length === 0 && <Card><Note>Nothing yet. The first run writes the first entry.</Note></Card>}
      {notes.length > 0 && (
        <Card title="Observations">
          <Note>What a person or session noticed watching the clips and sources, newest first. Read by the script writer, not the picker.</Note>
          <div className="mt-4">
            {notes.map((e, i) => (
              <Fold key={e.id} open={i === 0} summary={
                <span className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-baseline gap-x-4">
                  <span className="text-xs tabular-nums text-neutral-500">{new Date(e.created_at * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
                  <span className="font-medium text-neutral-100">{e.title}</span>
                </span>
              }>
                <div className="sm:pl-[6.5rem]"><Markdown text={formatName(e.body)} /></div>
              </Fold>
            ))}
          </div>
        </Card>
      )}
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

type Row = RankRow & Record<string, unknown>;

/** Lift in words a non-statistician reads at a glance: "+90%" or "-46%" views against videos like it; "3.2x" past +200%. */
const pct = (r: number) => {
  const x = 10 ** r;
  if (x >= 3) return `${x.toFixed(1)}x`;
  const d = Math.round((x - 1) * 100);
  return d === 0 ? "same" : `${d > 0 ? "+" : ""}${d}%`;
};

/** One panel: every trait as bars (log lift, bar fades with thin evidence), values under minN
 *  listed faded, and a one-line "moved since last cycle" note where a value shifted by 0.1 or more. */
function TraitPanel({ latest, prev, minN }: { latest: CycleFacts; prev?: CycleFacts; minN: number }) {
  const traits = TABLES.flatMap(([key, col, title]) => {
    const rows = ((latest.traits?.[key] as Row[] | undefined) ?? []).slice().sort((a, b) => b.mean_reward - a.mean_reward);
    if (!rows.length) return [];
    const was = new Map(((prev?.traits?.[key] as Row[] | undefined) ?? []).map((r) => [String(r[col]), r]));
    const moved = rows.filter((r) => r.n >= minN).map((r) => ({ r, w: was.get(String(r[col])) })).filter((x) => x.w && Math.abs(x.r.mean_reward - x.w.mean_reward) >= 0.1);
    return [{ key, col, title, rows, moved }];
  });
  if (!traits.length) return <Note className="mt-3">This cycle did not record trait counts; the next Research again will.</Note>;
  return (
    <div className="mt-6 grid gap-8 sm:grid-cols-2">
      {traits.map((t) => (
        <div key={t.key}>
          <TraitBars rows={t.rows.filter((r) => r.n >= minN)} column={t.col} title={t.title} max={6} />
          {t.rows.some((r) => r.n < minN) && (
            <p className="mt-2 text-xs text-neutral-600">under {minN} videos: {t.rows.filter((r) => r.n < minN).map((r) => `${traitValue(r[t.col])} ${pct(r.mean_reward)} (${r.n})`).join(", ")}</p>
          )}
          {t.moved.map(({ r, w }) => (
            <p key={String(r[t.col])} className="mt-1 text-xs text-neutral-400">{traitValue(r[t.col])} moved from {pct(w!.mean_reward)} to {pct(r.mean_reward)} since last cycle.</p>
          ))}
        </div>
      ))}
    </div>
  );
}
