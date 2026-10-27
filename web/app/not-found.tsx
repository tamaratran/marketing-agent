import Link from "next/link";
import { H1 } from "./ui";

export default function NotFound() {
  return (
    <>
      <H1 sub="The agent has no record of this video, creator or page.">Not here</H1>
      <p className="text-sm">
        <Link href="/" className="text-gold hover:underline">Back to the walkthrough</Link>
      </p>
    </>
  );
}
