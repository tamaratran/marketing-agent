import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = { title: "mkt", description: "organic marketing loop" };

const nav = [
  ["/", "Overview"], ["/findings", "Findings"], ["/ours", "Our posts"], ["/concepts", "Concepts"], ["/scripts", "Scripts"], ["/clips", "Clips"],
  ["/runs", "Runs"],
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-neutral-950 text-neutral-100 antialiased">
        <header className="border-b border-neutral-800">
          <nav className="mx-auto flex max-w-6xl flex-wrap items-center gap-1 px-4 py-3 text-sm">
            <span className="mr-4 font-semibold tracking-tight">mkt</span>
            {nav.map(([href, label]) => (
              <Link key={href} href={href} className="rounded px-2 py-1 text-neutral-300 hover:bg-neutral-800 hover:text-white">
                {label}
              </Link>
            ))}
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
