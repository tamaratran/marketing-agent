import { get, usd, type Payout } from "@/lib/api";
import { markPaid } from "../actions";
import { ghost, H1, Pill, Table } from "../ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const rows = await get<Payout[]>("/payouts");
  const owed = rows.reduce((a, p) => a + p.owed_usd - p.paid_usd, 0);
  return (
    <>
      <H1 sub={`Pay per 1k views, settled at day 7. Open: ${usd(owed)}. Marking paid records it; the transfer itself is manual.`}>Payouts</H1>
      <Table
        head={["creator", "post", "age", "views", "$ per 1k", "owed", "paid", "", ""]}
        rows={rows.map((p) => [
          `@${p.creator}`,
          <a key="u" href={p.url} target="_blank" className="text-sky-300 hover:underline">{p.video_id}</a>,
          `${p.age_days.toFixed(1)}d`, p.views.toLocaleString(), p.rate_per_1k.toFixed(2), usd(p.owed_usd), usd(p.paid_usd),
          <Pill key="s" tone={p.paid_usd >= p.owed_usd && p.owed_usd > 0 ? "good" : p.settled ? "warn" : "neutral"}>{p.paid_usd >= p.owed_usd && p.owed_usd > 0 ? "paid" : p.settled ? "due" : "accruing"}</Pill>,
          p.owed_usd > p.paid_usd ? (
            <form key="f" action={markPaid.bind(null, p.video_id, +(p.owed_usd - p.paid_usd).toFixed(2), p.views)}><button className={ghost}>Mark {usd(p.owed_usd - p.paid_usd)} paid</button></form>
          ) : "",
        ])}
      />
    </>
  );
}
