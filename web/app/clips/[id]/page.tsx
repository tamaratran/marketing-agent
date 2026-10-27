import Link from "next/link";
import { notFound } from "next/navigation";
import { CLIPS, dateOf, get, usd, frameUrl, type Overview, type Render, type Script, type VideoDetail } from "@/lib/api";
import type { Ours } from "@/lib/ours";
import { Download } from "../../download";
import { Card, Pill, Stat, formatName, ghost, times } from "../../ui";
import { postClip, releaseClip } from "../../actions";
import { PostButton } from "../../post-button";
import { MIN_AGE_H_OWN, WhyBlock, explain } from "../why";
import { LabelsBlock } from "../labels";
import { MAX_POST_ATTEMPTS, age, gaveUp, hoursSince, statusOf, tone, views } from "../status";

export const dynamic = "force-dynamic";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const scriptId = Number(id);
  if (!Number.isInteger(scriptId)) notFound();
  const [all, scripts, ours, overview] = await Promise.all([
    get<Render[]>("/renders"), get<Script[]>("/scripts?days=60&limit=500"), get<Ours>("/ours"), get<Overview>("/overview"),
  ]);
  const r = all.find((x) => x.script_id === scriptId);
  if (!r) notFound();
  const s = scripts.find((x) => x.id === scriptId);
  const p = ours.posts.find((x) => x.script_id === scriptId);
  const detail = p ? await get<VideoDetail>(`/videos/${p.id}`).catch(() => null) : null;
  const account = ours.accounts[0]?.handle;
  const st = statusOf(r, !!p);
  const src = `${CLIPS}/s${scriptId}.mp4`, clean = r.post_path ? `${CLIPS}/s${scriptId}_clean.mp4` : null;
  const early = !!p && p.age_h < MIN_AGE_H_OWN;
  const canPost = !p && !r.hold_reason && !!clean && (!r.post_session_url || gaveUp(r));
  const watch = (label: string) => r.post_session_url && <a href={r.post_session_url} target="_blank" className="text-gold hover:underline">{label}</a>;

  return (
    <>
      <p className="mb-8 text-sm"><Link href="/clips" className={ghost}>All clips</Link></p>
      <div className="grid gap-8 sm:grid-cols-[240px_minmax(0,1fr)] sm:gap-12">
        <video poster={frameUrl(`s${scriptId}`)} controls preload="none" className="aspect-[9/16] w-full max-w-[240px] rounded-sm bg-black" src={src} />
        <div className="min-w-0">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight text-neutral-50">{r.hook}</h1>
          <p className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm text-neutral-400">
            <Pill tone={tone(st)}>{st}</Pill>
            <span>s{scriptId}</span>
            {s?.concept && <span>{formatName(s.concept)}</span>}
            <span>rendered {dateOf(r.created_at)}</span>
            <span>{usd(r.cost_usd)}</span>
          </p>

          {p && (
            <>
              <div className="mt-10 grid grid-cols-2 gap-6 sm:grid-cols-4">
                <Stat label={`views, ${age(p.age_h)} up`} value={views(p.views_now) || "0"} />
                <Stat
                  label="vs videos like it"
                  value={early ? "too early" : p.lift_matched != null ? times(p.lift_matched) : "–"}
                  hint={early ? `judged at ${MIN_AGE_H_OWN}h` : p.lift_matched == null ? (p.views_now ? "no reference videos yet" : "no views yet") : undefined}
                />
                <Stat
                  label="shares+saves per 1k"
                  value={p.engagement_per_1k ?? "–"}
                  hint={p.engagement_lift != null ? `${p.engagement_lift > 0 ? "+" : ""}${p.engagement_lift.toFixed(2)} vs the niche` : undefined}
                />
                <Stat label="views at 3 days" value={p.views_72h ? views(Math.round(p.views_72h)) : "–"} />
              </div>
              <p className="mt-4 text-xs text-neutral-500">
                <a href={p.url} target="_blank" className="text-gold hover:underline">on TikTok</a> · posted {dateOf(p.create_time)} ·{" "}
                <Link href={`/videos/${p.id}`} className="hover:underline">view history, {p.n_obs} polls</Link>
              </p>
              <WhyBlock why={explain(p, detail, overview)} />
            </>
          )}

          {!p && st === "posting" && (
            <p className="mt-8 text-sm text-neutral-400">
              Devin is posting this from @{account}{r.post_attempts > 1 ? `, try ${r.post_attempts} of ${MAX_POST_ATTEMPTS}` : ""}: {watch("watch")}
            </p>
          )}
          {!p && st === "waiting" && (
            <p className="mt-8 text-sm text-neutral-400">
              No post after try {r.post_attempts} of {MAX_POST_ATTEMPTS} (TikTok login, most likely); handed back within 30 min: {watch("see why")}
            </p>
          )}
          {!p && gaveUp(r) && (
            <p className="mt-8 text-sm text-neutral-400">Gave up after {MAX_POST_ATTEMPTS} tries over {hoursSince(r.post_requested_at)}h: {watch("see why")}</p>
          )}
          {canPost && <div className="mt-8"><PostButton action={postClip} scriptId={scriptId} account={account} /></div>}
          {!p && r.hold_reason && (
            <Card title="On hold">
              <p className="text-neutral-200">{r.hold_reason}</p>
              <form action={releaseClip} className="mt-3">
                <input type="hidden" name="script_id" value={scriptId} />
                <button className={ghost}>Release</button>
              </form>
            </Card>
          )}

          {clean && r.post_text.length > 0 && (
            <Card title="Text added in TikTok">
              {r.post_text.map((ln, i) => <p key={i} className="font-medium text-neutral-100">{ln}</p>)}
            </Card>
          )}

          <LabelsBlock labels={r.labels} />

          <Card title="Script and sound">
            <p className="text-sm text-neutral-400">
              sound: {s?.sound ? (s.sound_url ? <a className="underline" href={s.sound_url} target="_blank">{s.sound}</a> : s.sound) : <span className="text-neutral-600">none picked</span>}
            </p>
            <p className="mt-1 text-sm text-neutral-500">
              <Link href={`/learnings#s${scriptId}`} className="hover:underline">script #{scriptId} and why it was written</Link> ·{" "}
              {clean ? <Download src={clean} className="text-gold hover:underline">clean clip</Download> : <Download src={src} className="text-gold hover:underline">download</Download>}
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}
