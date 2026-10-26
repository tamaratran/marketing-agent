import { redirect } from "next/navigation";

/** Findings moved under step 6 of How it decides; old links and bookmarks still land there. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const q = new URLSearchParams(Object.entries(sp).filter((e): e is [string, string] => typeof e[1] === "string")).toString();
  redirect(`/how${q ? `?${q}` : ""}#check`);
}
