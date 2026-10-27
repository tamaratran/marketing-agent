"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { STEPS } from "./ui";

export function Nav() {
  const path = usePathname();
  const current = path === "/concepts" ? "/" : path;
  return (
    <nav className="flex justify-center px-5 pb-10 pt-8 sm:px-8">
      <ol className="flex items-baseline gap-6 sm:gap-8">
        {STEPS.map((s, i) => {
          const on = current === s.href;
          return (
            <li key={s.href}>
              <Link href={s.href} aria-current={on ? "page" : undefined} title={s.what} className={`text-base sm:text-lg ${on ? "font-semibold text-neutral-50 underline decoration-gold decoration-2 underline-offset-8" : "text-neutral-500 hover:text-neutral-200"}`}>
                <span className="mr-1.5 text-xs tabular-nums text-neutral-600">{i + 1}</span>{s.label}
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
