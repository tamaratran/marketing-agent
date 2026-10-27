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
    <nav className="mx-auto flex max-w-6xl flex-col items-center gap-3 px-4 pb-6 pt-8">
      <ol className="flex items-center gap-3 sm:gap-5">
        {STEPS.map((s, i) => {
          const on = current === s.href;
          return (
            <li key={s.href} className="flex items-center gap-3 sm:gap-5">
              {i > 0 && <span aria-hidden className="text-neutral-700">›</span>}
              <Link href={s.href} aria-current={on ? "page" : undefined} title={s.what} className={`flex items-center gap-2 text-base sm:text-lg ${on ? "text-neutral-100" : "text-neutral-400 hover:text-neutral-100"}`}>
                <span className={`flex h-7 w-7 items-center justify-center rounded-full text-sm ${on ? "bg-neutral-100 text-neutral-900" : "border border-neutral-700"}`}>{i + 1}</span>
                <span className={on ? "font-medium" : "hidden sm:inline"}>{s.label}</span>
              </Link>
            </li>
          );
        })}
      </ol>
      <ul className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs">
        {pages.map(([href, label]) => {
          const on = current === href;
          return (
            <li key={href}>
              <Link href={href} aria-current={on ? "page" : undefined} className={on ? "text-neutral-100" : "text-neutral-500 hover:text-neutral-100"}>{label}</Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
