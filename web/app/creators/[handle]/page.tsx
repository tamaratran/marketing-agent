import Link from "next/link";
import { dateOf, fmt, get, type CreatorDetail } from "@/lib/api";
import { Card, H1, Stat, Table } from "../../ui";
import { Thumb } from "../../thumb";

export const dynamic = "force-dynamic";

export default async function Page({ params }: { params: Promise<{ handle: string }> }) {
  const { handle } = await params;
  const c = await get<CreatorDetail>(`/creators/${handle}`);
  const snap = c.snapshots.at(-1);
  const lifts = c.videos.map((v) => v.lift_72h).filter((x): x is number => x != null);
  return (
    <>
      <H1 sub={`${c.videos.length} videos we track · ${c.videos.filter((v) => v.cohort_at).length} in a cohort`}>@{handle}</H1>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="followers" value={snap?.followers?.toLocaleString() ?? "?"} />
        <Stat label="posts on profile" value={snap?.video_count?.toLocaleString() ?? "?"} />
        <Stat label="total likes" value={snap?.heart_count?.toLocaleString() ?? "?"} />
        <Stat label="median views (tracked)" value={snap?.median_views?.toLocaleString() ?? "n/a"} />
        <Stat label="beat own baseline at 72h" value={lifts.length ? `${lifts.filter((x) => x > 0).length}/${lifts.length}` : "no 72h data"} />
      </div>
      <Card title="Videos">
        <Table head={["", "posted", "video", "tag", "views", "likes", "lift 72h"]} rows={c.videos.map((v) => [
          <Thumb key={`t${v.id}`} id={v.id} href={`/videos/${v.id}`} />,
          dateOf(v.create_time),
          <Link key={v.id} href={`/videos/${v.id}`} className="text-gold hover:underline">{(v.desc || v.id).slice(0, 70)}</Link>,
          v.source_tag, v.views?.toLocaleString() ?? "", v.likes?.toLocaleString() ?? "", fmt(v.lift_72h),
        ])} />
      </Card>
      {c.snapshots.length > 1 && (
        <Card title="Snapshots" className="mt-4">
          <Table head={["taken", "followers", "posts", "likes"]} rows={c.snapshots.map((s) => [dateOf(s.taken_at), s.followers?.toLocaleString() ?? "", s.video_count ?? "", s.heart_count?.toLocaleString() ?? ""])} />
        </Card>
      )}
    </>
  );
}
