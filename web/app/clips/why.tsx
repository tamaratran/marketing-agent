import type { Overview, VideoDetail } from "@/lib/api";
import type { OursPost } from "@/lib/ours";
import { traitValue } from "../charts";
import { Fold, Pill, times } from "../ui";

// Mirrors scoreboard.MIN_AGE_H_FOR_OWN: younger posts are not judged.
export const MIN_AGE_H_OWN = 6;
// log10 lift beyond which a post counts as a clear win or a clear miss (about 2x either way).
const CLEAR = 0.3;

type Tone = "good" | "bad" | "neutral";
type Line = { tone: Tone; text: string; detail?: string };

const TRAITS: { key: string; table: "hooks" | "styles" | "pacing" | "sound" | "product_early"; label: string }[] = [
  { key: "hook_type", table: "hooks", label: "hook" },
  { key: "visual_style", table: "styles", label: "look" },
  { key: "pacing_bucket", table: "pacing", label: "pace" },
  { key: "music_role", table: "sound", label: "sound" },
  { key: "product_on_screen_by_5s", table: "product_early", label: "product by 5s" },
];

const n = (x: number) => Math.round(x).toLocaleString("en-US");
const hours = (h: number) => (h < 48 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`);

export type Why = { verdict: "early" | "unscored" | "win" | "average" | "miss"; headline: string; reason: string; lines: Line[] };

/** Everything measured about one of our posts, read into a verdict and the facts behind it. No model writes this. */
export function explain(p: OursPost, v: VideoDetail | null, o: Overview): Why {
  const lines: Line[] = [];
  const minN = o.trait_min_n ?? 5;
  const own: Record<string, unknown> = { ...(v?.tags?.tags ?? {}), ...(v?.features ?? {}) };

  let good = 0, bad = 0, scored = 0;
  for (const t of TRAITS) {
    const raw = own[t.key];
    if (raw == null || raw === "") continue;
    const value = traitValue(raw);
    const rows = (o[t.table] as ({ n: number; mean_reward: number } & Record<string, unknown>)[]).filter((r) => r.n >= minN);
    const row = rows.find((r) => traitValue(r[t.key]) === value);
    const best = rows.reduce<typeof row>((b, r) => (b == null || r.mean_reward > b.mean_reward ? r : b), undefined);
    if (!row || !best) {
      lines.push({ tone: "neutral", text: `${t.label}: ${value}`, detail: `under ${minN} videos like this in the panel, not scored` });
      continue;
    }
    scored++;
    const isBest = row === best;
    if (isBest) good++; else if (row.mean_reward < 0) bad++;
    lines.push({
      tone: isBest ? "good" : row.mean_reward < 0 ? "bad" : "neutral",
      text: `${t.label}: ${value} ${times(row.mean_reward)} videos like them, ${row.n} videos`,
      detail: isBest ? "the best value in the panel" : `best is ${traitValue(best[t.key])} at ${times(best.mean_reward)}`,
    });
  }

  const last = v?.observations.at(-1);
  if (last && last.views) {
    const eng = (last.shares ?? 0) + (last.saves ?? 0);
    lines.push({
      tone: p.engagement_lift == null ? "neutral" : p.engagement_lift > 0 ? "good" : "bad",
      text: `${last.likes ?? 0} likes, ${last.shares ?? 0} shares, ${last.saves ?? 0} saves, ${last.comments ?? 0} comments on ${n(last.views)} views`,
      detail: p.engagement_lift == null ? undefined : `${eng === 0 ? "no" : p.engagement_per_1k} shares or saves per 1k, ${p.engagement_lift > 0 ? "+" : ""}${p.engagement_lift.toFixed(2)} vs the niche`,
    });
  }

  let growth: Tone | null = null;
  const obs = (v?.observations ?? []).filter((x) => x.views != null);
  if (v && obs.length >= 2) {
    const t0 = v.video.create_time;
    const first = obs[0], end = obs[obs.length - 1];
    const prev = [...obs].reverse().find((x) => end.observed_at - x.observed_at >= 6 * 3600);
    const firstH = (first.observed_at - t0) / 3600;
    if (prev && firstH > 0.25) {
      const span = (end.observed_at - prev.observed_at) / 3600;
      const vphFirst = (first.views ?? 0) / firstH, vphRecent = ((end.views ?? 0) - (prev.views ?? 0)) / span;
      growth = vphRecent < vphFirst / 4 ? "bad" : vphRecent > vphFirst ? "good" : "neutral";
      lines.push({
        tone: growth,
        text: growth === "bad" ? "views slowed" : growth === "good" ? "views still climbing" : "views steady",
        detail: `${n(vphFirst)} an hour in the first ${hours(firstH)}, ${n(vphRecent)} an hour over the last ${hours(span)}`,
      });
    }
  }

  const demo = own.demo_score_1_5 ?? own.demo_score;
  if (typeof demo === "number") lines.push({ tone: "neutral", text: `demo ${demo}/5`, detail: "is the product obvious in 5s; a gate, not a prediction" });

  const expected = p.expected_log != null ? n(10 ** p.expected_log) : null;
  const where = `${n(p.views_now ?? 0)} views at ${hours(p.age_h)}${expected ? `, videos like it had about ${expected}` : ""}`;
  if (p.age_h < MIN_AGE_H_OWN) return { verdict: "early", headline: `Too early to judge: ${where}`, reason: `Posts under ${MIN_AGE_H_OWN}h are noise; check back at ${MIN_AGE_H_OWN}h.`, lines };
  if (p.lift_matched == null) return { verdict: "unscored", headline: `Not scored yet: ${where}`, reason: p.views_now ? "No reference videos of this age yet." : "No views yet.", lines };

  const verdict = p.lift_matched > CLEAR ? "win" : p.lift_matched < -CLEAR ? "miss" : "average";
  const parts: string[] = [];
  if (verdict === "miss") {
    if (scored && bad >= Math.ceil(scored / 2)) parts.push(`${bad} of its ${scored} scored traits do worse than average across ${n(o.scored)} videos`);
    if (p.engagement_lift != null && p.engagement_lift < 0) parts.push("fewer shares and saves per view than the niche");
    if (growth === "bad") parts.push("views slowed after the first hours");
  } else if (verdict === "win") {
    if (good) parts.push(`${good} of its ${scored} scored traits are the best value in the panel`);
    if (p.engagement_lift != null && p.engagement_lift > 0) parts.push("more shares and saves per view than the niche");
    if (growth === "good") parts.push("views still climbing");
  }
  const lead = verdict === "miss" ? "Fell short" : verdict === "win" ? "Did well" : "About average";
  const reason = parts.length ? `${parts.join("; ")}.` : verdict === "average" ? "Nothing in the data stands out either way." : "Nothing in the data explains it yet.";
  return { verdict, headline: `${lead}: ${times(p.lift_matched)} videos like it, ${where}`, reason, lines };
}

const tones: Record<Tone, string> = { good: "text-emerald-300", bad: "text-red-300", neutral: "text-neutral-300" };

export function WhyFold({ why }: { why: Why }) {
  const pill = why.verdict === "win" ? <Pill tone="good">why it worked</Pill> : why.verdict === "miss" ? <Pill tone="bad">why it fell short</Pill> : <Pill tone="neutral">why</Pill>;
  return (
    <Fold className="mt-3" summary={<span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">{pill}<span className="text-neutral-100">{why.headline}</span></span>}>
      <p className="text-sm text-neutral-200">{why.reason}</p>
      {why.lines.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs">
          {why.lines.map((l, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-x-2">
              <span className={`tabular-nums ${tones[l.tone]}`}>{l.text}</span>
              {l.detail && <span className="text-neutral-500">{l.detail}</span>}
            </li>
          ))}
        </ul>
      )}
    </Fold>
  );
}
