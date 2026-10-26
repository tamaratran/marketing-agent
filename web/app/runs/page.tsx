import { dateOf, get, type Overview, type Run } from "@/lib/api";
import { startRun } from "../actions";
import { button, Card, H1, Note, Table } from "../ui";
import { RefreshButtons } from "../refresh";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [rows, o] = await Promise.all([get<Run[]>("/runs"), get<Overview>("/overview")]);
  return (
    <>
      <H1 sub="A cycle is one pass of the loop, done by a Devin session on demand: re-read the product's best TikToks and how our own posts did, write better scripts, render the clips and put them on Clips with caption and sound, ready for a human to post. Nothing runs on a schedule and nothing is posted automatically.">Runs</H1>
      <Card title="Run a cycle" className="mb-5">
        <form action={startRun} className="flex flex-wrap items-center gap-3">
          <button className={button}>Run cycle</button>
          <Note>About 30 to 60 minutes. Renders {o.niche} clips for the configured product (see Ours). Costs a Devin session (capped at 10 ACUs) plus fal: about $5.70 per 12s clip at 720p, 5 clips per cycle.</Note>
        </form>
      </Card>
      <Card title="Refresh without a full run" className="mb-5">
        <RefreshButtons />
      </Card>
      <Card title="Runs started here">
        <Table
          head={["started", "niche", "product", "session", "note"]}
          rows={rows.map((r) => [dateOf(r.created_at), r.niche, r.product, <a key="u" href={r.url} target="_blank" className="text-sky-300 hover:underline">{r.session_id}</a>, r.note])}
          empty="None yet. Cycles started from the CLI are listed too; their results show up on the other pages."
        />
      </Card>
    </>
  );
}
