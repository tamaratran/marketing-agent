/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { frameUrl } from "@/lib/api";

/** Poster frame for a video we downloaded; videos we only polled have no frame and show a blank tile. */
export function Thumb({ id, size = 56, href }: { id: string; size?: number; href?: string }) {
  const img = (
    <img
      src={frameUrl(id)}
      alt=""
      width={size}
      height={Math.round(size * 16 / 9)}
      loading="lazy"
      className="rounded bg-neutral-800 object-cover"
      style={{ width: size, height: Math.round((size * 16) / 9) }}
    />
  );
  return href ? <Link href={href} className="block shrink-0">{img}</Link> : img;
}
