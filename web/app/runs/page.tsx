import { dateOf, get, type Run } from "@/lib/api";
import { startRun } from "../actions";
import { button, Card, H1, input, Table } from "../ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const rows = await get<Run[]>("/runs");
  return (
    <>
      <H1 sub="Each run is a Devin session that scrapes, classifies, picks a concept, writes scripts, renders, polls creator posts and pushes state. The cron does one a day; this starts an extra one.">Runs</H1>
      <Card title="Start a run" className="mb-5">
        <form action={startRun} className="flex flex-wrap gap-2">
          <input name="niche" defaultValue="wearables" className={`${input} w-28`} />
          <input name="tags" defaultValue="smartring whoop ouraring" className={`${input} w-56`} title="hashtags" />
          <input name="product" required defaultValue="a smart ring that tracks sleep, stress and recovery" className={`${input} flex-1`} />
          <input name="renders" type="number" min={0} max={3} defaultValue={1} className={`${input} w-20`} title="clips to render" />
          <button className={button}>Start</button>
        </form>
        <p className="mt-2 text-xs text-neutral-500">Costs a Devin session (capped at 10 ACUs) plus about $2.65 of fal per clip.</p>
      </Card>
      <Table
        head={["started", "niche", "product", "session", "note"]}
        rows={rows.map((r) => [dateOf(r.created_at), r.niche, r.product, <a key="u" href={r.url} target="_blank" className="text-sky-300 hover:underline">{r.session_id}</a>, r.note])}
      />
    </>
  );
}
