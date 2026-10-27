import type { ClipLabels } from "@/lib/api";
import { traitValue } from "../charts";
import { Card } from "../ui";

// scoreboard.PACING_EDGES: cuts per 10 s -> slow / medium / fast / frantic
const bucket = (cuts: unknown) => {
  const x = Number(cuts);
  if (!Number.isFinite(x)) return null;
  return x < 2 ? "slow" : x < 4 ? "medium" : x < 7 ? "fast" : "frantic";
};

const ROWS: [string, (t: Record<string, unknown>) => unknown][] = [
  ["hook", (t) => t.hook_type],
  ["look", (t) => t.visual_style],
  ["sound", (t) => t.music_role],
  ["pace", (t) => bucket(t.pacing_cuts_per_10s)],
  ["product by 5s", (t) => t.product_on_screen_by_5s],
];

/** What the classifier saw in our clip, in the same words What wins uses, then the beats. */
export function LabelsBlock({ labels }: { labels: ClipLabels | null | undefined }) {
  if (!labels) return null;
  const t = labels.tags;
  return (
    <Card title="What is in this clip">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-5">
        {ROWS.map(([label, pick]) => {
          const v = pick(t);
          if (v == null || v === "") return null;
          return (
            <div key={label}>
              <dt className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</dt>
              <dd className="mt-0.5 text-neutral-100">{traitValue(v)}</dd>
            </div>
          );
        })}
      </dl>
      {typeof t.hook_text === "string" && t.hook_text && <p className="mt-3 text-sm text-neutral-400">first 2 seconds: <span className="text-neutral-200">{t.hook_text}</span></p>}
      {labels.beats.length > 0 && (
        <ol className="mt-3 space-y-1 text-sm">
          {labels.beats.map((b, i) => (
            <li key={i} className="flex gap-3"><span className="w-8 shrink-0 tabular-nums text-neutral-500">{Math.round(b.t_s)}s</span><span className="text-neutral-200">{b.what}</span></li>
          ))}
        </ol>
      )}
      <p className="mt-3 text-xs text-neutral-500">Labelled by the same classifier that labels the research videos, so these words match What wins.</p>
    </Card>
  );
}
