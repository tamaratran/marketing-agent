"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useRef } from "react";
import { STEPS } from "./ui";

const pages: [string, string][] = [
  ["/how", "How it decides"],
  ["/overview", "Overview"], ["/findings", "Findings"], ["/scripts", "Scripts"], ["/runs", "Runs"],
];

export function Nav() {
  const path = usePathname();
  const key = path + useSearchParams().toString();
  const menu = useRef<HTMLDetailsElement>(null);
  const current = path === "/concepts" ? "/" : path;
  return (
    <nav className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3 text-sm">
      <div className="flex min-w-0 items-center gap-3 sm:gap-4">
        <Link href="/" className="font-semibold tracking-tight">mkt</Link>
        <ol className="flex min-w-0 items-center gap-2 sm:gap-3">
          {STEPS.map((s, i) => {
            const on = current === s.href;
            return (
              <li key={s.href} className="flex items-center gap-2 sm:gap-3">
                {i > 0 && <span aria-hidden className="text-neutral-700">›</span>}
                <Link href={s.href} aria-current={on ? "page" : undefined} title={s.what} className={`flex items-center gap-1.5 text-xs ${on ? "text-neutral-100" : "text-neutral-400 hover:text-neutral-100"}`}>
                  <span className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] ${on ? "bg-neutral-100 text-neutral-900" : "border border-neutral-700"}`}>{i + 1}</span>
                  <span className={on ? "" : "hidden sm:inline"}>{s.label}</span>
                </Link>
              </li>
            );
          })}
        </ol>
      </div>
      <details key={key} ref={menu} className="relative shrink-0">
        <summary className="cursor-pointer list-none text-xs text-neutral-500 hover:text-neutral-300">All details</summary>
        <div className="absolute right-0 z-10 mt-2 w-40 rounded-lg border border-neutral-800 bg-neutral-900 py-1 shadow-lg">
          {pages.map(([href, label]) => <Link key={href} href={href} onClick={() => menu.current?.removeAttribute("open")} className="block px-3 py-1.5 text-neutral-300 hover:bg-neutral-800">{label}</Link>)}
        </div>
      </details>
    </nav>
  );
}
