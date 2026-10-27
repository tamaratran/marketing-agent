import Link from "next/link";
import { CLIPS, dateOf, get, usd, type Overview, type Render, type Script, type VideoDetail, frameUrl } from "@/lib/api";
import type { Ours, OursPost } from "@/lib/ours";
import { Download } from "../download";
import { Card, Fold, H1, Pill, Stat, Table, reward, formatName } from "../ui";
import { Thumb } from "../thumb";
import { postClip, releaseClip } from "../actions";
import { MIN_AGE_H_OWN, WhyFold, explain } from "./why";
import { PostButton } from "../post-button";

export const dynamic = "force-dynamic";

const views = (n: number | null | undefined) => (n == null ? "" : n.toLocaleString("en-US"));
const POST_RETRY_AFTER_S = 3600;
const MAX_POST_ATTEMPTS = 4;
const hoursSince = (t: number | null) => Math.round((Date.now() / 1000 - (t ?? 0)) / 3600);
const stale = (r: Render) => !!r.post_session_url && hoursSince(r.post_requested_at) >= POST_RETRY_AFTER_S / 3600;
const gaveUp = (r: Render) => stale(r) && (r.post_attempts ?? 0) >= MAX_POST_ATTEMPTS;

export default async function Page() {
  const [all, scripts, ours, overview] = await Promise.all([
    get<Render[]>("/renders"), get<Script[]>("/scripts?days=60&limit=500"), get<Ours>("/ours"), get<Overview>("/overview"),
  ]);
  const details = new Map(await Promise.all(ours.posts.map(async (p) => [p.id, await get<VideoDetail>(`/videos/${p.id}`).catch(() => null)] as const)));
  const seen = new Set<number>();
  const rows = all.filter((r) => !seen.has(r.script_id) && seen.add(r.script_id));
  const byId = new Map(scripts.map((s) => [s.id, s]));
  const posts = new Map(ours.posts.filter((p) => p.script_id).map((p) => [p.script_id as number, p]));
  const account = ours.accounts[0]?.handle;
  const posted = rows.filter((r) => posts.has(r.script_id)).length;
  const held = rows.filter((r) => r.hold_reason && !posts.has(r.script_id)).length;
  const measured = ours.posts.filter((p) => p.age_h >= MIN_AGE_H_OWN && p.lift_matched != null);
  const beat = measured.filter((p) => (p.lift_matched ?? 0) > 0).length;
  const unmatched = ours.posts.filter((p) => !p.script_id);
  return (
    <>
      <H1 sub={account ? `Each clip, whether it is on @${account}, and how it is doing.` : "Each clip and how it is doing."}>Clips</H1>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="clips" value={rows.length} />
        <Stat label="posted" value={posted} />
        <Stat label="on hold" value={held} />
        <Stat label="ahead of videos like them" value={measured.length ? `${beat} of ${measured.length}` : "none measured yet"} />
      </div>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {rows.map((r) => {
          const s = byId.get(r.script_id), p = posts.get(r.script_id);
          const src = `${CLIPS}/s${r.script_id}.mp4`, clean = r.post_path ? `${CLIPS}/s${r.script_id}_clean.mp4` : null;
          return (
            <li key={r.id} id={`s${r.script_id}`} className="flex scroll-mt-4 flex-col overflow-hidden rounded-xl border border-neutral-800 bg-neutral-950">
              <video poster={frameUrl(`s${r.script_id}`)} controls preload="none" className="aspect-[9/16] w-full bg-black" src={src} />
              <div className="flex flex-1 flex-col p-3 text-sm">
                <p className="font-medium leading-snug text-neutral-100">{r.hook}</p>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                  {p ? <Pill tone="good">posted</Pill> : r.hold_reason ? <Pill tone="bad">on hold</Pill> : r.post_session_url && !stale(r) ? <Pill tone="neutral">posting</Pill> : r.post_session_url && !gaveUp(r) ? <Pill tone="neutral">waiting</Pill> : r.post_path ? <Pill tone="neutral">ready</Pill> : null}
                  {p && (
                    <>
                      <span className="tabular-nums text-neutral-100">{views(p.views_now)} <span className="text-neutral-500">views</span></span>
                      <span>{lift(p)}</span>
                      <span className="text-neutral-500">{p.age_h < 48 ? `${Math.round(p.age_h)}h` : `${Math.round(p.age_h / 24)}d`} up</span>
                    </>
                  )}
                </div>
                <p className="mt-1.5 text-xs text-neutral-500">s{r.script_id}{s?.concept && <> · {formatName(s.concept)}</>} · {dateOf(r.created_at)}</p>
                {r.hold_reason && <p className="mt-2 text-xs text-neutral-500">{r.hold_reason}</p>}
                {!p && !r.hold_reason && clean && (!r.post_session_url || gaveUp(r)) && <div className="mt-3"><PostButton action={postClip} scriptId={r.script_id} account={account} /></div>}
                <Fold summary={<span className="text-xs text-neutral-400">{p ? "numbers, text and sound" : "text, sound and download"}</span>} className="mt-3">
                  <div className="min-w-0 text-sm">
              {p && <PostStats p={p} />}
              {p && <WhyFold why={explain(p, details.get(p.id) ?? null, overview)} />}
              {!p && r.post_session_url && !stale(r) && <p className="text-xs text-neutral-400">Devin is posting this from @{account}{r.post_attempts > 1 ? `, try ${r.post_attempts} of ${MAX_POST_ATTEMPTS}` : ""}: <a href={r.post_session_url} target="_blank" className="text-gold hover:underline">watch</a></p>}
              {!p && r.post_session_url && stale(r) && !gaveUp(r) && <p className="text-xs text-neutral-400">No post after try {r.post_attempts} of {MAX_POST_ATTEMPTS} (TikTok login, most likely); handed back within 30 min: <a href={r.post_session_url} target="_blank" className="text-gold hover:underline">see why</a></p>}
              {!p && gaveUp(r) && <p className="text-xs text-neutral-400">Gave up after {MAX_POST_ATTEMPTS} tries over {hoursSince(r.post_requested_at)}h: <a href={r.post_session_url ?? "#"} target="_blank" className="text-gold hover:underline">see why</a></p>}
              {!p && r.hold_reason && (
                <form action={releaseClip} className="mt-2"><input type="hidden" name="script_id" value={r.script_id} /><button className="text-xs text-neutral-400 hover:text-neutral-100">Release</button></form>
              )}
              {clean && r.post_text.length > 0 && (
                <div className="mt-3 rounded border border-neutral-800 p-2">
                  <p className="text-[11px] uppercase tracking-wide text-neutral-500">text to add in TikTok</p>
                  {r.post_text.map((ln, i) => <p key={i} className="font-medium">{ln}</p>)}
                </div>
              )}
              <p className="mt-3 text-xs text-neutral-400">
                {s?.concept && <>format: {formatName(s.concept)} · </>}
                sound: {s?.sound ? (s.sound_url ? <a className="underline" href={s.sound_url} target="_blank">{s.sound}</a> : s.sound) : <span className="text-neutral-600">none picked</span>}
              </p>
              <p className="mt-1 text-xs text-neutral-500">
                <Link href={`/learnings#s${r.script_id}`} className="hover:underline">script #{r.script_id}</Link> · {dateOf(r.created_at)} · {usd(r.cost_usd)} ·{" "}
                {clean ? <Download src={clean} className="text-gold hover:underline">clean clip</Download> : <Download src={src} className="text-gold hover:underline">download</Download>}
              </p>
                  </div>
                </Fold>
              </div>
            </li>
          );
        })}
        {!rows.length && <p className="text-sm text-neutral-500">No clips yet. Generate clips on Learnings renders the best scripts.</p>}
      </ul>

      {unmatched.length > 0 && (
        <Card title="Posts without a clip" className="mt-6">
          <Table head={["", "posted", "post", "views", "vs videos like it"]} rows={unmatched.map((p) => [
            <Thumb key={`t${p.id}`} id={p.id} href={`/videos/${p.id}`} />,
            dateOf(p.create_time),
            <Link key={p.id} href={`/videos/${p.id}`} className="text-gold hover:underline">{(p.desc || p.id).slice(0, 60)}</Link>,
            views(p.views_now),
            lift(p),
          ])} />
        </Card>
      )}

      {ours.accounts.length === 0 && <p className="mt-3 text-sm text-gold">No posting account yet: <code>mkt own login</code>, then <code>mkt own add @handle</code>.</p>}
    </>
  );
}

const lift = (p: OursPost) =>
  p.age_h < MIN_AGE_H_OWN
    ? <span key="early" className="text-neutral-500" title={`Posts under ${MIN_AGE_H_OWN} hours are noise and do not move the picker`}>too early, {p.age_h.toFixed(1)}h</span>
    : reward(p.lift_matched, p.views_now ? "no reference videos yet" : "no views yet", "videos like it");


function PostStats({ p }: { p: OursPost }) {
  return (
    <div className="mb-3">
      <p className="text-xs text-neutral-500">
        <a href={p.url} target="_blank" className="text-gold hover:underline">on TikTok</a> · posted {dateOf(p.create_time)} · <Link href={`/videos/${p.id}`} className="hover:underline">history, {p.n_obs} polls</Link>
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-2">
        <Figure label="views now" value={views(p.views_now) || "none yet"} />
        <Figure label="vs videos like it" value={lift(p)} />
        <Figure label="shares+saves per 1k" value={p.engagement_per_1k != null ? <>{p.engagement_per_1k}{p.engagement_lift != null && <span className="ml-1 text-xs text-neutral-500">{p.engagement_lift > 0 ? "+" : ""}{p.engagement_lift.toFixed(2)} vs niche</span>}</> : "none yet"} />
        <Figure label="views at 3 days" value={p.views_72h ? views(Math.round(p.views_72h)) : "not yet"} />
      </dl>
    </div>
  );
}

function Figure({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="border-t border-rule px-3 py-2">
      <dt className="text-xs text-neutral-500">{label}</dt>
      <dd className="mt-0.5 tabular-nums text-neutral-100">{value}</dd>
    </div>
  );
}
