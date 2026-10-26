import Link from "next/link";
import { get, usd, type Findings, type Overview, type Render, type Script } from "@/lib/api";
import type { Ours } from "@/lib/ours";
import { Card, H1, Note, Stat, Table, human, pt, reward } from "./ui";
import { Thumb } from "./thumb";

export const dynamic = "force-dynamic";

function Step({ n, href, title, value, children }: { n: number; href: string; title: string; value: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="group rounded-lg border border-neutral-800 bg-neutral-900/60 p-3 hover:border-neutral-600">
      <div className="text-[11px] text-neutral-500">{n}. {title}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums group-hover:text-white">{value}</div>
      <div className="mt-1 text-xs leading-snug text-neutral-400">{children}</div>
    </Link>
  );
}

export default async function Page() {
  const [o, fs, scripts, renders, ours] = await Promise.all([
    get<Overview>("/overview"), get<Findings>("/findings"), get<Script[]>("/scripts?days=14&limit=200"), get<Render[]>("/renders"), get<Ours>("/ours"),
  ]);
  const account = ours.accounts[0]?.handle;
  const posted = new Set(ours.posts.map((p) => p.script_id).filter(Boolean));
  const clipScripts = [...new Set(renders.map((r) => r.script_id))];
  const ready = clipScripts.filter((id) => !posted.has(id));
  const tags = [...new Set(o.top_videos.map((v) => v.source_tag).filter(Boolean))];
  return (
    <>
      <H1 sub={`Niche: ${o.niche}. The agent studies what other TikTok accounts in the niche are doing, turns the formats that are working into scripts and preview clips, and learns from how our own posts do.`}>Overview</H1>

      <Card title="How the loop works" className="mb-4">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <Step n={1} href="/concepts" title="Watch the niche" value={`${o.videos} videos`}>
            Other accounts&apos; recent videos{tags.length ? ` from ${tags.slice(0, 3).map((t) => `#${t}`).join(" ")}` : ""}, with their views tracked over time. {o.tagged} watched and tagged by the classifier.
          </Step>
          <Step n={2} href="/concepts" title="Find formats" value={`${o.concepts} concepts`}>
            Reusable video formats that are picking up views fastest. One is picked each day.
          </Step>
          <Step n={3} href="/scripts" title="Write scripts" value={`${scripts.length} scripts`}>
            The picked format remixed for the product, last 14 days.
          </Step>
          <Step n={4} href="/clips" title="Render previews" value={`${clipScripts.length} clip${clipScripts.length === 1 ? "" : "s"}`}>
            AI video previews of the best scripts, {usd(o.spent_usd)} spent so far.
          </Step>
          <Step n={5} href="/ours" title="Post and learn" value={`${ours.posts.length} post${ours.posts.length === 1 ? "" : "s"}`}>
            A person posts{account ? ` from @${account}` : ""}. Each post&apos;s views feed back into which format is picked next.
          </Step>
        </div>
        <Note className="mt-3">
          Research uses other people&apos;s videos only; our results use our own account only. The two are never mixed. A Devin session runs steps 1 to 4 when you press Run cycle on Runs; posting is always done by a person.
        </Note>
      </Card>

      <Card title="What needs you" className="mb-4">
        <ul className="space-y-1 text-sm text-neutral-300">
          {ready.length > 0 ? (
            <li>
              <Link href="/clips" className="text-sky-300 hover:underline">{ready.length} clip{ready.length > 1 ? "s" : ""} ready to post</Link>
              {account ? ` from @${account}` : ""}. Download one, post it with the caption and sound listed, and the next sync links it back to its script.
            </li>
          ) : (
            <li>No new clips waiting to be posted. The next daily run renders more.</li>
          )}
          {!account && <li>No posting account registered yet, so nothing of ours can be measured. Run <code>mkt own add @handle</code>.</li>}
          {o.stuck_accounts.length > 0 && <li className="text-amber-300">Our account may be throttled: its last few posts all stayed under 1k views.</li>}
        </ul>
      </Card>

      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <Stat label="research videos scored" value={o.scored} hint="A video is scored once it is a day old: its views compared with that creator's usual." />
        <Stat label="findings" value={fs.collecting ? "collecting" : "ready"} hint={fs.collecting ? `Need ${fs.min_n ?? 20} videos per group at 3 days old before calling anything a pattern.${fs.status.eta_72h ? ` First ones reach 3 days ${pt(fs.status.eta_72h)}.` : ""}` : "Controlled patterns are in. See Findings."} />
        <Stat label="our posts beating our usual" value={ours.posts.length ? `${ours.posts.filter((p) => (p.lift_72h ?? p.lift_now ?? 0) > 0).length}/${ours.posts.length}` : "none yet"} hint="Only posts made after the account was registered count." />
      </div>

      {o.stuck_accounts.length > 0 && (
        <Card title="Accounts that look throttled" className="mb-4">
          <Table head={["account", "posts", "median views"]} rows={o.stuck_accounts.map((a) => [a.author, a.n ?? "", a.median_views ?? ""])} />
        </Card>
      )}
      <Card title="Best-performing research videos">
        <Note className="mb-3">
          Other accounts&apos; videos, ranked by how far they beat that creator&apos;s usual views (&quot;10x usual&quot; means ten times what the account normally gets). Not yet adjusted for account size or niche; that is what Findings does. Hook and style come from the classifier.
        </Note>
        <Table
          head={["", "video", "creator", "views", "vs creator's usual", "hook", "style"]}
          rows={o.top_videos.map((v) => [
            <Thumb key={`t${v.id}`} id={v.id} href={`/videos/${v.id}`} />,
            <Link key={v.id} href={`/videos/${v.id}`} className="text-sky-300 hover:underline">{(v.desc || v.id).slice(0, 60)}</Link>,
            <Link key={`a${v.id}`} href={`/creators/${v.author}`} className="hover:underline">@{v.author}</Link>, v.views.toLocaleString(), reward(v.reward, "too new"), human(v.hook_type), human(v.visual_style),
          ])}
        />
      </Card>
    </>
  );
}
