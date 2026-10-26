import { API, get, type Learning } from "@/lib/api";
import { Markdown } from "../md";
import { Card, H1, Note, Pill, formatName } from "../ui";

export const dynamic = "force-dynamic";

const when = (ts: number) => new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC";

export default async function Page() {
  const rows = await get<Learning[]>("/learnings?limit=100");
  return (
    <>
      <H1 sub="What the agent has learned, in its own words, newest first. Every cycle writes one entry from measurements (what the source videos do, what the picker leaned on, how our posts did against the market, what changed), and the session running the cycle adds what it noticed and fixed.">Learnings</H1>
      <Note className="mb-4">
        The same text as one file: <a href={`${API}/learnings.md`} className="text-sky-300 hover:underline" target="_blank">learnings.md</a>
      </Note>
      {rows.length === 0 && <Card><Note>Nothing yet. The first cycle writes the first entry.</Note></Card>}
      <div className="space-y-4">
        {rows.map((e) => (
          <Card key={e.id}>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="font-semibold text-neutral-100">{e.title}</span>
              <Pill tone={e.kind === "cycle" ? "neutral" : "good"}>{e.kind === "cycle" ? "measured" : "observation"}</Pill>
              <span className="text-xs text-neutral-500">{when(e.created_at)} · {e.niche}</span>
            </div>
            <Markdown text={formatName(e.body)} />
          </Card>
        ))}
      </div>
    </>
  );
}
