import { dateOf, get, type Overview, type Run } from "@/lib/api";
import type { Ours } from "@/lib/ours";
import { startRun } from "../actions";
import { button, Card, H1, input, Note, Table } from "../ui";
import { RefreshButtons } from "../refresh";

export const dynamic = "force-dynamic";

function Field({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={`flex flex-col gap-1 text-xs text-neutral-500 ${className}`}>
      {label}
      {children}
    </label>
  );
}

export default async function Page() {
  const [rows, o, ours] = await Promise.all([get<Run[]>("/runs"), get<Overview>("/overview"), get<Ours>("/ours")]);
  const tags = [...new Set(o.top_videos.map((v) => v.source_tag).filter(Boolean))].join(" ");
  const product = ours.accounts[0]?.product ?? "";
  return (
    <>
      <H1 sub="A run is one pass of the loop done by a Devin session: find new research videos, tag them, pick a concept, write scripts, render clips and check our posts. One runs automatically every morning; start an extra one here.">Runs</H1>
      <Card title="Start an extra run" className="mb-5">
        <form action={startRun} className="flex flex-wrap items-end gap-2">
          <Field label="Niche"><input name="niche" defaultValue={o.niche} className={`${input} w-28`} /></Field>
          <Field label="Hashtags to search"><input name="tags" defaultValue={tags} className={`${input} w-64`} /></Field>
          <Field label="Product to make videos for" className="min-w-64 flex-1"><input name="product" required defaultValue={product} className={input} /></Field>
          <Field label="Clips to render"><input name="renders" type="number" min={0} max={3} defaultValue={1} className={`${input} w-20`} /></Field>
          <button className={button}>Start</button>
        </form>
        <Note className="mt-2">Costs a Devin session (capped at 10 ACUs) plus about $2.65 of fal per clip.</Note>
      </Card>
      <Card title="Refresh without a full run" className="mb-5">
        <RefreshButtons />
      </Card>
      <Card title="Runs started here">
        <Table
          head={["started", "niche", "product", "session", "note"]}
          rows={rows.map((r) => [dateOf(r.created_at), r.niche, r.product, <a key="u" href={r.url} target="_blank" className="text-sky-300 hover:underline">{r.session_id}</a>, r.note])}
          empty="None yet. The daily automatic run is not listed here; its results show up on the other pages."
        />
      </Card>
    </>
  );
}
