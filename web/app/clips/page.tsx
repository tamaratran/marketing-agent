/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { dateOf, get, type Render, type Script, frameUrl } from "@/lib/api";
import type { Ours, OursPost } from "@/lib/ours";
import { Card, H1, Pill, Stat, Table, formatName, reward, times } from "../ui";
import { Thumb } from "../thumb";
import { MIN_AGE_H_OWN } from "./why";
import { age, statusOf, tone, views } from "./status";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [all, scripts, ours] = await Promise.all([
    get<Render[]>("/renders"), get<Script[]>("/scripts?days=60&limit=500"), get<Ours>("/ours"),
  ]);
  const seen = new Set<number>();
  const rows = all.filter((r) => !seen.has(r.script_id) && seen.add(r.script_id));
  const byId = new Map(scripts.map((s) => [s.id, s]));
  const posts = new Map(ours.posts.filter((p) => p.script_id).map((p) => [p.script_id as number, p]));
  const account = ours.accounts[0]?.handle;
  const posted = rows.filter((r) => posts.has(r.script_id)).length;
  const measured = ours.posts.filter((p) => p.age_h >= MIN_AGE_H_OWN && p.lift_matched != null);
  const beat = measured.filter((p) => (p.lift_matched ?? 0) > 0).length;
  const unmatched = ours.posts.filter((p) => !p.script_id);
  return (
    <>
      <H1 sub={account ? `Each clip, whether it is on @${account}, and how it is doing. Open one for the numbers behind it.` : "Each clip and how it is doing."}>Clips</H1>
      <div className="mb-10 grid grid-cols-3 gap-6">
        <Stat label="clips" value={rows.length} />
        <Stat label={account ? `on @${account}` : "posted"} value={posted} />
        <Stat label="ahead of videos like them" value={measured.length ? `${beat} of ${measured.length}` : "–"} />
      </div>
      {rows.length > 0 ? (
        <ul className="grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3 md:grid-cols-4">
          {rows.map((r) => <Poster key={r.id} r={r} s={byId.get(r.script_id)} p={posts.get(r.script_id)} />)}
        </ul>
      ) : (
        <p className="text-neutral-500">No clips yet. Generate clips on Learnings renders the best scripts.</p>
      )}

      {unmatched.length > 0 && (
        <Card title="Posts without a clip">
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

function Poster({ r, s, p }: { r: Render; s?: Script; p?: OursPost }) {
  const st = statusOf(r, !!p);
  const id = `s${r.script_id}`;
  const early = p ? p.age_h < MIN_AGE_H_OWN : false;
  return (
    <li id={id} className="scroll-mt-4">
      <Link href={`/clips/${r.script_id}`} className="group block">
        <div className="relative aspect-[9/16] overflow-hidden rounded-sm bg-neutral-900">
          <img src={frameUrl(id)} alt="" loading="lazy" className="h-full w-full object-cover transition-opacity group-hover:opacity-80" />
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-neutral-950/95 via-neutral-950/60 to-transparent px-3 pb-3 pt-12">
            {p ? (
              <>
                <p className="text-2xl font-semibold leading-none tabular-nums text-neutral-50">{views(p.views_now) || "0"}</p>
                <p className="mt-1 text-xs tabular-nums text-neutral-300">
                  views{early ? "" : p.lift_matched != null ? ` · ${times(p.lift_matched)} videos like it` : ""}
                </p>
              </>
            ) : (
              <p className="text-sm font-medium text-neutral-200">{st}</p>
            )}
          </div>
        </div>
        <p className="mt-2 line-clamp-2 text-sm font-medium leading-snug text-neutral-100 group-hover:text-neutral-50">{r.hook}</p>
        <p className="mt-1 flex flex-wrap items-baseline gap-x-2 text-xs text-neutral-500">
          <Pill tone={tone(st)}>{st}</Pill>
          {p && <span>{age(p.age_h)} up</span>}
          <span>s{r.script_id}</span>
          {s?.concept && <span className="hidden truncate sm:inline">{formatName(s.concept)}</span>}
        </p>
      </Link>
    </li>
  );
}

const lift = (p: OursPost) =>
  p.age_h < MIN_AGE_H_OWN
    ? <span key="early" className="text-neutral-500">too early, {p.age_h.toFixed(1)}h</span>
    : reward(p.lift_matched, p.views_now ? "no reference videos yet" : "no views yet", "videos like it");
