import Link from "next/link";
import { get, type Concept, type Findings, type Logic, type Overview, type Render, type Script } from "@/lib/api";
import type { Ours } from "@/lib/ours";
import { H1, Note, formatName, pt, times } from "../ui";

export const dynamic = "force-dynamic";

/** Normal CDF via the Abramowitz-Stegun erf approximation (error < 1.5e-7). */
function cdf(x: number) {
  const z = Math.abs(x) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * z);
  const erf = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z);
  return x >= 0 ? (1 + erf) / 2 : (1 - erf) / 2;
}

/** Chance each format wins the picker's draw: P(its noisy score is the highest), integrated numerically. */
function pickChances(rows: { mean: number; sd: number }[]) {
  const lo = Math.min(...rows.map((r) => r.mean - 6 * r.sd));
  const hi = Math.max(...rows.map((r) => r.mean + 6 * r.sd));
  const dx = (hi - lo) / 4000;
  return rows.map((r, i) => {
    let p = 0;
    for (let x = lo; x <= hi; x += dx) {
      const pdf = Math.exp(-(((x - r.mean) / r.sd) ** 2) / 2) / (r.sd * Math.sqrt(2 * Math.PI));
      let others = 1;
      rows.forEach((o, j) => { if (j !== i) others *= cdf((x - o.mean) / o.sd); });
      p += pdf * others * dx;
    }
    return p;
  });
}

const pct = (p: number) => (p >= 0.995 ? ">99%" : p < 0.005 ? "<1%" : `${Math.round(p * 100)}%`);

export default async function How() {
  const [lg, concepts, ours, fs, o, scripts, renders] = await Promise.all([
    get<Logic>("/logic"), get<Concept[]>("/concepts"), get<Ours>("/ours"), get<Findings>("/findings"),
    get<Overview>("/overview"), get<Script[]>("/scripts?days=60&limit=500"), get<Render[]>("/renders"),
  ]);
  const account = ours.accounts[0]?.handle;
  const linked = ours.posts.filter((p) => p.script_id);
  const scored = lg.videos.filter((v) => v.reward != null);
  const beat = scored.filter((v) => (v.reward as number) > 0).length;

  const formats = concepts.map((c) => ({
    c, mean: c.prior + (c.mean_reward ?? 0), sd: lg.explore_sd / Math.sqrt(1 + c.n),
  }));
  const chances = pickChances(formats);
  const ranked = formats.map((f, i) => ({ ...f, p: chances[i] })).sort((a, b) => b.p - a.p);
  const leader = ranked[0];

  return (
    <div className="mx-auto max-w-3xl space-y-12">
      <H1 sub="The actual rules the agent follows to decide what the next video looks like, drawn from live data.">How it decides</H1>

      <Section n={1} title="The loop">
        <Loop steps={[
          ["Research", `${lg.videos.length} videos from other accounts`],
          ["Score", `${beat} of ${scored.length} beat their usual`],
          ["Formats", `${concepts.length} found`],
          ["Pick", leader ? formatName(leader.c.name) : "none yet"],
          ["Script + clip", `${scripts.length} scripts, ${new Set(renders.map((r) => r.script_id)).size} clips`],
          ["You post", `${linked.length} posts linked so far`],
        ]} />
        <Note className="mt-3">How our posts do feeds back into the pick. Views on research videos are rechecked every 2 hours.</Note>
      </Section>

      <Section n={2} title="Score: did a video beat its creator's usual?">
        <p className="text-sm text-neutral-300">
          Raw views mislead: 50k views is huge for a new account and a flop for a big one. So every video is compared with
          its own creator&apos;s usual (the middle of their videos we&apos;ve seen). Each square is one video: right of the line beat their usual, left fell short.
        </p>
        <Histogram videos={scored} />
        <Note className="mt-2">
          {beat} of {scored.length} scored videos beat their creator&apos;s usual; {lg.videos.length - scored.length} more are under {lg.min_age_h}h old and not judged yet.
          Creators with fewer than 3 videos in our data are compared with the niche&apos;s middle instead.
          The top {Math.round((1 - lg.winsor_pct) * 100)}% of view counts are capped so one viral hit can&apos;t swamp the rest.
        </Note>
      </Section>

      <Section n={3} title="Formats: what to copy">
        <p className="text-sm text-neutral-300">
          GPT groups videos under 72 hours old into {concepts.filter((c) => c.kind !== "format").length} reusable formats. Each gets an early traction score:
          views per hour, discounted for big accounts, boosted while the video is under 2 days old. One more format,
          the clone, is built from the product&apos;s own best TikToks.
        </p>
        <Traction rows={concepts.filter((c) => c.kind !== "format")} />
      </Section>

      <Section n={4} title="Pick: which format the next scripts use">
        <p className="text-sm text-neutral-300">
          Each format gets a head start from its early traction (the dot). A bit of random noise is added (the line shows
          its usual range) and the highest score wins. The noise is what lets a weaker format win now and then, so the
          agent keeps testing instead of copying the leader forever.
          {lg.format_edge != null && (
            <> The clone starts {lg.format_edge} above the best research format: it is the safest bet, so it wins most picks, but the rest still get tested.</>
          )}
        </p>
        <PickChart rows={ranked} />
        {leader && leader.p > 0.95 && (
          <div className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/30 p-3 text-sm text-amber-200">
            Right now {formatName(leader.c.name)} wins {pct(leader.p)} of picks. Its head start of {lg.format_prior} is far
            ahead of the rest, so the other formats effectively never get tested.
          </div>
        )}
      </Section>

      <Section n={5} title="Learn: how our posts change the pick">
        <p className="text-sm text-neutral-300">
          Once a post from {account ? `@${account}` : "our account"} is matched to its script, its result is added to that
          format&apos;s head start: a post that does 10x the account&apos;s usual adds 1, one that does a tenth takes 1 away.
          The more posts a format has, the less noise it gets, so proven formats settle and untested ones still get tries.
        </p>
        <div className="mt-4 grid gap-6 sm:grid-cols-2">
          <div>
            <div className="mb-2 text-xs text-neutral-500">Noise range vs posts in that format</div>
            <NoiseBars sd={lg.explore_sd} />
          </div>
          <div>
            <div className="mb-2 text-xs text-neutral-500">How much a post counts vs its age</div>
            <AgeCurve />
          </div>
        </div>
        <Note className="mt-3">
          The 3-day result counts fully. Before that, a post&apos;s current result counts partially so early posts nudge the pick without deciding it.
          {linked.length ? ` ${linked.length} posts are linked so far.` : " No posts are linked yet, so every pick so far comes from research alone."}
        </Note>
      </Section>

      <Section n={6} title="Write: what the script writer is told">
        <p className="text-sm text-neutral-300">
          Along with the format, GPT gets this summary of what has worked, word for word. Our own posts come first,
          then research patterns, then places where the two disagree.
        </p>
        <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-neutral-800 bg-neutral-900/60 p-3 text-xs leading-relaxed text-neutral-400">{o.winning || "Nothing scored yet, so the writer only gets the format."}</pre>
      </Section>

      <Section n={7} title="Check: is a pattern real or luck?">
        <p className="text-sm text-neutral-300">
          The summary above is raw averages, which mix up the trait with account size, video length and posting time.
          A separate analysis tracks fresh videos and compares like with like, but only once at least {fs.min_n ?? 20} of
          them are 3 days old.
        </p>
        <Progress reached={fs.status.reached} total={fs.status.videos} need={fs.min_n ?? 20} />
        <Note className="mt-2">
          {fs.collecting
            ? `Still collecting${fs.status.eta_72h ? `; the first videos turn 3 days old ${pt(fs.status.eta_72h)}` : ""}. Until then the writer gets the raw version.`
            : <>Ready. See <Link href="/findings" className="text-sky-300 hover:underline">Findings</Link>.</>}
        </Note>
      </Section>
    </div>
  );
}

function Section({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-3 flex items-baseline gap-2">
        <span className="text-xs tabular-nums text-neutral-500">{n}</span>
        <h2 className="text-base font-semibold">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Loop({ steps }: { steps: [string, string][] }) {
  return (
    <ol className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {steps.map(([t, d], i) => (
        <li key={t} className="rounded-lg border border-neutral-800 bg-neutral-900/60 p-3">
          <div className="text-[11px] text-neutral-500">{i + 1}{i === steps.length - 1 ? " → back to 4" : " →"}</div>
          <div className="text-sm font-medium">{t}</div>
          <div className="mt-0.5 text-xs text-neutral-400">{d}</div>
        </li>
      ))}
    </ol>
  );
}

function Histogram({ videos }: { videos: Logic["videos"] }) {
  const step = 0.25, lo = -3, hi = 3;
  const bins = Array.from({ length: (hi - lo) / step }, (_, i) => lo + i * step);
  const at = (r: number) => Math.min(bins.length - 1, Math.max(0, Math.floor((r - lo) / step)));
  const cols = bins.map(() => [] as Logic["videos"]);
  videos.forEach((v) => cols[at(v.reward as number)].push(v));
  const tall = Math.max(...cols.map((c) => c.length), 1);
  const W = 600, cell = Math.min(10, 150 / tall), H = tall * cell + 40, cw = W / bins.length;
  const x = (r: number) => ((r - lo) / (hi - lo)) * W;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-4 w-full" role="img" aria-label="How each video did against its creator's usual views">
      {cols.map((c, i) => c.map((v, j) => (
        <rect key={v.id} x={i * cw + 1} y={H - 28 - (j + 1) * cell} width={cw - 2} height={cell - 1} rx={1}
          fill={(v.reward as number) > 0 ? "#34d399" : "#f87171"} fillOpacity={0.8}>
          <title>{`@${v.author}: ${(v.views ?? 0).toLocaleString()} views, ${times(v.reward as number)} usual`}</title>
        </rect>
      )))}
      <line x1={x(0)} x2={x(0)} y1={0} y2={H - 24} stroke="#a3a3a3" strokeDasharray="4 3" />
      {(["1/1000", "1/100", "1/10", "1x", "10x", "100x", "1000x"] as const).map((t, i) => (
        <text key={t} x={Math.min(W - 16, Math.max(16, x(i - 3)))} y={H - 12} fontSize={10} fill="#737373" textAnchor="middle">{t}</text>
      ))}
      <text x={W / 2} y={H} fontSize={11} fill="#a3a3a3" textAnchor="middle">views vs creator&apos;s usual</text>
    </svg>
  );
}

function Traction({ rows }: { rows: Concept[] }) {
  const sorted = [...rows].sort((a, b) => b.early_score - a.early_score);
  const max = Math.log10(Math.max(...sorted.map((c) => c.early_score), 10) + 1);
  return (
    <div className="mt-4 space-y-1.5">
      {sorted.map((c) => (
        <div key={c.id} className="grid grid-cols-[minmax(0,10rem)_1fr_3.5rem] items-center gap-3 text-xs">
          <span className="truncate text-neutral-300" title={c.name}>{formatName(c.name)}</span>
          <div className="h-2 rounded bg-neutral-800"><div className="h-2 rounded bg-sky-400/70" style={{ width: `${(Math.log10(c.early_score + 1) / max) * 100}%` }} /></div>
          <span className="text-right tabular-nums text-neutral-400">{Math.round(c.early_score).toLocaleString()}</span>
        </div>
      ))}
      <Note>Early traction per format (log scale). It becomes the head start in the next step.</Note>
    </div>
  );
}

function PickChart({ rows }: { rows: { c: Concept; mean: number; sd: number; p: number }[] }) {
  const lo = Math.min(0, ...rows.map((r) => r.mean - 2 * r.sd));
  const hi = Math.max(...rows.map((r) => r.mean + 2 * r.sd));
  const at = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="mt-4 space-y-2">
      <div className="grid grid-cols-[minmax(0,10rem)_1fr_3rem] gap-3 text-[11px] text-neutral-500">
        <span>format</span><span>head start and noise range</span><span className="text-right">picked</span>
      </div>
      {rows.map((r) => (
        <div key={r.c.id} className="grid grid-cols-[minmax(0,10rem)_1fr_3rem] items-center gap-3">
          <span className="truncate text-xs text-neutral-300" title={r.c.name}>{formatName(r.c.name)}</span>
          <div className="relative h-4">
            <div className="absolute inset-y-1/2 left-0 right-0 h-px bg-neutral-800" />
            <div className="absolute top-1/2 h-1 -translate-y-1/2 rounded bg-sky-400/40" style={{ left: at(r.mean - 2 * r.sd), width: `calc(${at(r.mean + 2 * r.sd)} - ${at(r.mean - 2 * r.sd)})` }} />
            <div className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-sky-300" style={{ left: at(r.mean) }} title={`head start ${r.mean.toFixed(2)}`} />
          </div>
          <span className={`text-right text-xs tabular-nums ${r.p > 0.5 ? "text-neutral-100" : "text-neutral-500"}`}>{pct(r.p)}</span>
        </div>
      ))}
      <Note>Chance of being picked is calculated exactly from the head starts and noise, not from past picks.</Note>
    </div>
  );
}

function NoiseBars({ sd }: { sd: number }) {
  const ns = Array.from({ length: 10 }, (_, n) => n);
  return (
    <div className="flex h-24 items-end gap-1.5">
      {ns.map((n) => (
        <div key={n} className="flex flex-1 flex-col items-center gap-1">
          <div className="w-full rounded-t bg-sky-400/60" style={{ height: `${(1 / Math.sqrt(1 + n)) * 72}px` }} title={`±${(2 * sd / Math.sqrt(1 + n)).toFixed(2)}`} />
          <span className="text-[10px] text-neutral-500">{n}</span>
        </div>
      ))}
    </div>
  );
}

function AgeCurve() {
  const W = 240, H = 96, pts = Array.from({ length: 73 }, (_, h) => [h, Math.min(1, Math.sqrt(h / 72))]);
  const d = pts.map(([h, w], i) => `${i ? "L" : "M"}${(h / 72) * (W - 20) + 10},${H - 16 - w * (H - 26)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-xs" role="img" aria-label="Weight vs post age">
      <path d={d} fill="none" stroke="#38bdf8" strokeWidth={2} />
      {[1, 6, 24, 72].map((h) => {
        const w = Math.min(1, Math.sqrt(h / 72));
        return (
          <circle key={h} cx={(h / 72) * (W - 20) + 10} cy={H - 16 - w * (H - 26)} r={3} fill="#38bdf8">
            <title>{`A ${h}h old post counts ${Math.round(w * 100)}% as much as a 3 day result`}</title>
          </circle>
        );
      })}
      {[0, 6, 24, 72].map((h) => (
        <text key={h} x={(h / 72) * (W - 20) + 10} y={H - 2} fontSize={10} fill="#737373" textAnchor="middle">{h}h</text>
      ))}
      <text x={W - 10} y={14} fontSize={10} fill="#737373" textAnchor="end">full</text>
    </svg>
  );
}

function Progress({ reached, total, need }: { reached: Record<string, number>; total: number; need: number }) {
  const marks: [string, string][] = [["1h", "1 hour"], ["6h", "6 hours"], ["24h", "1 day"], ["72h", "3 days"]];
  return (
    <div className="mt-4 space-y-2">
      {marks.map(([k, label]) => {
        const n = reached[k] ?? 0;
        return (
          <div key={k} className="grid grid-cols-[4rem_1fr_4rem] items-center gap-3 text-xs">
            <span className="text-neutral-400">{label}</span>
            <div className="relative h-2 rounded bg-neutral-800">
              <div className="h-2 rounded bg-sky-400/70" style={{ width: `${total ? (n / total) * 100 : 0}%` }} />
              {k === "72h" && total > 0 && <div className="absolute -top-1 h-4 w-px bg-amber-300" style={{ left: `${Math.min(1, need / total) * 100}%` }} title={`needs ${need}`} />}
            </div>
            <span className="text-right tabular-nums text-neutral-400">{n} of {total}</span>
          </div>
        );
      })}
      <Note>How many tracked videos have a view count taken at each age. We only get one if we were already watching the video then, so most videos found after their first hour have no 1 hour count. The yellow mark is the {need} needed at 3 days.</Note>
    </div>
  );
}
