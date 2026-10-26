import { analyzeNow, repollNow } from "./actions";
import { ghost } from "./ui";

export function RefreshButtons() {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-400">
      <form action={repollNow}><button className={ghost}>Check post performance</button></form>
      <form action={analyzeNow}><button className={ghost}>Recompute findings</button></form>
      <span>Fetches the latest stats for our posts and tracked reference videos, then updates the findings. This also happens at the start of each run cycle.</span>
    </div>
  );
}
