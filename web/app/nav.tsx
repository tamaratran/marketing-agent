"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useRef } from "react";

const pages: [string, string][] = [
  ["/how", "How it decides"],
  ["/overview", "Overview"], ["/concepts", "Formats"], ["/findings", "Findings"], ["/scripts", "Scripts"],
  ["/clips", "Clips"], ["/ours", "Our posts"], ["/learnings", "Learnings"], ["/runs", "Runs"],
];

const quick: [string, string][] = [["/learnings", "Learnings"], ["/clips", "Clips"], ["/runs", "Runs"]];

export function Nav() {
  const key = usePathname() + useSearchParams().toString();
  const menu = useRef<HTMLDetailsElement>(null);
  return (
    <nav className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 text-sm">
      <div className="flex items-center gap-4">
        <Link href="/" className="font-semibold tracking-tight">mkt</Link>
        {quick.map(([href, label]) => <Link key={href} href={href} className="text-xs text-neutral-400 hover:text-neutral-100">{label}</Link>)}
      </div>
      <details key={key} ref={menu} className="relative">
        <summary className="cursor-pointer list-none text-xs text-neutral-500 hover:text-neutral-300">All details</summary>
        <div className="absolute right-0 z-10 mt-2 w-40 rounded-lg border border-neutral-800 bg-neutral-900 py-1 shadow-lg">
          {pages.map(([href, label]) => <Link key={href} href={href} onClick={() => menu.current?.removeAttribute("open")} className="block px-3 py-1.5 text-neutral-300 hover:bg-neutral-800">{label}</Link>)}
        </div>
      </details>
    </nav>
  );
}
