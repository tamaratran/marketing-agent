"use client";
import { useFormStatus } from "react-dom";

function Button({ account }: { account?: string }) {
  const { pending } = useFormStatus();
  return (
    <button disabled={pending} className="rounded bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-900 hover:bg-white disabled:opacity-50">
      {pending ? "Starting..." : `Post to TikTok${account ? ` as @${account}` : ""}`}
    </button>
  );
}

/** One press, one post: starts the Devin session that uploads this clip from our account. */
export function PostButton({ action, scriptId, account }: { action: (f: FormData) => Promise<void>; scriptId: number; account?: string }) {
  return (
    <form action={action} className="mt-2" onSubmit={(e) => { if (!confirm(`Post this clip to TikTok${account ? ` as @${account}` : ""}?`)) e.preventDefault(); }}>
      <input type="hidden" name="script_id" value={scriptId} />
      <Button account={account} />
    </form>
  );
}
