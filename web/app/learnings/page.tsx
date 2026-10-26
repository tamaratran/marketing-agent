import Link from "next/link";
import { get, type Campaign, type CycleFacts, type Findings, type Learning, type Render, type Run, type Script } from "@/lib/api";
import { startRenders, startResearch } from "../actions";
import { traitValue, type RankRow } from "../charts";
import { Markdown } from "../md";
import { Card, Fold, H1, NextStep, Note, button, formatName, ghost, times } from "../ui";

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
  const notes = rows.filter((e) => e.kind !== "cycle");
  const latest = cycles[cycles.length - 1]?.facts;
  const prev = cycles[cycles.length - 2]?.facts;
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
          {latest ? <>As of {when(cycles[cycles.length - 1].created_at)}: {latest.n_scored ?? 0} research videos scored against videos of the same age and account size, {latest.n_tagged ?? 0} of them classified by trait. </> : null}
          What wins now is on <Link href="/" className="text-sky-300 hover:underline">Formats</Link>.
        </Note>
        {!latest ? (
          <Note className="mt-3">No cycle entry yet. Research again writes the first one.</Note>
        ) : (
          <>
            <TraitTables latest={latest} prev={prev} minN={minN} />
          </>
        )}
      </Card>


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

      {rows.length === 0 && <Card><Note>Nothing yet. The first run writes the first entry.</Note></Card>}
      {notes.length > 0 && (
        <Card title="Observations" className="mt-4">
          <Note>What a person or session noticed watching the clips and sources, newest first. These are read by the script writer, not by the picker.</Note>
          <div className="mt-3 space-y-2">
            {notes.map((e, i) => (
              <Fold key={e.id} open={i === 0} summary={
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-neutral-100">{e.title}</span>
                  <span className="text-xs text-neutral-500">{when(e.created_at)}</span>
                </span>
              }>
                <Markdown text={formatName(e.body)} />
              </Fold>
            ))}
          </div>
        </Card>
      )}
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

type Row = RankRow & Record<string, unknown>;

/** Lift in words a non-statistician reads at a glance: "+90%" or "-46%" views against videos like it; "3.2x" past +200%. */
const pct = (r: number) => {
  const x = 10 ** r;
  if (x >= 3) return `${x.toFixed(1)}x`;
  const d = Math.round((x - 1) * 100);
  return d === 0 ? "same" : `${d > 0 ? "+" : ""}${d}%`;
};
const tone = (r: number) => (10 ** r >= 1.1 ? "text-emerald-300" : 10 ** r <= 0.9 ? "text-red-300" : "text-neutral-300");

/** One table per trait: each value, its views against videos like it as a percent, how many videos that
 *  rests on, and whether that is enough (min_n) to count. A one-line takeaway sits above each table,
 *  and the best solid value per trait is pulled into a "best bets" line at the top. */
function TraitTables({ latest, prev, minN }: { latest: CycleFacts; prev?: CycleFacts; minN: number }) {
  const traits = TABLES.flatMap(([key, col, title]) => {
    const rows = ((latest.traits?.[key] as Row[] | undefined) ?? []).slice().sort((a, b) => b.mean_reward - a.mean_reward);
    if (!rows.length) return [];
    const was = new Map(((prev?.traits?.[key] as Row[] | undefined) ?? []).map((r) => [String(r[col]), r]));
    const solid = rows.filter((r) => r.n >= minN);
    return [{ key, col, title, rows, solid, was }];
  });
  if (!traits.length) return <Note className="mt-3">This cycle did not record trait counts; the next Research again will.</Note>;
  const bets = traits.filter((t) => t.solid.length && 10 ** t.solid[0].mean_reward >= 1.1).map((t) => `${t.title.replace(/ \(.*\)/, "").toLowerCase()}: ${traitValue(t.solid[0][t.col])} (${pct(t.solid[0].mean_reward)})`);
  return (
    <div className="mt-4 space-y-5">
      {bets.length > 0 && (
        <p className="text-sm text-neutral-200">
          <span className="text-neutral-500">Best bets right now, from values with {minN}+ videos: </span>{bets.join("; ")}.
        </p>
      )}
      {traits.map((t) => {
        const best = t.solid[0], worst = t.solid[t.solid.length - 1];
        const take = !best
          ? `No value has ${minN} videos yet, so nothing to go on.`
          : t.solid.length === 1
            ? `Only "${traitValue(best[t.col])}" has enough videos; it gets ${pct(best.mean_reward)} views against videos like it.`
            : `${traitValue(best[t.col])} does best (${pct(best.mean_reward)} views against videos like it), ${traitValue(worst[t.col])} worst (${pct(worst.mean_reward)}).`;
        return (
          <div key={t.key}>
            <h3 className="text-sm font-medium text-neutral-100">{t.title}</h3>
            <p className="mb-2 mt-0.5 text-sm text-neutral-400">{take}</p>
            <div className="overflow-x-auto">
              <table className="w-full max-w-2xl text-sm">
                <thead>
                  <tr className="text-left text-xs text-neutral-500">
                    <th className="pb-1.5 pr-4 font-medium">Value</th>
                    <th className="pb-1.5 pr-4 font-medium">Views vs videos like it</th>
                    <th className="pb-1.5 pr-4 font-medium">Videos</th>
                    <th className="pb-1.5 font-medium">Enough to count?</th>
                  </tr>
                </thead>
                <tbody>
                  {t.rows.map((r) => {
                    const thin = r.n < minN, w = t.was.get(String(r[t.col]));
                    const moved = w && Math.abs(r.mean_reward - w.mean_reward) >= 0.1 ? w : null;
                    return (
                      <tr key={String(r[t.col])} className={`border-t border-neutral-800/80 ${thin ? "text-neutral-500" : ""}`}>
                        <td className="py-1.5 pr-4">{traitValue(r[t.col])}</td>
                        <td className={`py-1.5 pr-4 tabular-nums ${thin ? "" : tone(r.mean_reward)}`}>
                          {pct(r.mean_reward)}
                          {moved && <span className="text-xs text-neutral-500"> (was {pct(moved.mean_reward)} last cycle)</span>}
                        </td>
                        <td className="py-1.5 pr-4 tabular-nums">{r.n}</td>
                        <td className="py-1.5">{thin ? `no, under ${minN}` : "yes"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
      <Note>&quot;+90%&quot; means those videos got 90% more views than videos of the same age from accounts of the same size. Raw averages; the controlled version is step 6 on <Link href="/how#check" className="text-sky-300 hover:underline">How it decides</Link>.</Note>
    </div>
  );
}
