"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

const pages: [string, string][] = [
  ["/how", "How it decides"],
  ["/overview", "Overview"], ["/concepts", "Formats"], ["/findings", "Findings"], ["/scripts", "Scripts"],
  ["/clips", "Clips"], ["/ours", "Our posts"], ["/runs", "Runs"],
];

export function Nav() {
  const key = usePathname() + useSearchParams().toString();
  return (
    <nav className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 text-sm">
      <Link href="/" className="font-semibold tracking-tight">mkt</Link>
      <details key={key} className="relative">
        <summary className="cursor-pointer list-none text-xs text-neutral-500 hover:text-neutral-300">All details</summary>
        <div className="absolute right-0 z-10 mt-2 w-40 rounded-lg border border-neutral-800 bg-neutral-900 py-1 shadow-lg">
          {pages.map(([href, label]) => <Link key={href} href={href} className="block px-3 py-1.5 text-neutral-300 hover:bg-neutral-800">{label}</Link>)}
        </div>
      </details>
    </nav>
  );
}
