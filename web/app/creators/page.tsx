import { get, type Creator } from "@/lib/api";
import { addCreator, addPost } from "../actions";
import { button, Card, H1, input, Pill, Table } from "../ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const rows = await get<Creator[]>("/creators");
  return (
    <>
      <H1 sub="Humans posting from their own US accounts. Nothing here messages anyone.">Creators</H1>
      <Table
        head={["handle", "channel", "$ per 1k", "posts", "median views", "last post", "status"]}
        rows={rows.map((c) => [
          `@${c.handle}`, c.channel, c.rate_per_1k.toFixed(2), c.posts, c.median_views ?? "", c.last_post ?? "",
          <Pill key="s" tone={c.status === "active" ? "good" : c.status === "stalled" ? "warn" : "neutral"}>{c.status}</Pill>,
        ])}
      />
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Card title="Add a creator">
          <form action={addCreator} className="flex flex-wrap gap-2">
            <input name="handle" required placeholder="@handle" className={input} />
            <select name="channel" className={input} defaultValue="discord"><option>discord</option><option>sideshift</option><option>email</option><option>dm</option></select>
            <input name="rate_per_1k" type="number" step="0.1" defaultValue={1} className={`${input} w-24`} title="$ per 1k views" />
            <input name="followers" type="number" placeholder="followers" className={`${input} w-28`} />
            <input name="notes" placeholder="notes" className={`${input} flex-1`} />
            <button className={button}>Add</button>
          </form>
        </Card>
        <Card title="Log a post">
          <form action={addPost} className="flex flex-wrap gap-2">
            <input name="creator" required placeholder="@handle" className={input} />
            <input name="url" required placeholder="https://www.tiktok.com/@.../video/..." className={`${input} flex-1`} />
            <input name="brief_id" type="number" placeholder="brief #" className={`${input} w-24`} />
            <input name="script_id" type="number" placeholder="script #" className={`${input} w-24`} />
            <button className={button}>Log</button>
          </form>
          <p className="mt-2 text-xs text-neutral-500">Views are polled from the public page; payout accrues at the creator&apos;s rate and settles at day 7.</p>
        </Card>
      </div>
    </>
  );
}
