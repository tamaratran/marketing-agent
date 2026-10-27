"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { STEPS } from "./ui";

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
    </nav>
  );
}
