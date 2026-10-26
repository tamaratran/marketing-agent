import { get, type Concept } from "@/lib/api";
import { H1, Table, reward } from "../ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const rows = await get<Concept[]>("/concepts");
  return (
    <>
      <H1 sub="Formats the research agent found, ranked by early traction. Reward fills in once our posts are tagged with a concept.">Concepts</H1>
      <Table
        head={["concept", "what it is", "early score", "prior", "observed reward", "n"]}
        rows={rows.map((c) => [<b key={c.id}>{c.name}</b>, <span key="d" className="text-neutral-400">{c.description}</span>, Math.round(c.early_score), c.prior.toFixed(2), reward(c.mean_reward), c.n])}
      />
    </>
  );
}
