import { dateOf, get, type Brief } from "@/lib/api";
import { setBriefStatus } from "../actions";
import { Card, ghost, H1, Pill } from "../ui";

export const dynamic = "force-dynamic";

const tone = (s: string) => (s === "approved" ? "good" : s === "posted" ? "neutral" : s === "closed" ? "neutral" : "warn") as "good" | "neutral" | "warn";

export default async function Page() {
  const rows = await get<Brief[]>("/briefs");
  return (
    <>
      <H1 sub="Drafted from the kept scripts. Approving records your decision; sending it to creators is still on you.">Briefs</H1>
      <div className="space-y-3">
        {rows.map((b) => (
          <Card key={b.id}>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <b>Brief #{b.id}</b>
              <span className="text-neutral-500">{dateOf(b.created_at)}</span>
              <Pill tone={tone(b.status)}>{b.status}</Pill>
              <span className="text-neutral-400">${b.rate_per_1k}/1k, cap ${b.cap_usd}, {b.deadline_days} days, scripts {b.script_ids}</span>
              <span className="ml-auto flex gap-1">
                {b.status === "draft" && <form action={setBriefStatus.bind(null, b.id, "approved")}><button className={ghost}>Approve</button></form>}
                {b.status === "approved" && <form action={setBriefStatus.bind(null, b.id, "posted")}><button className={ghost}>Mark posted</button></form>}
                {b.status !== "closed" && <form action={setBriefStatus.bind(null, b.id, "closed")}><button className={ghost}>Close</button></form>}
              </span>
            </div>
            <details className="mt-2"><summary className="cursor-pointer text-xs text-neutral-500">brief text</summary>
              <pre className="mt-2 whitespace-pre-wrap text-sm text-neutral-300">{b.body}</pre></details>
          </Card>
        ))}
        {!rows.length && <p className="text-sm text-neutral-500">No briefs yet.</p>}
      </div>
    </>
  );
}
