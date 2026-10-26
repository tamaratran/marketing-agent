import { analyzeNow, repollNow } from "./actions";
import { ghost } from "./ui";

/** Manual versions of what the crons do, for when you don't want to wait. */
export function RefreshButtons() {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-400">
      <form action={repollNow}><button className={ghost}>Update view counts now</button></form>
      <form action={analyzeNow}><button className={ghost}>Recompute findings</button></form>
      <span>Updating fetches fresh public stats for every followed video (about 1 s each) and recomputes findings. This also happens on its own every 2 hours.</span>
    </div>
  );
}
