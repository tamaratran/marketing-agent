import Link from "next/link";
import type { Overview } from "@/lib/api";
import { Note, Table, human, reward } from "./ui";
import { Thumb } from "./thumb";

/** Other accounts' videos ranked by how far they beat videos like them. Lives in a fold on Formats. */
export function TopVideos({ o }: { o: Overview }) {
  return (
    <>
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
    </>
  );
}
