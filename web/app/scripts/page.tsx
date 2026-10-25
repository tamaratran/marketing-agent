import { dateOf, get, type Script } from "@/lib/api";
import { Card, H1, Pill } from "../ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const rows = await get<Script[]>("/scripts?days=14&limit=60");
  return (
    <>
      <H1 sub="Product remixes of the picked concept, last 14 days. Demo score is how well the product can be shown in the first 5 seconds.">Scripts</H1>
      <div className="grid gap-3 md:grid-cols-2">
        {rows.map((s) => (
          <Card key={s.id}>
            <div className="mb-1 flex items-center gap-2 text-xs text-neutral-500">
              <span>#{s.id}</span><span>{dateOf(s.created_at)}</span><Pill>{s.concept}</Pill>
              <Pill tone={s.demo_score >= 4 ? "good" : "warn"}>demo {s.demo_score}/5</Pill>
            </div>
            <p className="font-medium">{s.hook}</p>
            <p className="mt-1 text-sm text-neutral-400">{s.captions?.join(" / ")}</p>
            <details className="mt-2 text-sm text-neutral-400"><summary className="cursor-pointer text-xs text-neutral-500">shot list</summary><p className="mt-1 whitespace-pre-wrap">{s.body}</p></details>
          </Card>
        ))}
        {!rows.length && <p className="text-sm text-neutral-500">No scripts in the last 14 days.</p>}
      </div>
    </>
  );
}
