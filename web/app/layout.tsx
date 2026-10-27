import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import { Nav } from "./nav";

export const metadata: Metadata = { title: "Marketing agent", description: "Organic TikTok marketing loop for Immersive Workout" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-neutral-950 text-neutral-100 antialiased">
        <header className="border-b border-neutral-800">
          <Suspense><Nav /></Suspense>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
