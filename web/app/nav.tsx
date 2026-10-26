"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const groups: { label?: string; links: [string, string][] }[] = [
  { links: [["/", "Overview"]] },
  { label: "Research", links: [["/concepts", "Concepts"], ["/findings", "Findings"]] },
  { label: "Make", links: [["/scripts", "Scripts"], ["/clips", "Clips"]] },
  { label: "Ours", links: [["/ours", "Our posts"]] },
  { links: [["/runs", "Runs"]] },
];

export function Nav() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <nav className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 text-sm">
      <Link href="/" className="mr-1 font-semibold tracking-tight">mkt</Link>
      {groups.map((g, i) => (
        <div key={i} className="flex items-center gap-1">
          {g.label && <span className="mr-1 text-[11px] uppercase tracking-wide text-neutral-600">{g.label}</span>}
          {g.links.map(([href, label]) => (
            <Link key={href} href={href} className={`rounded px-2 py-1 ${active(href) ? "bg-neutral-800 text-white" : "text-neutral-300 hover:bg-neutral-800 hover:text-white"}`}>
              {label}
            </Link>
          ))}
        </div>
      ))}
    </nav>
  );
}
