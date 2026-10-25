import Link from "next/link";
import { get, fmt, type VideoDetail } from "@/lib/api";
import { Card, H1, Pill, Stat, Table } from "../../ui";
import { Curve } from "../../curve";
import { Thumb } from "../../thumb";
import { tiktokEmbed } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const d = await get<VideoDetail>(`/videos/${id}`);
  const v = d.video, f = d.features, t = d.tags?.tags ?? null, run = d.tags?.run;
  const posted = new Date(v.create_time * 1000).toUTCString();
  const tagRows = t
    ? Object.entries(t).filter(([k]) => !["summary", "quality_issues"].includes(k)).map(([k, val]) => [k, Array.isArray(val) ? val.join(", ") : String(val ?? "")])
    : [];
  return (
    <>
      <H1 sub={`@${v.author} · posted ${posted} · ${v.duration ?? "?"}s · #${v.source_tag}${v.niche ? ` · ${v.niche}` : ""}${v.cohort_at ? " · cohort" : ""}`}>{v.desc || v.id}</H1>
      <p className="mb-4 text-sm">
        <a href={v.url} target="_blank" className="text-sky-300 hover:underline">open on TikTok</a>
        {" · "}
        <Link href={`/creators/${v.author}`} className="text-sky-300 hover:underline">creator page</Link>
        {v.music && <span className="text-neutral-400"> · sound: {v.music}</span>}
        {v.hashtags.length > 0 && <span className="text-neutral-500"> · {v.hashtags.map((h) => `#${h}`).join(" ")}</span>}
      </p>
      {f && (
        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-6">
          {[1, 6, 24, 72, 168].map((a) => (
            <Stat key={a} label={`views at ${a < 24 ? `${a}h` : `${a / 24}d`}`} value={f[`views_${a}h`] != null ? Math.round(f[`views_${a}h`] as number).toLocaleString() : "not yet"} />
          ))}
          <Stat label="lift at 72h (log10 vs creator)" value={f.lift_72h != null ? fmt(f.lift_72h as number) : f.creator_baseline_log == null ? "no baseline" : "not yet"} />
        </div>
      )}
      <div className="mb-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_340px]">
        <Card title="View curve (log-log; dashed line is the creator's median)">
          <Curve obs={d.observations} createTime={v.create_time} baselineLog={f?.creator_baseline_log as number | null} />
          <p className="mt-2 text-xs text-neutral-500">{d.observations.length} observations, oldest {d.observations[0] ? ((d.observations[0].observed_at - v.create_time) / 3600).toFixed(1) : "-"}h, latest {d.observations.at(-1) ? ((d.observations.at(-1)!.observed_at - v.create_time) / 3600).toFixed(1) : "-"}h after posting.</p>
        </Card>
        <Card title="Watch">
          <iframe src={tiktokEmbed(v.id)} title={v.desc || v.id} className="h-[580px] w-full rounded border-0 bg-black" allow="encrypted-media; fullscreen" />
          <details className="mt-2 text-xs text-neutral-500"><summary className="cursor-pointer">poster frame we classified</summary><div className="mt-2"><Thumb id={v.id} size={160} /></div></details>
        </Card>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card title={t ? `Classifier (${run?.model}, ${run?.latency_s}s)` : "Classifier"}>
          {t ? (
            <>
              <p className="mb-3 text-sm text-neutral-200">{String(t.summary ?? "")}</p>
              {Array.isArray(t.quality_issues) && t.quality_issues.length > 0 && (
                <p className="mb-3 text-sm text-amber-300">issues: {(t.quality_issues as string[]).join("; ")}</p>
              )}
              <Table head={["field", "value"]} rows={tagRows} />
              <details className="mt-3 text-sm text-neutral-400">
                <summary className="cursor-pointer">what the model saw</summary>
                <p className="mt-2">frames at {run?.frame_times.map((x) => `${x}s`).join(", ")}; transcript: <span className="text-neutral-300">{run?.transcript || "(none)"}</span></p>
              </details>
            </>
          ) : (
            <p className="text-sm text-neutral-500">Not tagged yet.</p>
          )}
        </Card>
        <Card title="Creator baseline">
          {d.creator ? (
            <Table head={["", ""]} rows={[
              ["followers", d.creator.followers?.toLocaleString() ?? ""],
              ["posts on profile", d.creator.video_count?.toLocaleString() ?? ""],
              ["total likes", d.creator.heart_count?.toLocaleString() ?? ""],
              ["posts we track", d.creator.n_posts],
              ["median views of those", d.creator.median_views?.toLocaleString() ?? "n/a"],
            ]} />
          ) : (
            <p className="text-sm text-neutral-500">No snapshot.</p>
          )}
          {f && (
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              {["follower_bucket", "duration_bucket", "posted_hour_bucket", "pacing_bucket"].map((k) => f[k] ? <Pill key={k}>{k.replace("_bucket", "")}: {String(f[k])}</Pill> : null)}
            </div>
          )}
        </Card>
      </div>
      <Card title="Raw observations" className="mt-4">
        <Table head={["age (h)", "views", "likes", "comments", "shares", "saves"]} rows={d.observations.map((o) => [((o.observed_at - v.create_time) / 3600).toFixed(1), o.views?.toLocaleString() ?? "", o.likes ?? "", o.comments ?? "", o.shares ?? "", o.saves ?? ""])} />
      </Card>
    </>
  );
}
