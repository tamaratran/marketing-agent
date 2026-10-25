import { fmt, get, type Findings, type Level } from "@/lib/api";
import { Card, H1, Pill, Stat, Table } from "../ui";
import { RefreshButtons } from "../refresh";

export const dynamic = "force-dynamic";

const tone = (v: string) => (v === "better" ? "good" : v === "worse" ? "bad" : v === "thin" ? "warn" : "neutral");

function Levels({ levels, minN }: { levels: Level[]; minN: number }) {
  return (
    <Table
      head={["level", "n", "raw mean", "controlled", "95% interval", "verdict"]}
      rows={levels.map((l) => [
        l.level,
        l.n < minN ? <span key="n" className="text-amber-300">{l.n}</span> : l.n,
        fmt(l.raw_mean),
        l.reference ? "reference" : (l.coef > 0 ? "+" : "") + fmt(l.coef),
        l.reference ? "" : `${fmt(l.lo)} to ${fmt(l.hi)}`,
        <span key="v" className="flex gap-1"><Pill tone={tone(l.verdict)}>{l.verdict}</Pill>{l.travels && <Pill tone="good">travels across niches</Pill>}</span>,
      ])}
    />
  );
}

export default async function Page({ searchParams }: { searchParams: Promise<{ outcome?: string; niche?: string }> }) {
  const sp = await searchParams;
  const f = await get<Findings>("/findings");
  const outcome = sp.outcome && f.fits[sp.outcome] ? sp.outcome : "lift_72h";
  const niche = sp.niche;
  const fits = f.fits[outcome] ? (niche ? f.fits[outcome].per_niche[niche] ?? {} : f.fits[outcome].pooled) : {};
  const st = f.status;
  const minN = f.min_n ?? 20;
  return (
    <>
      <H1 sub="What videos that beat their creator's baseline have in common, with account size, niche, length and posting hour held fixed. Raw and controlled shown side by side; nothing under the minimum n is a finding.">Findings</H1>
      <div className="mb-4"><RefreshButtons /></div>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-6">
        <Stat label="cohort videos" value={st.videos} />
        <Stat label="tagged" value={st.tagged ?? 0} />
        <Stat label="with creator baseline" value={st.with_baseline ?? 0} />
        <Stat label="reached 24h" value={st.reached["24h"] ?? 0} />
        <Stat label="reached 72h" value={st.reached["72h"] ?? 0} />
        <Stat label="minimum n per cell" value={minN} />
      </div>
      {f.collecting && (
        <Card className="mb-4">
          <p className="text-sm text-amber-200">
            Collecting. {st.reached["72h"] ?? 0} of {st.videos} cohort videos have reached 72h; findings need at least {minN} per cell before anything is called better or worse.
            {st.eta_72h ? ` The first videos reach 72h around ${new Date(st.eta_72h * 1000).toUTCString()}.` : ""} Tables below are shown for transparency and are all thin.
          </p>
        </Card>
      )}
      <p className="mb-4 flex flex-wrap gap-2 text-sm">
        {Object.entries(f.outcomes ?? {}).map(([k, label]) => (
          <a key={k} href={`/findings?outcome=${k}${niche ? `&niche=${niche}` : ""}`} className={`rounded border px-2 py-1 ${k === outcome ? "border-neutral-300 text-white" : "border-neutral-700 text-neutral-400 hover:text-white"}`}>{label}</a>
        ))}
        <span className="mx-2 text-neutral-600">|</span>
        <a href={`/findings?outcome=${outcome}`} className={`rounded border px-2 py-1 ${!niche ? "border-neutral-300 text-white" : "border-neutral-700 text-neutral-400"}`}>pooled (niche as control)</a>
        {Object.keys(st.niches ?? {}).map((n) => (
          <a key={n} href={`/findings?outcome=${outcome}&niche=${n}`} className={`rounded border px-2 py-1 ${niche === n ? "border-neutral-300 text-white" : "border-neutral-700 text-neutral-400"}`}>{n} only</a>
        ))}
      </p>
      {Object.entries(fits).map(([trait, fit]) => (
        <Card key={trait} title={`${trait.replaceAll("_", " ")} · n=${fit.n}${fit.r2 != null ? ` · r²=${fit.r2}` : ""}`} className="mb-4">
          {fit.levels?.length ? <Levels levels={fit.levels} minN={minN} /> : <p className="text-sm text-neutral-500">Not enough rows to fit.</p>}
        </Card>
      ))}
      {Object.keys(fits).length === 0 && <p className="text-sm text-neutral-500">No analysis stored yet. The 2-hourly repoll and the daily run both refresh it.</p>}
    </>
  );
}
