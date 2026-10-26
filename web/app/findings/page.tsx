import Link from "next/link";
import { fmt, get, type Findings, type Level } from "@/lib/api";
import { Card, H1, Note, Pill, Stat, Table, human } from "../ui";
import { RefreshButtons } from "../refresh";

export const dynamic = "force-dynamic";

const tone = (v: string) => (v === "better" ? "good" : v === "worse" ? "bad" : v === "thin" ? "warn" : "neutral");
const verdictText: Record<string, string> = { thin: "too few videos", "no evidence": "no clear difference", reference: "baseline" };
const outcomeText: Record<string, string> = {
  lift_now: "Beat videos like it (same age, same account size), latest check",
  lift_72h: "Beat the creator's usual at 3 days",
  growth_6_24: "Kept growing from 6h to 24h",
  log_vph_6h: "Fast start (views per hour at 6h)",
};

function Levels({ levels, minN }: { levels: Level[]; minN: number }) {
  return (
    <Table
      head={["value", "videos", "raw average", "after controls", "likely range", "verdict"]}
      rows={levels.map((l) => [
        human(l.level),
        l.n < minN ? <span key="n" className="text-amber-300" title={`under the ${minN} needed`}>{l.n}</span> : l.n,
        fmt(l.raw_mean),
        l.reference ? "baseline" : (l.coef > 0 ? "+" : "") + fmt(l.coef),
        l.reference ? "" : `${fmt(l.lo)} to ${fmt(l.hi)}`,
        <span key="v" className="flex gap-1"><Pill tone={tone(l.verdict)}>{verdictText[l.verdict] ?? l.verdict}</Pill>{l.travels && <Pill tone="good">holds across niches</Pill>}</span>,
      ])}
    />
  );
}

export default async function Page({ searchParams }: { searchParams: Promise<{ outcome?: string; niche?: string }> }) {
  const sp = await searchParams;
  const f = await get<Findings>("/findings");
  const outcome = sp.outcome && f.fits[sp.outcome] ? sp.outcome : f.fits.lift_now ? "lift_now" : "lift_72h";
  const niche = sp.niche;
  const fits = f.fits[outcome] ? (niche ? f.fits[outcome].per_niche[niche] ?? {} : f.fits[outcome].pooled) : {};
  const st = f.status;
  const minN = f.min_n ?? 20;
  const fitted = Object.entries(fits).filter(([, fit]) => fit.levels?.length);
  const empty = Object.entries(fits).filter(([, fit]) => !fit.levels?.length).map(([t]) => t);
  return (
    <>
      <H1 sub="Which video traits (hook, style, length, posting time...) actually go with more views, once you account for account size, niche, length and posting hour. Built from a fixed group of fresh research videos followed over a week.">Findings</H1>
      <div className="mb-4"><RefreshButtons /></div>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="videos being followed" value={st.videos} hint="Enrolled when under 6 hours old." />
        <Stat label="tagged by the classifier" value={st.tagged ?? 0} />
        <Stat label="with the creator's usual views" value={st.with_baseline ?? 0} hint="Needed to judge a video against its own account." />
        <Stat label="scored" value={st.reached["scored"] ?? 0} hint={`A day old with a view count, judged against videos like them. Findings need ${minN}.`} />
        <Stat label="3 days old" value={st.reached["72h"] ?? 0} hint="For the slower 3-day measures." />
      </div>
      {f.collecting && (
        <Card className="mb-4">
          <p className="text-sm text-amber-200">
            Still collecting, so nothing below is a result yet. {st.reached["scored"] ?? 0} of {st.videos} videos are scored (a day old, with a view count); {minN} are needed before a trait is called better or worse. Views are checked when a cycle runs, so this fills in with cycles.
          </p>
        </Card>
      )}
      <div className="mb-2 text-xs text-neutral-500">Measure</div>
      <p className="mb-3 flex flex-wrap gap-2 text-sm">
        {Object.entries(f.outcomes ?? {}).map(([k, label]) => (
          <Link key={k} href={`/findings?outcome=${k}${niche ? `&niche=${niche}` : ""}`} title={label} className={`rounded border px-2 py-1 ${k === outcome ? "border-neutral-300 text-white" : "border-neutral-700 text-neutral-400 hover:text-white"}`}>{outcomeText[k] ?? label}</Link>
        ))}
      </p>
      <div className="mb-2 text-xs text-neutral-500">Videos from</div>
      <p className="mb-4 flex flex-wrap gap-2 text-sm">
        <Link href={`/findings?outcome=${outcome}`} className={`rounded border px-2 py-1 ${!niche ? "border-neutral-300 text-white" : "border-neutral-700 text-neutral-400"}`}>all niches</Link>
        {Object.entries(st.niches ?? {}).map(([n, c]) => (
          <Link key={n} href={`/findings?outcome=${outcome}&niche=${n}`} className={`rounded border px-2 py-1 ${niche === n ? "border-neutral-300 text-white" : "border-neutral-700 text-neutral-400"}`}>{n} only ({c})</Link>
        ))}
      </p>
      {fitted.length > 0 && (
        <Note className="mb-3">
          Numbers are on a log10 scale: +0.30 after controls is about 2x the views of the baseline value, +1.00 about 10x. &quot;Likely range&quot; is the 95% interval; if it crosses zero there is no clear difference.
        </Note>
      )}
      {fitted.map(([trait, fit]) => (
        <Card key={trait} title={`${human(trait)} · ${fit.n} videos`} className="mb-4">
          <Levels levels={fit.levels} minN={minN} />
        </Card>
      ))}
      {empty.length > 0 && (
        <Card className="mb-4">
          <p className="text-sm text-neutral-400">Not enough 3-day-old videos to compare yet: {empty.map(human).join(", ")}.</p>
        </Card>
      )}
      {Object.keys(fits).length === 0 && <p className="text-sm text-neutral-500">No analysis stored yet. Start a run cycle or choose &quot;Check post performance&quot; to refresh it.</p>}
    </>
  );
}
