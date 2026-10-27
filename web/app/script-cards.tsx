import Link from "next/link";
import { dateOf, type Script } from "@/lib/api";
import { Card, Note, Pill, formatName } from "./ui";

/** Every script of the last 14 days, hook first, shot list folded. Lives in a fold on Learnings. */
export function ScriptCards({ rows, rendered }: { rows: Script[]; rendered: Set<number> }) {
  return (
    <>
      <Note className="mb-4">
        <b className="text-neutral-400">Hook</b> is the first 1 to 3 seconds. <b className="text-neutral-400">Demo score</b> is how clearly the product is shown in the first 5 seconds (5 is best; under 3 is thrown away). Open the shot list for the second-by-second plan.
      </Note>
      <div className="grid gap-3 md:grid-cols-2">
        {rows.map((s) => (
          <Card key={s.id}>
            <div id={`s${s.id}`} className="scroll-mt-4" />
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
              <span>#{s.id}</span><span>{dateOf(s.created_at)}</span><Pill>{formatName(s.concept)}</Pill>
              <Pill tone={s.demo_score >= 4 ? "good" : "warn"}>demo {s.demo_score}/5</Pill>
              {rendered.has(s.id) && <Link href={`/clips#s${s.id}`}><Pill tone="good">clip ready</Pill></Link>}
            </div>
            <p className="font-medium"><span className="text-xs font-normal text-neutral-500">hook{s.hook_on_screen === false ? " (spoken)" : ""}: </span>{s.hook}</p>
            {s.spoken && s.spoken !== s.hook && <p className="mt-1 text-sm text-neutral-300"><span className="text-xs text-neutral-500">says: </span>{s.spoken}</p>}
            <p className="mt-1 text-sm text-neutral-400">{s.captions?.length ? <><span className="text-xs text-neutral-500">on-screen text: </span>{s.captions.join(" / ")}</> : "no on-screen text"}</p>
            {s.sound && <p className="mt-1 text-xs text-neutral-500">sound to use: {s.sound_url ? <a className="underline" href={s.sound_url} target="_blank">{s.sound}</a> : s.sound}</p>}
            <details className="mt-2 text-sm text-neutral-400"><summary className="cursor-pointer text-xs text-neutral-500">shot list</summary><p className="mt-1 whitespace-pre-wrap">{s.body}</p></details>
          </Card>
        ))}
        {!rows.length && <p className="text-sm text-neutral-500">No scripts in the last 14 days.</p>}
      </div>
    </>
  );
}
