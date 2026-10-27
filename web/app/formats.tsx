import Link from "next/link";
import { get, type Concept, type Overview, type Script } from "@/lib/api";
import { TraitBars, traitValue, type RankRow } from "./charts";
import { Thumb } from "./thumb";
import { HowItDecides } from "./how";
import { TopVideos } from "./top-videos";
import { Fold, H1, formatName, times } from "./ui";

const TABLES: [keyof Overview, string, string][] = [
  ["hooks", "hook_type", "Hook type"], ["styles", "visual_style", "Visual style"],
  ["pacing", "pacing_bucket", "Pacing (cuts per 10s)"], ["sound", "music_role", "Sound"],
];
const TRAIT: Record<string, string> = { hook_type: "hook", visual_style: "style", pacing_bucket: "pace", product_on_screen_by_5s: "product by 5s" };

/** The most-viewed scraped videos the research step filed under a format, each with its lift against videos like it. */
export function Examples({ examples }: { examples?: Concept["examples"] }) {
  if (!examples?.length) return <span className="text-xs text-neutral-600">no examples</span>;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {examples.map((e) => (
        <a key={e.id} href={e.url} target="_blank" rel="noreferrer" className="flex min-w-0 items-center gap-3 text-xs hover:text-neutral-50">
          <Thumb id={e.id} size={44} />
          <span className="min-w-0">
            <span className="block truncate text-neutral-200">@{e.author}</span>
            <span className="block text-neutral-500">{e.views != null ? `${e.views.toLocaleString()} views` : "views pending"}</span>
            {e.reward != null && <span className={`block ${e.reward > 0 ? "text-neutral-50" : "text-neutral-500"}`}>{times(e.reward)} videos like it</span>}
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

      <div className="grid grid-cols-3 gap-6">
        <Stat n={o.videos} label={`${o.niche} videos tracked`} />
        <Stat n={o.scored} label="scored against videos like them" />
        <Stat n={o.tagged} label="classified by trait" />
      </div>

      <section className="mt-12">
        <h2 className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-neutral-500">What wins</h2>
        {tables.length ? (
          <div className="grid gap-8 sm:grid-cols-2">
            {tables.map((t) => <TraitBars key={t.k} rows={t.rows} column={t.col} title={t.title} max={4} />)}
          </div>
        ) : (
          <p className="text-sm text-neutral-500">No trait has {o.trait_min_n ?? 5} classified videos yet. <Link href="/learnings" className="text-gold hover:underline">Research again</Link> classifies the rest.</p>
        )}
      </section>

      <section className="mt-14">
        <h2 className="mb-1 text-xs font-medium uppercase tracking-[0.14em] text-neutral-500">Formats, by how often the picker chooses them</h2>
        <div className="grid grid-cols-[1.5rem_minmax(0,1fr)_5.5rem] items-baseline gap-x-3 pb-2 text-xs text-neutral-500 sm:grid-cols-[2rem_1fr_9rem_6rem_6rem] sm:gap-x-4">
          <span>#</span><span>format</span><span>pick share</span><span className="hidden sm:block">our lift</span><span className="hidden text-right sm:block">examples</span>
        </div>
      {sorted.length === 0 && <p className="text-sm text-neutral-500">No formats yet. A run cycle groups research videos into formats.</p>}
      <ul>
        {sorted.map((c, i) => {
          const traits = Object.entries(c.traits ?? {}).filter(([k, v]) => v != null && TRAIT[k]);
          const share = c.pick_share ?? 0;
          return (
            <li key={c.id}>
              <Fold open={i < 5} summary={
                <span className="grid min-w-0 grid-cols-[1.5rem_minmax(0,1fr)_5.5rem] items-center gap-x-3 sm:grid-cols-[2rem_1fr_9rem_6rem_6rem] sm:gap-x-4">
                  <span className="text-xs tabular-nums text-neutral-600">{i + 1}</span>
                  <span className="min-w-0 truncate font-medium text-neutral-100">{formatName(c.name)}{c.kind === "format" && <span className="ml-2 text-xs font-normal text-gold">ours</span>}</span>
                  <span className="flex items-center gap-2"><span className="h-1 w-10 bg-neutral-800 sm:w-24"><span className="block h-1 bg-neutral-200" style={{ width: `${Math.round(share * 100)}%` }} /></span><span className="text-xs tabular-nums text-neutral-400">{Math.round(share * 100)}%</span></span>
                  <span className="hidden text-xs tabular-nums sm:block">{c.n && c.mean_reward != null ? <span className={c.mean_reward > 0 ? "text-neutral-50" : "text-neutral-400"}>{times(c.mean_reward)}</span> : <span className="text-neutral-600">–</span>}</span>
                  <span className="hidden justify-end gap-1 sm:flex">{(c.examples ?? []).slice(0, 3).map((e) => <Thumb key={e.id} id={e.id} size={22} />)}</span>
                </span>
              }>
              <p className="text-sm leading-relaxed text-neutral-400">{c.description}</p>
              {traits.length > 0 && (
                <p className="mt-3 text-xs text-neutral-500">
                  {traits.map(([k, v], j) => <span key={k}>{j > 0 && <span className="mx-2 text-neutral-700">·</span>}{TRAIT[k]} <span className="text-neutral-300">{traitValue(v)}</span></span>)}
                </p>
              )}
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                <Fact label="early traction" title="How fast its videos gained views, discounted for big accounts">{Math.round(c.early_score)}</Fact>
                <Fact label="head start" title="The score the picker starts this format from, plus what its traits have earned">
                  {c.prior.toFixed(2)}
                  {c.trait_detail?.length ? <span className={(c.trait_bonus ?? 0) > 0 ? "text-neutral-50" : (c.trait_bonus ?? 0) < 0 ? "text-neutral-500" : "text-neutral-500"}> {(c.trait_bonus ?? 0) >= 0 ? "+" : ""}{(c.trait_bonus ?? 0).toFixed(2)} traits</span> : null}
                </Fact>
                <Fact label="scripts, 14 days">{used.get(c.name) ?? 0}</Fact>
                <Fact label="our results" title="Our posts in this format against niche videos of the same age from accounts the same size">
                  {c.n && c.mean_reward != null ? <span className={c.mean_reward > 0 ? "text-neutral-50" : "text-neutral-500"}>{times(c.mean_reward)} videos like it <span className="text-neutral-500">({c.n} post{c.n > 1 ? "s" : ""})</span></span> : <span className="text-neutral-500">not posted yet</span>}
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
      </section>
      <div className="mt-14">
        <Fold summary={<span className="text-sm font-medium text-neutral-200">How formats are scored and picked</span>}>
          <div className="pt-2"><HowItDecides part="formats" /></div>
        </Fold>
        <Fold summary={<span className="text-sm font-medium text-neutral-200">Best research videos</span>}>
          <div className="pt-2"><TopVideos o={o} /></div>
        </Fold>
      </div>
    </>
  );
}

function Stat({ n, label }: { n: number; label: string }) {
  return (
    <div>
      <div className="text-4xl font-semibold tabular-nums tracking-tight text-neutral-50">{n.toLocaleString("en-US")}</div>
      <div className="mt-1 text-xs text-neutral-500">{label}</div>
    </div>
  );
}
