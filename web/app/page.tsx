import Link from "next/link";
import { CLIPS, frameUrl, get, usd, type Concept, type Findings, type Overview, type Render, type Script } from "@/lib/api";
import type { Ours } from "@/lib/ours";
import { startRun } from "./actions";
import { Download } from "./download";
import { Thumb } from "./thumb";
import { button, formatName, Pill, human, reward, times } from "./ui";

export const dynamic = "force-dynamic";

const STEPS = ["What's working", "The format", "The script", "The clip", "Post it", "How it went"];

type Q = { step?: string; clip?: string };

export default async function Page({ searchParams }: { searchParams: Promise<Q> }) {
  const q = await searchParams;
  const [o, concepts, scripts, renders, ours, fs] = await Promise.all([
    get<Overview>("/overview"), get<Concept[]>("/concepts"), get<Script[]>("/scripts?days=60&limit=500"),
    get<Render[]>("/renders"), get<Ours>("/ours"), get<Findings>("/findings"),
  ]);
  const step = Math.min(Math.max(Math.floor(Number(q.step)) || 1, 1), STEPS.length);
  const account = ours.accounts[0]?.handle;
  const posted = new Map(ours.posts.filter((p) => p.script_id).map((p) => [p.script_id as number, p]));
  const clips = renders.filter((r, i) => renders.findIndex((x) => x.script_id === r.script_id) === i);
  const clip = clips.find((r) => String(r.script_id) === q.clip)
    ?? clips.find((r) => !posted.has(r.script_id) && !r.hold_reason)
    ?? clips.find((r) => !r.hold_reason)
    ?? clips[0];
  const script = scripts.find((s) => s.id === clip?.script_id) ?? scripts[0];
  const concept = concepts.find((c) => c.name === script?.concept) ?? concepts[0];
  const scored = o.top_videos.filter((v) => v.reward != null && v.reward > 0);
  const top = [...scored, ...o.top_videos.filter((v) => v.reward == null)].slice(0, 3);
  const href = (n: number, c = clip?.script_id) => `/?step=${n}${c ? `&clip=${c}` : ""}`;

  return (
    <div className="mx-auto max-w-2xl">
      <ol className="mb-4 flex gap-1">
        {STEPS.map((s, i) => (
          <li key={s} className="flex-1">
            <Link href={href(i + 1)} className="block py-2" aria-label={`Step ${i + 1}: ${s}`}>
              <div className={`h-1 rounded ${i + 1 <= step ? "bg-neutral-100" : "bg-neutral-800"}`} />
              <div className={`mt-1 text-[11px] ${i + 1 === step ? "text-neutral-100" : "text-neutral-500"}`}><span className="sm:hidden">{i + 1}</span><span className="hidden sm:inline">{s}</span></div>
            </Link>
          </li>
        ))}
      </ol>

      <div className="text-xs text-neutral-500">Step {step} of {STEPS.length}</div>

      {step === 1 && (
        <Screen title="What's working on TikTok" lead={`We watch ${o.videos} recent ${o.niche} videos from other accounts and track their views. ${scored.length ? "These beat their creator's usual views by the most" : "None are old enough to compare yet"}${scored.length && top.length > scored.length ? ", plus the newest ones, which are too new to compare yet" : ""}.`}>
          <div className="space-y-3">
            {top.map((v) => (
              <a key={v.id} href={v.url} target="_blank" className="flex gap-3 rounded-lg border border-neutral-800 p-3 hover:border-neutral-600">
                <Thumb id={v.id} size={48} />
                <div className="min-w-0 text-sm">
                  <div className="truncate">{v.desc || v.id}</div>
                  <div className="mt-1 text-xs text-neutral-400">@{v.author} · {v.views.toLocaleString()} views · {reward(v.reward, "too new to compare")}</div>
                  <div className="mt-1 text-xs text-neutral-500">{human(v.hook_type)} hook, {human(v.visual_style)}</div>
                </div>
              </a>
            ))}
          </div>
          <Aside>{scored[0]?.reward != null && <>&quot;{times(scored[0].reward)} usual&quot; means {times(scored[0].reward).replace("x", "")} times the views that account normally gets. </>} These are other people&apos;s videos; we only learn from them.</Aside>
        </Screen>
      )}

      {step === 2 && concept && (
        <Screen title={formatName(concept.name)} lead="The agent groups videos like these into reusable formats. This is the format behind the clip you are about to see.">
          <p className="text-sm leading-relaxed text-neutral-300">{concept.description}</p>
          <div className="mt-5 text-xs text-neutral-500">Other formats it found</div>
          <ul className="mt-2 space-y-1 text-sm text-neutral-400">
            {concepts.filter((c) => c.id !== concept.id).slice(0, 4).map((c) => <li key={c.id}>{formatName(c.name)}</li>)}
          </ul>
          <Aside>Formats with more early views get picked more often. Once our own posts have results, the ones that work for us get picked more. <Link href="/how" className="text-sky-300 hover:underline">See how it decides</Link></Aside>
        </Screen>
      )}

      {step === 3 && script && (
        <Screen title="The script" lead={`Written for ${account ? `@${account}` : "our account"} in that format.`}>
          <Field label={script.hook_on_screen === false ? "Opening line (spoken)" : "Opening line (on screen)"}><span className="text-lg font-medium">{script.hook}</span></Field>
          {script.spoken && script.spoken !== script.hook && <Field label="What's said">{script.spoken}</Field>}
          {!!script.captions?.length && <Field label="Text on screen">{script.captions.join(" / ")}</Field>}
          <Field label="Shots"><p className="whitespace-pre-wrap text-sm text-neutral-400">{script.body}</p></Field>
          {clips.length > 1 && <Others clips={clips} current={clip?.script_id} step={3} posted={posted} />}
        </Screen>
      )}

      {step === 4 && (clip ? (
        <Screen title="The clip" lead="An AI preview of the script, captions included.">
          <video key={clip.script_id} poster={frameUrl(`s${clip.script_id}`)} controls playsInline preload="metadata" className="mx-auto aspect-[9/16] h-[55vh] max-h-[560px] rounded-lg bg-black" src={`${CLIPS}/s${clip.script_id}.mp4`} />
          <div className="mt-3 flex items-center justify-center gap-3 text-sm">
            {posted.has(clip.script_id) ? <Pill tone="good">already posted</Pill> : clip.hold_reason ? <Pill tone="bad">on hold</Pill> : <Pill tone="warn">not posted yet</Pill>}
            {clip.post_path ? <Download src={`${CLIPS}/s${clip.script_id}_clean.mp4`}>Download clean clip to post</Download> : <Download src={`${CLIPS}/s${clip.script_id}.mp4`} />}
          </div>
          {clip.hold_reason && <Aside>On hold, do not post this one: {clip.hold_reason}</Aside>}
          {clip.post_path && clip.post_text.length > 0 && (
            <div className="mx-auto mt-3 max-w-sm rounded border border-neutral-800 p-2 text-center">
              <p className="text-[11px] uppercase tracking-wide text-neutral-500">text to add in TikTok</p>
              {clip.post_text.map((ln, i) => <p key={i} className="text-sm font-medium">{ln}</p>)}
            </div>
          )}
          <p className="mt-3 text-center text-xs text-neutral-500">Every clip, with its text and sound: <Link href="/clips" className="text-sky-300 hover:underline">Clips</Link></p>
          {clips.length > 1 && <Others clips={clips} current={clip.script_id} step={4} posted={posted} />}
        </Screen>
      ) : (
        <Screen title="The clip" lead="No clips yet. Make some at the last step." />
      ))}

      {step === 5 && (
        <Screen title="Post it" lead={`Nothing is posted automatically. Post it yourself${account ? ` from @${account}` : ""}.`}>
          <ol className="space-y-3 text-sm text-neutral-300">
            {[
              <>Download the clip{clip ? <> (<Download src={`${CLIPS}/s${clip.script_id}${clip.post_path ? "_clean" : ""}.mp4`}>here</Download>)</> : null} and upload it in TikTok.</>,
              clip?.post_path && clip.post_text.length > 0 ? <>Add the text with TikTok&apos;s text tool, one line per card: {clip.post_text.map((ln, i) => <b key={i}>{i ? " / " : ""}{ln}</b>)}. The clip has no text burned in, so TikTok&apos;s text stays crisp and editable.</> : null,
              <>
                Add the sound:{" "}
                {script?.sound ? (script.sound_url ? <a href={script.sound_url} target="_blank" className="text-sky-300 hover:underline">{script.sound}</a> : <b>{script.sound}</b>) : "none was picked, so use one that is trending in this format."}
              </>,
              <>Start the caption with the opening line{script ? <>: <b>{script.hook}</b></> : null}. That is how we match the post back to this script.</>,
            ].filter(Boolean).map((item, i) => <Li key={i} n={i + 1}>{item}</Li>)}
          </ol>
          {!account && <Aside>No posting account is registered yet, so results can&apos;t be tracked. Run <code>mkt own add @handle</code>.</Aside>}
        </Screen>
      )}

      {step === 6 && (
        <Screen title="How it went" lead={account ? `Posts from @${account}, compared with niche videos of the same age from accounts the same size.` : "No posting account yet."}>
          {ours.posts.length ? (
            <ul className="space-y-2 text-sm">
              {ours.posts.slice(0, 6).map((p) => (
                <li key={p.id} className="flex justify-between gap-3 border-b border-neutral-800 pb-2">
                  <a href={p.url} target="_blank" className="truncate hover:underline">{p.desc || p.id}</a>
                  <span className="shrink-0 text-neutral-400">{(p.views_72h ?? p.views_now ?? 0).toLocaleString()} views · {reward(p.lift_matched ?? p.lift_72h ?? p.lift_now, "too new")}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-neutral-400">Nothing posted yet. Once you post, views show up here within a day and steer which format gets picked next.</p>
          )}
          <p className="mt-4 text-sm text-neutral-400">
            {fs.collecting
              ? `Wider patterns across the niche need more scored videos (${fs.status.reached["scored"] ?? 0} of ${fs.min_n ?? 20}); they fill in as cycles run.`
              : <>Patterns across the niche are ready on <Link href="/findings" className="text-sky-300 hover:underline">Findings</Link>.</>}
          </p>
          <div className="mt-6 rounded-lg border border-neutral-800 p-4">
            <div className="text-sm font-medium">Make the next batch</div>
            <p className="mt-1 text-xs text-neutral-500">Re-reads what&apos;s working and how our posts did, writes new scripts and renders new clips. About 30 to 60 minutes, roughly $6 per clip. {usd(o.spent_usd)} spent so far.</p>
            <form action={startRun} className="mt-3"><button className={button}>Make new clips</button></form>
          </div>
        </Screen>
      )}

      <div className="sticky bottom-0 -mx-4 mt-8 flex items-center justify-between border-t border-neutral-900 bg-neutral-950/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:px-0 sm:py-0">
        {step > 1 ? <Link href={href(step - 1)} className="rounded border border-neutral-700 px-4 py-2 text-sm hover:bg-neutral-800">Back</Link> : <span />}
        {step < STEPS.length
          ? <Link href={href(step + 1)} className="rounded bg-neutral-100 px-5 py-2 text-sm font-medium text-neutral-900 hover:bg-white">Next: {STEPS[step]}</Link>
          : <Link href={href(1)} className="rounded border border-neutral-700 px-4 py-2 text-sm hover:bg-neutral-800">Start over</Link>}
      </div>
    </div>
  );
}

function Screen({ title, lead, children }: { title: string; lead: string; children?: React.ReactNode }) {
  return (
    <section className="mt-1">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-2 mb-5 text-sm text-neutral-400">{lead}</p>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="mt-1 text-sm text-neutral-200">{children}</div>
    </div>
  );
}

function Li({ n, children }: { n: number; children: React.ReactNode }) {
  return <li className="flex gap-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-neutral-800 text-xs">{n}</span><span className="pt-0.5">{children}</span></li>;
}

function Aside({ children }: { children: React.ReactNode }) {
  return <p className="mt-5 text-xs leading-relaxed text-neutral-500">{children}</p>;
}

function Others({ clips, current, step, posted }: { clips: Render[]; current?: number; step: number; posted: Map<number, unknown> }) {
  return (
    <div className="mt-6">
      <div className="text-xs text-neutral-500">Other clips</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {clips.map((c) => (
          <Link key={c.script_id} href={`/?step=${step}&clip=${c.script_id}`} className={`rounded border px-2 py-1 text-xs ${c.script_id === current ? "border-neutral-300 text-white" : "border-neutral-800 text-neutral-400 hover:border-neutral-600"}`}>
            {c.hook}{posted.has(c.script_id) ? " (posted)" : c.hold_reason ? " (on hold)" : ""}
          </Link>
        ))}
      </div>
    </div>
  );
}
