import Link from "next/link";
import { CLIPS, dateOf, get, usd, type Render, type Script, frameUrl } from "@/lib/api";
import type { Ours } from "@/lib/ours";
import { Card, H1, Note, Pill } from "../ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [all, scripts, ours] = await Promise.all([get<Render[]>("/renders"), get<Script[]>("/scripts?days=60&limit=500"), get<Ours>("/ours")]);
  const seen = new Set<number>();
  const rows = all.filter((r) => !seen.has(r.script_id) && seen.add(r.script_id));
  const byId = new Map(scripts.map((s) => [s.id, s]));
  const posts = new Map(ours.posts.filter((p) => p.script_id).map((p) => [p.script_id as number, p]));
  const account = ours.accounts[0]?.handle;
  return (
    <>
      <H1 sub={`AI preview clips (Seedance) of the best scripts, captions burned in. A person posts them${account ? ` from @${account}` : ""}; nothing is posted automatically.`}>Clips</H1>
      <Note className="mb-4">
        To post one: download it, upload it to TikTok, and pick the sound listed under the clip in TikTok&apos;s sound library. The next sync matches the post to its script by caption, and its views start counting toward that concept.
      </Note>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {rows.map((r) => {
          const s = byId.get(r.script_id), p = posts.get(r.script_id), src = `${CLIPS}/s${r.script_id}.mp4`;
          return (
            <Card key={r.id}>
              <div id={`s${r.script_id}`} className="scroll-mt-4" />
              <video poster={frameUrl(`s${r.script_id}`)} controls preload="metadata" className="aspect-[9/16] w-full rounded bg-black" src={src} />
              <div className="mt-2 flex items-center gap-2">
                {p ? <a href={p.url} target="_blank"><Pill tone="good">posted</Pill></a> : <Pill tone="warn">ready to post</Pill>}
                <a href={src} download className="text-xs text-sky-300 hover:underline">download</a>
              </div>
              <p className="mt-2 text-sm font-medium">{r.hook}</p>
              {s?.concept && <p className="text-xs text-neutral-400">concept: {s.concept}</p>}
              {s?.sound && <p className="text-xs text-neutral-400">sound: {s.sound_url ? <a className="underline" href={s.sound_url} target="_blank">{s.sound}</a> : s.sound}</p>}
              <p className="mt-1 text-xs text-neutral-500"><Link href="/scripts" className="hover:underline">script #{r.script_id}</Link> · {dateOf(r.created_at)} · {usd(r.cost_usd)}</p>
            </Card>
          );
        })}
        {!rows.length && <p className="text-sm text-neutral-500">No clips yet. The daily run renders the best scripts.</p>}
      </div>
    </>
  );
}
