"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { STEPS } from "./ui";

const pages: [string, string][] = [
  ["/how", "How it decides"],
  ["/overview", "Overview"], ["/scripts", "Scripts"], ["/runs", "Runs"],
];

export function Nav() {
  const path = usePathname();
  const current = path === "/concepts" ? "/" : path;
  return (
    <nav className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-3 text-sm">
      <div className="flex min-w-0 items-center gap-3 sm:gap-4">
        <Link href="/" className="font-semibold tracking-tight">Marketing agent</Link>
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
      <ul className="flex w-full items-center gap-4 text-xs sm:w-auto sm:shrink-0">
        {pages.map(([href, label]) => {
          const on = current === href;
          return (
            <li key={href}>
              <Link href={href} aria-current={on ? "page" : undefined} className={on ? "text-neutral-100" : "text-neutral-400 hover:text-neutral-100"}>{label}</Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
