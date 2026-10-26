import { human, times } from "./ui";

export type RankRow = { n: number; mean_reward: number; stderr?: number; win_rate: number } & Record<string, unknown>;

export const traitValue = (v: unknown) => (v === "True" || v === true ? "yes" : v === "False" || v === false ? "no" : human(String(v)));

/** Mean lift per trait value as horizontal bars with the sample size, so a bar on 2 videos
 *  reads as thin evidence next to one on 20. The bar is log10 lift: +1 is 10x. */
export function TraitBars({ rows, column, title, max = 6 }: { rows: RankRow[]; column: string; title: string; max?: number }) {
  const shown = rows.slice(0, max);
  if (!shown.length) return null;
  const span = Math.max(0.5, ...shown.map((r) => Math.abs(r.mean_reward) + (r.stderr ?? 0)));
  const bigN = Math.max(...shown.map((r) => r.n));
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs"><span className="font-medium text-neutral-200">{title}</span><span className="text-neutral-500">lift vs videos like it · n</span></div>
      <ul className="space-y-1.5">
        {shown.map((r) => {
          const v = r.mean_reward, w = (Math.abs(v) / span) * 50, left = v >= 0 ? 50 : 50 - w;
          const err = ((r.stderr ?? 0) / span) * 50;
          return (
            <li key={String(r[column])} className="grid grid-cols-[7rem_1fr_5rem] items-center gap-2 text-xs sm:grid-cols-[9rem_1fr_6rem]">
              <span className="truncate text-neutral-300" title={traitValue(r[column])}>{traitValue(r[column])}</span>
              <div className="relative h-4 rounded bg-neutral-900" role="img" aria-label={`${traitValue(r[column])}: ${times(v)} videos like it on ${r.n} videos`}>
                <div className="absolute inset-y-0 left-1/2 w-px bg-neutral-700" />
                <div className={`absolute inset-y-1 rounded-sm ${v >= 0 ? "bg-emerald-400" : "bg-red-400"}`} style={{ left: `${left}%`, width: `${Math.max(w, 0.5)}%`, opacity: 0.45 + 0.55 * Math.sqrt(r.n / bigN) }} />
                {err > 0 && <div className="absolute top-1/2 h-px bg-neutral-100/70" style={{ left: `${50 + (v / span) * 50 - err}%`, width: `${2 * err}%` }} />}
              </div>
              <span className="text-right tabular-nums text-neutral-400"><span className={v >= 0 ? "text-emerald-300" : "text-red-300"}>{times(v)}</span> · {r.n}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** One number per cycle, oldest left, as a small line with dots. */
export function Trend({ points, label, fmt }: { points: { t: number; v: number }[]; label: string; fmt: (v: number) => string }) {
  if (points.length === 0) return null;
  const W = 240, H = 56, pad = 6;
  const vs = points.map((p) => p.v);
  const lo = Math.min(...vs), hi = Math.max(...vs), range = hi - lo || 1;
  const x = (i: number) => (points.length === 1 ? W / 2 : pad + (i / (points.length - 1)) * (W - 2 * pad));
  const y = (v: number) => H - pad - ((v - lo) / range) * (H - 2 * pad);
  const last = points[points.length - 1];
  return (
    <div className="rounded-lg border border-neutral-800 p-3">
      <div className="flex items-baseline justify-between text-xs"><span className="text-neutral-400">{label}</span><span className="font-medium text-neutral-100">{fmt(last.v)}</span></div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-1 w-full" role="img" aria-label={`${label} over ${points.length} cycles, now ${fmt(last.v)}`}>
        {points.length > 1 && <polyline fill="none" stroke="#a3a3a3" strokeWidth={1.5} points={points.map((p, i) => `${x(i)},${y(p.v)}`).join(" ")} />}
        {points.map((p, i) => <circle key={p.t} cx={x(i)} cy={y(p.v)} r={2.5} fill="#e5e5e5"><title>{`${new Date(p.t * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" })}: ${fmt(p.v)}`}</title></circle>)}
      </svg>
      <div className="text-[10px] text-neutral-600">{points.length === 1 ? "1 cycle so far" : `${points.length} cycles, oldest left`}</div>
    </div>
  );
}
