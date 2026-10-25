import { analyzeNow, repollNow } from "./actions";
import { ghost } from "./ui";

/** Manual versions of what the crons do, for when you don't want to wait. */
export function RefreshButtons() {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-400">
      <form action={repollNow}><button className={ghost}>Re-poll cohort now</button></form>
      <form action={analyzeNow}><button className={ghost}>Re-run analysis</button></form>
      <span>Re-poll records fresh public stats for every cohort video (≈1 s each) and rebuilds curves and findings; the cron does this every 2 h.</span>
    </div>
  );
}
