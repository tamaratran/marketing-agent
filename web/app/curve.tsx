import type { Observation } from "@/lib/api";

const AGES = [1, 6, 24, 72, 168];

/** Views against age in hours, log-log, with the fixed ages the features are read at. */
export function Curve({ obs, createTime, baselineLog }: { obs: Observation[]; createTime: number; baselineLog?: number | null }) {
  const pts = obs.filter((o) => o.views && o.views > 0).map((o) => ({ a: Math.max((o.observed_at - createTime) / 3600, 0.1), v: o.views as number }));
  if (pts.length === 0) return <p className="text-sm text-neutral-500">No observations yet.</p>;
  const W = 640, H = 220, L = 64, B = 28;
  const xs = pts.map((p) => Math.log10(p.a)), ys = pts.map((p) => Math.log10(p.v));
  const x0 = Math.min(-1, ...xs), x1 = Math.max(Math.log10(200), ...xs);
  const y0 = Math.min(0, ...ys, baselineLog ?? 99) - 0.2, y1 = Math.max(...ys, baselineLog ?? 0) + 0.3;
  const X = (a: number) => L + ((Math.log10(a) - x0) / (x1 - x0)) * (W - L - 8);
  const Y = (v: number) => H - B - ((Math.log10(v) - y0) / (y1 - y0)) * (H - B - 8);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p.a).toFixed(1)},${Y(p.v).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-2xl text-neutral-400">
      {AGES.map((a) => (
        <g key={a}>
          <line x1={X(a)} x2={X(a)} y1={8} y2={H - B} stroke="currentColor" strokeOpacity={0.15} />
          <text x={X(a)} y={H - 10} fontSize={10} textAnchor="middle" fill="currentColor">{a < 24 ? `${a}h` : `${a / 24}d`}</text>
        </g>
      ))}
      {[1, 2, 3, 4, 5, 6].filter((e) => e >= y0 && e <= y1).map((e) => (
        <g key={e}>
          <line x1={L} x2={W - 8} y1={Y(10 ** e)} y2={Y(10 ** e)} stroke="currentColor" strokeOpacity={0.15} />
          <text x={L - 6} y={Y(10 ** e) + 3} fontSize={10} textAnchor="end" fill="currentColor">{(10 ** e).toLocaleString()}</text>
        </g>
      ))}
      {baselineLog != null && <line x1={L} x2={W - 8} y1={Y(10 ** baselineLog)} y2={Y(10 ** baselineLog)} stroke="#f59e0b" strokeDasharray="4 3" />}
      <path d={d} fill="none" stroke="#38bdf8" strokeWidth={2} />
      {pts.map((p, i) => <circle key={i} cx={X(p.a)} cy={Y(p.v)} r={3} fill="#38bdf8" />)}
    </svg>
  );
}
