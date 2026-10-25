import { API, dateOf, get, usd, type Render } from "@/lib/api";
import { Card, H1 } from "../ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const rows = await get<Render[]>("/renders");
  return (
    <>
      <H1 sub="Seedance previews of kept scripts, captions burned in. These are for exploring formats; creators film the real ones.">Clips</H1>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {rows.map((r) => (
          <Card key={r.id}>
            <video controls preload="metadata" className="aspect-[9/16] w-full rounded bg-black" src={`${API}/renders/${r.id}/file`} />
            <p className="mt-2 text-sm font-medium">{r.hook}</p>
            <p className="text-xs text-neutral-500">script #{r.script_id} · {dateOf(r.created_at)} · {usd(r.cost_usd)} · {r.model.split("/").slice(0, 2).join("/")}</p>
          </Card>
        ))}
        {!rows.length && <p className="text-sm text-neutral-500">No clips yet.</p>}
      </div>
    </>
  );
}
