import Link from "next/link";
import { CLIPS, dateOf, get, usd, type Render, type Script, frameUrl } from "@/lib/api";
import type { Ours } from "@/lib/ours";
import { Download } from "../download";
import { Card, H1, Note, Pill, formatName } from "../ui";
import { holdClip, postClip, releaseClip } from "../actions";
import { PostButton } from "../post-button";

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
      <H1 sub={`AI preview clips (Seedance) of the best scripts. The preview has the text burned in; the file to post is the clean one, with the text added in TikTok. Press Post on a clip you approve and Devin posts it${account ? ` from @${account}` : ""}; nothing is posted without that press.`}>Clips</H1>
      <Note className="mb-4">
        Post uploads the clean clip through TikTok&apos;s own web uploader, adds the lines under &quot;text to add&quot; with TikTok&apos;s text tool (TikTok reads its own text; text baked into the pixels is just picture to it), picks the listed sound, and registers the post so its views count toward that format. TikTok decides its own AI-generated label. To post by hand instead, download the clean clip and do the same.
      </Note>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {rows.map((r) => {
          const s = byId.get(r.script_id), p = posts.get(r.script_id), src = `${CLIPS}/s${r.script_id}.mp4`, clean = r.post_path ? `${CLIPS}/s${r.script_id}_clean.mp4` : null;
          return (
            <Card key={r.id}>
              <div id={`s${r.script_id}`} className="scroll-mt-4" />
              <video poster={frameUrl(`s${r.script_id}`)} controls preload="metadata" className="aspect-[9/16] w-full rounded bg-black" src={src} />
              <div className="mt-2 flex items-center gap-2">
                {p ? <a href={p.url} target="_blank"><Pill tone="good">posted</Pill></a> : r.hold_reason ? <Pill tone="bad">on hold</Pill> : r.post_session_url ? <a href={r.post_session_url} target="_blank"><Pill tone="neutral">posting...</Pill></a> : <Pill tone="warn">ready to post</Pill>}
                {clean ? <Download src={clean} className="text-xs text-sky-300 hover:underline">download clean clip to post</Download> : <Download src={src} className="text-xs text-sky-300 hover:underline">download</Download>}
              </div>
              {!p && !r.hold_reason && clean && !r.post_session_url && <PostButton action={postClip} scriptId={r.script_id} account={account} />}
              {!p && r.post_session_url && <p className="mt-2 text-xs text-neutral-400">Devin is posting this from @{account}: <a href={r.post_session_url} target="_blank" className="text-sky-300 hover:underline">watch</a>. It shows as posted once the post is found on the profile.</p>}
              {r.hold_reason && <p className="mt-2 text-xs text-red-200">{r.hold_reason}</p>}
              {!p && (r.hold_reason ? (
                <form action={releaseClip} className="mt-2"><input type="hidden" name="script_id" value={r.script_id} /><button className="text-xs text-neutral-400 hover:text-neutral-100">Release</button></form>
              ) : (
                <form action={holdClip} className="mt-2 flex gap-1"><input type="hidden" name="script_id" value={r.script_id} /><input name="reason" required placeholder="why hold it" className="min-w-0 flex-1 rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs" /><button className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:bg-neutral-800">Hold</button></form>
              ))}
              {clean && r.post_text.length ? (
                <div className="mt-2 rounded border border-neutral-800 p-2">
                  <p className="text-[11px] uppercase tracking-wide text-neutral-500">text to add in TikTok</p>
                  {r.post_text.map((ln, i) => <p key={i} className="text-sm font-medium">{ln}</p>)}
                </div>
              ) : (
                <p className="mt-2 text-sm font-medium">{r.hook}</p>
              )}
              {clean && <p className="mt-1 text-[11px] text-neutral-500">preview above has the text burned in; the clean clip has none</p>}
              {s?.concept && <p className="text-xs text-neutral-400">format: {formatName(s.concept)}</p>}
              <p className="text-xs text-neutral-400">sound: {s?.sound ? (s.sound_url ? <a className="underline" href={s.sound_url} target="_blank">{s.sound}</a> : s.sound) : <span className="text-neutral-600">none picked, use a trending one</span>}</p>
              <p className="mt-1 text-xs text-neutral-500"><Link href="/scripts" className="hover:underline">script #{r.script_id}</Link> · {dateOf(r.created_at)} · {usd(r.cost_usd)}</p>
            </Card>
          );
        })}
        {!rows.length && <p className="text-sm text-neutral-500">No clips yet. The daily run renders the best scripts.</p>}
      </div>
    </>
  );
}
