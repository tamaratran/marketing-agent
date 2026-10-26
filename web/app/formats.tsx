import Link from "next/link";
import { get, type Concept, type Overview, type Script } from "@/lib/api";
import { TraitBars, traitValue, type RankRow } from "./charts";
import { Thumb } from "./thumb";
import { Fold, H1, NextStep, Pill, formatName, times } from "./ui";

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
      <H1 sub={`What is working in ${o.niche} on TikTok, grouped into formats we can copy.`}>Formats</H1>

      <section className="mb-8 rounded-lg border border-neutral-800 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="text-sm font-semibold">What wins</h2>
          <Link href="/how" className="text-xs text-neutral-500 hover:text-neutral-300 hover:underline">How these are scored</Link>
        </div>
        <div className="mt-3 mb-4 grid grid-cols-3 gap-2">
          <Stat n={o.videos} label={`${o.niche} videos tracked`} />
          <Stat n={o.scored} label="scored" />
          <Stat n={o.tagged} label="classified" />
        </div>
        {tables.length ? (
          <>
            <ul className="grid gap-2 text-sm sm:grid-cols-2">
              {tables.map((t) => {
                const top = [...t.rows].sort((a, b) => (b.mean_reward ?? 0) - (a.mean_reward ?? 0))[0];
                return (
                  <li key={t.k} className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-neutral-500">{t.title}:</span>
                    <span className="text-neutral-100">{traitValue(top[t.col] as string | boolean | null)}</span>
                    <span className="text-emerald-300">{times(top.mean_reward ?? 0)}</span>
                    <span className="text-xs text-neutral-500">{top.n} video{top.n === 1 ? "" : "s"}</span>
                  </li>
                );
              })}
            </ul>
            <Fold summary={<span className="text-xs text-neutral-400">Every trait</span>} className="mt-3">
              <div className="grid gap-5 sm:grid-cols-2">
                {tables.map((t) => <TraitBars key={t.k} rows={t.rows} column={t.col} title={t.title} max={5} />)}
              </div>
            </Fold>
          </>
        ) : (
          <p className="text-sm text-neutral-500">No trait has {o.trait_min_n ?? 5} classified videos yet. <Link href="/learnings" className="text-sky-300 hover:underline">Research again</Link> classifies the rest.</p>
        )}
      </section>

      {sorted.length === 0 && <p className="text-sm text-neutral-500">No formats yet. A run cycle groups research videos into formats.</p>}
      <ul className="space-y-2">
        {sorted.map((c) => {
          const traits = Object.entries(c.traits ?? {}).filter(([k, v]) => v != null && TRAIT[k]);
          return (
            <li key={c.id}>
              <Fold open={c.kind === "format"} summary={
                <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-base font-semibold">{formatName(c.name)}</span>
                  {c.kind === "format" && <Pill tone="good">our clone</Pill>}
                  {c.pick_share != null && <span className="text-xs text-neutral-500">picked {Math.round(c.pick_share * 100)}%</span>}
                  {c.n && c.mean_reward != null ? <span className={`text-xs ${c.mean_reward > 0 ? "text-emerald-300" : "text-red-300"}`}>{times(c.mean_reward)} videos like it</span> : null}
                  <span className="flex gap-1">{(c.examples ?? []).slice(0, 3).map((e) => <Thumb key={e.id} id={e.id} size={22} />)}</span>
                </span>
              }>
              <p className="text-sm leading-relaxed text-neutral-400">{c.description}</p>
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
              </Fold>
            </li>
          );
        })}
      </ul>
      <NextStep from="/" />
    </>
  );
}

function Stat({ n, label }: { n: number; label: string }) {
  return (
    <div className="rounded-lg border border-neutral-800 px-3 py-2">
      <div className="text-xl font-semibold tabular-nums text-neutral-100">{n.toLocaleString("en-US")}</div>
      <div className="text-xs text-neutral-500">{label}</div>
    </div>
  );
}
