"use client";
/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { useState } from "react";
import { frameUrl } from "@/lib/api";

/** Poster frame for a video we downloaded; videos we only polled have no frame and show a blank tile. */
export function Thumb({ id, size = 56, href }: { id: string; size?: number; href?: string }) {
  const [missing, setMissing] = useState(false);
  const h = Math.round((size * 16) / 9);
  const img = missing ? (
    <div className="rounded bg-neutral-800" style={{ width: size, height: h }} title="not downloaded, no frame" />
  ) : (
    <img src={frameUrl(id)} alt="" width={size} height={h} loading="lazy" onError={() => setMissing(true)} className="rounded bg-neutral-800 object-cover" style={{ width: size, height: h }} />
  );
  return href ? <Link href={href} className="block shrink-0">{img}</Link> : img;
}
