import Link from "next/link";
import { get, type Concept, type TraitDetail, type Findings, type Logic, type Overview, type Render, type Script } from "@/lib/api";
import type { Ours } from "@/lib/ours";
import { H1, Note, formatName, times } from "../ui";

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
    c, mean: c.prior + (c.learned ?? c.mean_reward ?? 0), sd: lg.explore_sd / Math.sqrt(1 + c.n),
  }));
  const chances = pickChances(formats);
  const ranked = formats.map((f, i) => ({ ...f, p: chances[i] })).sort((a, b) => b.p - a.p);
  const leader = ranked[0];
  const withRecord = scored.filter((v) => v.creator_offset !== 0).length;
  const curve = lg.curve;
  const typical = (h: number, followers: number) => curve ? Math.round(10 ** (curve.a + curve.b * Math.log10(h) + curve.c * Math.log10(followers + 1))) : null;
  const big = scored.filter((v) => (v.reward as number) >= 1).length;
  const research = ranked.find((r) => r.c.kind !== "format");
  const whatIf = (target: typeof ranked[number] | undefined, lift: number) => {
    if (!target) return null;
    const K = lg.shrink_k ?? 0;
    const next = formats.map((f) => f.c.id === target.c.id
      ? { ...f, mean: f.c.prior + (K * (f.c.trait_bonus ?? 0) + (f.c.mean_reward ?? 0) * f.c.n + lift) / (K + f.c.n + 1), sd: lg.explore_sd / Math.sqrt(2 + f.c.n) }
      : f);
    const i = formats.findIndex((f) => f.c.id === target.c.id);
    return { name: formatName(target.c.name), before: target.p, after: pickChances(next)[i], lift };
  };
  const scenarios = [whatIf(leader, 1), whatIf(leader, -1), whatIf(research, 1)].filter((x) => x != null);

  return (
    <div className="mx-auto max-w-3xl space-y-12">
      <H1 sub="The actual rules the agent follows to decide what the next video looks like, drawn from live data.">How it decides</H1>

      <Section n={1} title="The loop">
        <Loop steps={[
          ["Research", `${lg.videos.length} videos from other accounts`],
          ["Score", `${beat} of ${scored.length} ahead of videos like them`],
          ["Formats", `${concepts.length} found`],
          ["Pick", leader ? formatName(leader.c.name) : "none yet"],
          ["Script + clip", `${scripts.length} scripts, ${new Set(renders.map((r) => r.script_id)).size} clips`],
          ["You post", `${linked.length} post${linked.length === 1 ? "" : "s"} linked so far`],
        ]} />
        <Note className="mt-3">How our posts do feeds back into the pick. Views on research videos are rechecked every 2 hours.</Note>
      </Section>

      <Section n={2} title="Score: did a video beat videos like it?">
        <p className="text-sm text-neutral-300">
          Raw views mislead twice over: 50k is huge for a new account and a flop for a big one, and a video that is 3 hours old has
          had no time to collect views. So every video is compared with what a video of the same age from an account of the same size
          typically has in this niche right now. That &quot;typical&quot; is a curve fitted on the {curve?.n ?? scored.length} research videos
          we have view counts for{curve ? <>: for example {typical(6, 300)?.toLocaleString()} views at 6 hours from a 300-follower account, {typical(72, 300)?.toLocaleString()} at 3 days,
          and {typical(72, 100_000)?.toLocaleString()} at 3 days from a 100k-follower account</> : ""}.
          When we have 3 or more videos from the same creator, their own track record against that curve is added, so the bar is the creator&apos;s usual, age-matched.
          Each square is one video. Right of the dashed line did better than videos like it, left did worse.
        </p>
        <p className="mt-2 text-sm text-neutral-300">
          Views alone are mostly luck with the For You feed. Shares and saves per 1k views say whether people kept what they saw, so a video&apos;s
          final score is its view score plus {lg.engagement_weight != null ? `${Math.round(lg.engagement_weight * 100)}%` : "half"} of how its shares+saves rate compares with the niche median (log10).
          Both are shown separately on Our posts.
        </p>
        <Histogram videos={scored} />
        <Note className="mt-2">
          {big} of {scored.length} did 10x or more. {withRecord} have a creator track record folded in; the rest are judged on age and account size alone.
          {lg.videos.length - scored.length > 0 && ` ${lg.videos.length - scored.length} more are under ${lg.min_age_h}h old and not judged yet.`}
          {" "}The top {Math.round((1 - lg.winsor_pct) * 100)}% of view counts are capped so one viral hit can&apos;t swamp the rest.
        </Note>
      </Section>

      <Section n={3} title="Pick: which format the next scripts use">
        <p className="text-sm text-neutral-300">
          GPT groups videos under 72 hours old into {concepts.filter((c) => c.kind !== "format").length} reusable formats. Each gets an early traction score:
          views per hour, discounted for big accounts, boosted while the video is under 2 days old. One more format,
          the clone, is built from the product&apos;s own best TikToks.
        </p>
        <p className="mt-2 text-sm text-neutral-300">
          Early traction sets each format&apos;s head start, then what we have learned about its traits moves it (the dot, see step 4).
          A bit of random noise is added (the line shows its usual range) and the highest score wins. The noise is what lets a weaker format win now and then, so the
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

      <Section n={4} title="Learn: how our posts change the pick">
        <p className="text-sm text-neutral-300">
          Once a post from {account ? `@${account}` : "our account"} is matched to its script, its result moves the pick two ways.
          Its own format&apos;s score moves directly: a post that does 10x what videos like it (same age, same account size, this niche) have adds 1, one that does a tenth takes 1 away.
          And every format sharing its traits moves a little: each format is a bundle of a hook type, a visual style, whether the product is on screen in the first 5 seconds, and a pace,
          and each of those earns its own running score from our posts, averaged over the four (what the niche&apos;s videos show counts {lg.market_trait_weight != null ? `${Math.round(lg.market_trait_weight * 100)}%` : "a quarter"} as much).
          So a format we have never posted still inherits what similar ones taught us, and a format that comes back under a new name after the next research run keeps its lessons.
        </p>
        <p className="mt-2 text-sm text-neutral-300">
          A format&apos;s own posts take over from the trait guess as they accumulate: with {lg.shrink_k ?? 2} posts the two count equally, after that its own results dominate.
          The more posts a format has, the less noise it gets, so proven formats settle and untested ones still get tries.
        </p>
        <TraitTable concepts={concepts} />
        <WhatIf rows={scenarios} />
        <Note className="mt-3">
          Worked out on today&apos;s numbers. A post under {lg.min_age_h_own ?? 6} hours old does not count at all; after that it counts partly (a 6 hour old result counts about 30%, 3 days counts fully), so early posts nudge the pick without deciding it.
          {linked.length ? ` ${linked.length} post${linked.length === 1 ? " is" : "s are"} linked so far.` : " No posts are linked yet, so every pick so far comes from research alone."}
        </Note>
      </Section>

      <Section n={5} title="Write: what the script writer is told">
        <p className="text-sm text-neutral-300">
          Along with the format, GPT gets this summary of what has worked, word for word. Our own posts come first,
          then research patterns, then places where the two disagree.
        </p>
        <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-neutral-800 bg-neutral-900/60 p-3 text-xs leading-relaxed text-neutral-400">{o.winning || "Nothing scored yet, so the writer only gets the format."}</pre>
      </Section>

      <Section n={6} title="Check: is a pattern real or luck?">
        <p className="text-sm text-neutral-300">
          The summary above is raw averages, which mix up the trait with account size, video length and posting time.
          A separate analysis follows fresh videos in this niche and compares like with like, using the same &quot;videos like it&quot; score as step 2,
          once at least {fs.min_n ?? 20} of them are a day old and scored. Views are only checked when a cycle runs, so this fills in with cycles, not with time.
        </p>
        <Progress done={fs.status.reached["scored"] ?? 0} need={fs.min_n ?? 20} tracked={fs.status.videos} />
        <Note className="mt-2">
          {fs.collecting
            ? "Still collecting. Until then the writer gets the raw version."
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
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-4 w-full" role="img" aria-label="How each video did against videos of the same age and account size">
      {cols.map((c, i) => c.map((v, j) => (
        <rect key={v.id} x={i * cw + 1} y={H - 28 - (j + 1) * cell} width={cw - 2} height={cell - 1} rx={1}
          fill={(v.reward as number) > 0 ? "#34d399" : "#f87171"} fillOpacity={0.9}>
          <title>{`@${v.author}: ${(v.views ?? 0).toLocaleString()} views, ${times(v.reward as number)} videos like it (typical ${Math.round(10 ** v.baseline).toLocaleString()})${v.creator_offset ? ", creator track record included" : ""}`}</title>
        </rect>
      )))}
      <line x1={x(0)} x2={x(0)} y1={0} y2={H - 24} stroke="#a3a3a3" strokeDasharray="4 3" />
      {(["1/1000", "1/100", "1/10", "1x", "10x", "100x", "1000x"] as const).map((t, i) => (
        <text key={t} x={Math.min(W - 16, Math.max(16, x(i - 3)))} y={H - 12} fontSize={10} fill="#737373" textAnchor="middle">{t}</text>
      ))}
      <text x={W / 2} y={H} fontSize={11} fill="#a3a3a3" textAnchor="middle">views vs videos like it</text>
    </svg>
  );
}

function TraitTable({ concepts }: { concepts: Concept[] }) {
  const rows = concepts.filter((c) => c.trait_detail && c.trait_detail.length).map((c) => ({ c, d: c.trait_detail as TraitDetail[] }));
  if (!rows.length) return <Note className="mt-3">No format has classified member videos yet, so there are no traits to learn on.</Note>;
  const label = (d: TraitDetail) => d.trait === "product_on_screen_by_5s" ? (d.value ? "product by 5s" : "no product by 5s") : `${String(d.value).replace(/_/g, " ")}${d.trait === "pacing_bucket" ? " pace" : ""}`;
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-neutral-500">
          <tr><th className="py-1 text-left font-normal">format</th><th className="py-1 text-left font-normal">traits</th><th className="py-1 text-right font-normal">from our posts</th><th className="py-1 text-right font-normal">from the niche</th><th className="py-1 text-right font-normal">head start moves by</th></tr>
        </thead>
        <tbody>
          {rows.map(({ c, d }) => (
            <tr key={c.id} className="border-t border-neutral-800 align-top">
              <td className="py-1.5 pr-3 text-neutral-200">{formatName(c.name)}</td>
              <td className="py-1.5 pr-3 text-neutral-400">{d.map(label).join(" · ")}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{(d.reduce((a, x) => a + x.ours, 0) / d.length).toFixed(2)} <span className="text-neutral-600">({Math.max(...d.map((x) => x.ours_n))} post{Math.max(...d.map((x) => x.ours_n)) === 1 ? "" : "s"})</span></td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{(d.reduce((a, x) => a + x.market, 0) / d.length).toFixed(2)} <span className="text-neutral-600">({Math.max(...d.map((x) => x.market_n))} videos)</span></td>
              <td className={`py-1.5 text-right tabular-nums ${(c.trait_bonus ?? 0) > 0 ? "text-emerald-300" : (c.trait_bonus ?? 0) < 0 ? "text-red-300" : "text-neutral-500"}`}>{(c.trait_bonus ?? 0) > 0 ? "+" : ""}{(c.trait_bonus ?? 0).toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
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

function WhatIf({ rows }: { rows: { name: string; before: number; after: number; lift: number }[] }) {
  return (
    <div className="mt-4 space-y-3">
      {rows.map((r) => (
        <div key={`${r.name}${r.lift}`} className="text-xs">
          <div className="mb-1 text-neutral-300">If one {r.name} post does {r.lift > 0 ? "10x" : "a tenth of"} what videos like it get, its chance of being picked goes</div>
          <div className="grid grid-cols-[3rem_1fr] items-center gap-x-3 gap-y-1">
            <span className="text-right tabular-nums text-neutral-500">{pct(r.before)}</span>
            <div className="h-2 rounded bg-neutral-800"><div className="h-2 rounded bg-neutral-500" style={{ width: `${r.before * 100}%` }} /></div>
            <span className={`text-right tabular-nums ${r.after > r.before ? "text-emerald-300" : "text-red-300"}`}>{pct(r.after)}</span>
            <div className="h-2 rounded bg-neutral-800"><div className={`h-2 rounded ${r.after > r.before ? "bg-emerald-400/80" : "bg-red-400/80"}`} style={{ width: `${r.after * 100}%` }} /></div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Progress({ done, need, tracked }: { done: number; need: number; tracked: number }) {
  return (
    <div className="mt-4 grid grid-cols-[1fr_7rem] items-center gap-3 text-xs">
      <div className="h-2 rounded bg-neutral-800"><div className="h-2 rounded bg-sky-400/70" style={{ width: `${Math.min(1, done / need) * 100}%` }} /></div>
      <span className="text-right tabular-nums text-neutral-400">{done} of {need} needed</span>
      <Note className="col-span-2">Videos at least 3 days old, out of {tracked} being followed.</Note>
    </div>
  );
}
