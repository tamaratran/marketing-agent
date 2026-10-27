import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { Suspense } from "react";
import "./globals.css";
import { Nav } from "./nav";

export const metadata: Metadata = { title: "Marketing agent", description: "Organic TikTok marketing loop for Immersive Workout" };

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={geist.variable}>
      <body className="min-h-screen bg-neutral-950 text-[15px] leading-relaxed text-neutral-200 antialiased">
        <header>
          <Suspense><Nav /></Suspense>
        </header>
        <main className="mx-auto max-w-4xl px-5 pb-20 pt-2 sm:px-8">{children}</main>
      </body>
    </html>
  );
}
