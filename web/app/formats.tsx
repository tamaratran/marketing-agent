import Link from "next/link";
import { get, type Concept, type Overview, type Script } from "@/lib/api";
import { TraitBars, traitValue, type RankRow } from "./charts";
import { Thumb } from "./thumb";
import { H1, Pill, formatName, times } from "./ui";

const TABLES: [keyof Overview, string, string][] = [
  ["hooks", "hook_type", "Hook type"], ["styles", "visual_style", "Visual style"],
  ["pacing", "pacing_bucket", "Pacing (cuts per 10s)"], ["sound", "music_role", "Sound"],
];
const TRAIT: Record<string, string> = { hook_type: "hook", visual_style: "style", pacing_bucket: "pace", product_on_screen_by_5s: "product by 5s" };

/** The most-viewed scraped videos the research step filed under a format, each with its lift against videos like it. */
export function Examples({ examples }: { examples?: Concept["examples"] }) {
  if (!examples?.length) return <span className="text-xs text-neutral-600">no examples</span>;
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {examples.map((e) => (
        <a key={e.id} href={e.url} target="_blank" rel="noreferrer" className="flex min-w-0 items-center gap-2 rounded border border-neutral-800 p-2 text-xs hover:border-neutral-600">
          <Thumb id={e.id} size={44} />
          <span className="min-w-0">
            <span className="block truncate text-neutral-200">@{e.author}</span>
            <span className="block text-neutral-500">{e.views != null ? `${e.views.toLocaleString()} views` : "views pending"}</span>
            {e.reward != null && <span className={`block ${e.reward > 0 ? "text-emerald-300" : "text-red-300"}`}>{times(e.reward)} videos like it</span>}
          </span>
        </a>
      ))}
    </div>
  );
}

function Fact({ label, children, title }: { label: string; children: React.ReactNode; title?: string }) {
  return (
    <div title={title}>
      <dt className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-neutral-200">{children}</dd>
    </div>
  );
}

/** The Formats page: what the whole panel says, then every format the research found with its scores, our results and examples. Served at / and /concepts. */
export async function Formats() {
  const [rows, scripts, o] = await Promise.all([
    get<Concept[]>("/concepts"), get<Script[]>("/scripts?days=14&limit=200"), get<Overview>("/overview"),
  ]);
  const used = new Map<string, number>();
  for (const s of scripts) used.set(s.concept, (used.get(s.concept) ?? 0) + 1);
  const tables = TABLES.map(([k, col, title]) => ({ k, col, title, rows: (o[k] as RankRow[] | undefined) ?? [] })).filter((t) => t.rows.length);
  const sorted = [...rows].sort((a, b) => (b.pick_share ?? 0) - (a.pick_share ?? 0));

  return (
    <>
      <H1 sub={`What is working in ${o.niche} on TikTok right now, grouped into formats we can copy. Each cycle the picker chooses one and writes scripts in it.`}>Formats</H1>

      <section className="mb-8 rounded-lg border border-neutral-800 p-4">
        <h2 className="text-sm font-semibold">What wins, across the whole panel</h2>
        <p className="mt-1 mb-4 text-xs leading-relaxed text-neutral-500">
          {o.videos} recent {o.niche} videos from other accounts tracked, {o.scored} scored against {o.niche} videos of the same age from accounts the same size, {o.tagged} classified by the vision model.
          Each bar is the mean lift of videos with that trait: 1x means the same views as videos like it, 10x ten times more. The number after the dot is how many scored videos the bar rests on; the white tick is one standard error.
          {o.tagged < 40 && ` With ${o.tagged} classified so far these are early reads, not verdicts; each cycle classifies more.`}
        </p>
        {tables.length ? (
          <div className="grid gap-5 sm:grid-cols-2">
            {tables.map((t) => <TraitBars key={t.k} rows={t.rows} column={t.col} title={t.title} max={5} />)}
          </div>
        ) : (
          <p className="text-sm text-neutral-500">No scored videos have been classified yet. The next cycle classifies the first batch.</p>
        )}
        <p className="mt-4 text-xs text-neutral-500">Cycle by cycle, with our own posts: <Link href="/learnings" className="text-sky-300 hover:underline">Learnings</Link>. How the picker turns this into a choice: <Link href="/how" className="text-sky-300 hover:underline">How it decides</Link>.</p>
      </section>

      {sorted.length === 0 && <p className="text-sm text-neutral-500">No formats yet. A run cycle groups research videos into formats.</p>}
      <ul className="space-y-4">
        {sorted.map((c) => {
          const traits = Object.entries(c.traits ?? {}).filter(([k, v]) => v != null && TRAIT[k]);
          return (
            <li key={c.id} className="rounded-lg border border-neutral-800 p-4">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 className="text-base font-semibold">{formatName(c.name)}</h2>
                {c.kind === "format" && <Pill tone="good">our clone</Pill>}
                {c.pick_share != null && <span className="text-xs text-neutral-500">picked {Math.round(c.pick_share * 100)}% of the time</span>}
              </div>
              <p className="mt-1 text-sm leading-relaxed text-neutral-400">{c.description}</p>
              {traits.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {traits.map(([k, v]) => <span key={k} className="rounded-full border border-neutral-800 px-2 py-0.5 text-xs text-neutral-400">{TRAIT[k]}: {traitValue(v)}</span>)}
                </div>
              )}
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                <Fact label="early traction" title="How fast its videos gained views, discounted for big accounts">{Math.round(c.early_score)}</Fact>
                <Fact label="head start" title="The score the picker starts this format from, plus what its traits have earned">
                  {c.prior.toFixed(2)}
                  {c.trait_detail?.length ? <span className={(c.trait_bonus ?? 0) > 0 ? "text-emerald-300" : (c.trait_bonus ?? 0) < 0 ? "text-red-300" : "text-neutral-500"}> {(c.trait_bonus ?? 0) >= 0 ? "+" : ""}{(c.trait_bonus ?? 0).toFixed(2)} traits</span> : null}
                </Fact>
                <Fact label="scripts, 14 days">{used.get(c.name) ?? 0}</Fact>
                <Fact label="our results" title="Our posts in this format against niche videos of the same age from accounts the same size">
                  {c.n && c.mean_reward != null ? <span className={c.mean_reward > 0 ? "text-emerald-300" : "text-red-300"}>{times(c.mean_reward)} videos like it <span className="text-neutral-500">({c.n} post{c.n > 1 ? "s" : ""})</span></span> : <span className="text-neutral-500">not posted yet</span>}
                </Fact>
              </dl>
              <div className="mt-4">
                <div className="mb-2 text-xs text-neutral-500">Examples from other accounts</div>
                <Examples examples={c.examples} />
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}
