"use client";
import { useFormStatus } from "react-dom";
import { button } from "./ui";

function Button({ account }: { account?: string }) {
  const { pending } = useFormStatus();
  return (
    <button disabled={pending} className={button}>
      {pending ? "Starting..." : `Post to TikTok${account ? ` as @${account}` : ""}`}
    </button>
  );
}

/** One press, one post: starts the Devin session that uploads this clip from our account. */
export function PostButton({ action, scriptId, account }: { action: (f: FormData) => Promise<void>; scriptId: number; account?: string }) {
  return (
    <form action={action} onSubmit={(e) => { if (!confirm(`Post this clip to TikTok${account ? ` as @${account}` : ""}?`)) e.preventDefault(); }}>
      <input type="hidden" name="script_id" value={scriptId} />
      <Button account={account} />
    </form>
  );
}
