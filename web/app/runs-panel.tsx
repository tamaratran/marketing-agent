/* eslint-disable @next/next/no-img-element */
import { dateOf, type Campaign, type Run, type RunStage } from "@/lib/api";
import { startRun } from "./actions";
import { button, Card, Note, Table } from "./ui";
import { RefreshButtons } from "./refresh";

/** The full cycle button, what a cycle works on, and every run started here. Lives in a fold on Learnings. */
export function RunsPanel({ rows, c }: { rows: Run[]; c: Campaign }) {
  const perClip = { "480p": 2.65, "720p": 5.7, "1080p": 9.6 }[c.cycle.resolution] ?? 5.7;
  return (
    <>
      <Card title="Run a cycle" className="mb-5">
        <form action={startRun} className="flex flex-wrap items-center gap-3">
          <button className={button}>Run cycle</button>
          <Note>About 30 to 60 minutes. Costs a Devin session (capped at {c.cycle.max_acu} ACUs) plus fal: about ${perClip.toFixed(2)} per 12s clip at {c.cycle.resolution}, {c.cycle.clips} clips per cycle.</Note>
        </form>
      </Card>
      <Card title="What a cycle works on" className="mb-5">
        <Note className="mb-3">From <code>campaign.toml</code> in the repo. To market something else, edit that file and merge; nothing on this page needs changing.</Note>
        <Table
          head={["", ""]}
          rows={[
            ["posting account", c.account.handle ? <a key="a" href={`https://www.tiktok.com/@${c.account.handle}`} target="_blank" className="text-gold hover:underline">@{c.account.handle}</a> : "none registered"],
            ["niche watched", `${c.niche.name}: ${c.niche.hashtags.map((t) => `#${t}`).join(" ")}`],
            ["product", <span key="p">{c.product.name}{c.product.developer ? ` by ${c.product.developer}` : ""}{c.product.website ? <> · <a href={c.product.website} target="_blank" className="text-gold hover:underline">site</a></> : null}{c.product.app_store ? <> · <a href={c.product.app_store} target="_blank" className="text-gold hover:underline">App Store</a></> : null}</span>],
            ["how scripts describe it", c.product.description],
            ["TikToks whose format is cloned", c.product.hashtags.length ? c.product.hashtags.map((t) => `#${t}`).join(" ") : "none, niche concepts only"],
            ["reference images for renders", <span key="r" className="flex gap-2">{c.product.references.map((u) => <a key={u} href={u} target="_blank"><img src={u} alt="" className="h-14 rounded border border-neutral-800" /></a>)}</span>],
            ["per cycle", `${c.cycle.clips} clips at ${c.cycle.resolution}`],
          ]}
        />
      </Card>
      <Card title="Refresh without a full run" className="mb-5">
        <RefreshButtons />
      </Card>
      <Card title="Runs started here">
        <Note className="mb-3">Status comes from the cycle itself when it finishes. &quot;needs a human&quot; means a login, captcha or credit, not a code failure.</Note>
        <Table
          head={["started", "status", "stages", "session", "note"]}
          rows={rows.map((r) => {
            const stages: RunStage[] = r.stages ? JSON.parse(r.stages) : [];
            const bad = stages.filter((s) => s.status === "failed");
            const human = bad.filter((s) => /top-up|login|captcha|TikTok session|credit/i.test(s.note));
            const status = !r.finished_at ? "running" : human.length === bad.length && bad.length ? "needs a human" : r.status === "failed" ? "failed" : "done";
            const summary = stages.length ? `${stages.filter((s) => s.status === "ok").length}/${stages.length} ok` : "";
            return [
              dateOf(r.created_at),
              <span key="s" className={status === "done" ? "text-neutral-50" : status === "running" ? "text-neutral-400" : "text-gold"}>{status}</span>,
              <span key="g">
                {summary}
                {bad.length > 0 && (
                  <ul className="mt-1 list-disc pl-4 text-xs text-gold">
                    {bad.map((s) => <li key={s.stage} title={s.note}>{s.stage} failed</li>)}
                  </ul>
                )}
              </span>,
              r.url ? <a key="u" href={r.url} target="_blank" className="text-gold hover:underline">{r.session_id}</a> : "CLI",
              r.note,
            ];
          })}
          empty="None yet. Cycles started from the CLI are listed too; their results show up on the other pages."
        />
      </Card>
    </>
  );
}
