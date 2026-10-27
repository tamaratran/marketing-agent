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

const PLAYBACK: Record<string, string> = { real_time: "real speed", sped_up: "sped up", slowed: "slowed down", mixed: "mixed speeds" };

type Shot = { t_s: number; seconds: number; camera: string; what: string };
type Overlay = { t_s: number; text: string; position: string };
type Moment = { t_s: number; what: string };
const list = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
const sec = (t: number) => `${Math.round(t * 10) / 10}s`;

/** True when the tags came from the video labeller (whole clip watched), not sampled frames. */
export const isDetailed = (t: Record<string, unknown> | null | undefined) => !!t && Array.isArray(t.shots);

/** The breakdown only the video labeller can give: how the hook is delivered, playback speed,
 *  the shot list, on-screen text with timing, and what the product does second by second. */
export function VideoBreakdown({ tags: t }: { tags: Record<string, unknown> }) {
  if (!isDetailed(t)) return null;
  const shots = list<Shot>(t.shots), overlays = list<Overlay>(t.text_overlays), product = list<Moment>(t.product_timeline);
  const hookHow = [t.hook_spoken && "spoken", t.hook_on_screen && "written on screen"].filter(Boolean).join(" and ") || "only in the caption";
  const facts: [string, string][] = [
    ["hook delivery", hookHow],
    ["playback", PLAYBACK[String(t.playback)] ?? String(t.playback ?? "")],
    ["speech", t.has_voiceover ? (t.lip_sync ? "on camera, lips match" : "voiceover, no one seen speaking") : "no speech"],
    ["cuts", `${shots.length} shot${shots.length === 1 ? "" : "s"}`],
  ];
  return (
    <div className="mt-4 space-y-4 text-sm">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        {facts.map(([k, v]) => (
          <div key={k}>
            <dt className="text-[11px] uppercase tracking-wide text-neutral-500">{k}</dt>
            <dd className="mt-0.5 text-neutral-100">{v}</dd>
          </div>
        ))}
      </dl>
      {shots.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] uppercase tracking-wide text-neutral-500">shot by shot</p>
          <ol className="space-y-1">
            {shots.map((s, i) => (
              <li key={i} className="flex gap-3">
                <span className="w-20 shrink-0 tabular-nums text-neutral-500">{sec(s.t_s)} · {sec(s.seconds)}</span>
                <span className="text-neutral-200"><span className="text-neutral-400">{s.camera}:</span> {s.what}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      <div>
        <p className="mb-1 text-[11px] uppercase tracking-wide text-neutral-500">text on screen</p>
        {overlays.length > 0 ? (
          <ol className="space-y-1">
            {overlays.map((o, i) => (
              <li key={i} className="flex gap-3"><span className="w-20 shrink-0 tabular-nums text-neutral-500">{sec(o.t_s)} · {o.position}</span><span className="text-neutral-200">&ldquo;{o.text}&rdquo;</span></li>
            ))}
          </ol>
        ) : (
          <p className="text-neutral-500">none</p>
        )}
      </div>
      {product.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] uppercase tracking-wide text-neutral-500">product on screen</p>
          <ol className="space-y-1">
            {product.map((m, i) => (
              <li key={i} className="flex gap-3"><span className="w-20 shrink-0 tabular-nums text-neutral-500">{sec(m.t_s)}</span><span className="text-neutral-200">{m.what}</span></li>
            ))}
          </ol>
        </div>
      )}
      {list<string>(t.quality_issues).length > 0 && (
        <p className="text-gold">flagged: {list<string>(t.quality_issues).join("; ")}</p>
      )}
    </div>
  );
}

/** What the labeller saw in our clip, in the same words What wins uses, then the breakdown. */
export function LabelsBlock({ labels }: { labels: ClipLabels | null | undefined }) {
  if (!labels) return null;
  const t = labels.tags;
  const detailed = isDetailed(t);
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
      {detailed ? (
        <VideoBreakdown tags={t} />
      ) : (
        labels.beats.length > 0 && (
          <ol className="mt-3 space-y-1 text-sm">
            {labels.beats.map((b, i) => (
              <li key={i} className="flex gap-3"><span className="w-8 shrink-0 tabular-nums text-neutral-500">{Math.round(b.t_s)}s</span><span className="text-neutral-200">{b.what}</span></li>
            ))}
          </ol>
        )
      )}
      <p className="mt-3 text-xs text-neutral-500">
        {detailed
          ? `Gemini (${labels.model ?? "video model"}) watched the whole clip with sound. The research videos get the same labels, so these words match What wins.`
          : "Labelled from sampled frames and the transcript by the same classifier that labels the research videos, so these words match What wins."}
      </p>
    </Card>
  );
}
