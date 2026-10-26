import Link from "next/link";
import { get, type Concept, type Script } from "@/lib/api";
import { H1, Note, Table, formatName, reward } from "../ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [rows, scripts] = await Promise.all([get<Concept[]>("/concepts"), get<Script[]>("/scripts?days=14&limit=200")]);
  const used = new Map<string, number>();
  for (const s of scripts) used.set(s.concept, (used.get(s.concept) ?? 0) + 1);
  return (
    <>
      <H1 sub="Reusable video formats the research agent found in other accounts' videos. Each day the picker chooses one to write scripts from.">Formats</H1>
      <Note className="mb-4">
        <b className="text-neutral-400">Early traction</b>: how fast videos in this format gained views, discounted for big accounts.{" "}
        <b className="text-neutral-400">Head start</b>: the score the picker starts each format from. Higher gets picked more.{" "}
        <b className="text-neutral-400">Traits</b>: what its hook type, visual style, product timing and pace have earned across all our posts (and, at a quarter weight, across the niche); a format we never posted still inherits this, and it is what gets added to the head start until the format has posts of its own.{" "}
        <Link href="/how" className="text-sky-300 hover:underline">See the real pick chances</Link>.{" "}
        <b className="text-neutral-400">Our results</b>: how our posts in this format did against niche videos of the same age from accounts the same size.
      </Note>
      <Table
        head={["format", "what it is", "early traction", "head start", "traits", "scripts (14d)", "our results"]}
        rows={rows.map((c) => [
          <b key={c.id} className="block min-w-[8rem]">{formatName(c.name)}</b>,
          <span key="d" className="block min-w-[18rem] max-w-md text-neutral-400">{c.description}</span>,
          Math.round(c.early_score),
          c.prior.toFixed(2),
          c.trait_detail?.length ? <span key="t" className={(c.trait_bonus ?? 0) > 0 ? "text-emerald-300" : (c.trait_bonus ?? 0) < 0 ? "text-red-300" : "text-neutral-500"}>{(c.trait_bonus ?? 0) > 0 ? "+" : ""}{(c.trait_bonus ?? 0).toFixed(2)}</span> : <span key="t" className="text-neutral-600">unclassified</span>,
          used.get(c.name) ?? 0,
          c.n ? <span key="r">{reward(c.mean_reward)} <span className="text-neutral-500">({c.n} post{c.n > 1 ? "s" : ""})</span></span> : <span key="r" className="text-neutral-600">not posted yet</span>,
        ])}
        empty="No formats yet. The daily run groups research videos into formats."
      />
    </>
  );
}
