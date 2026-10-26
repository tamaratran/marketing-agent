import { redirect } from "next/navigation";

// Our posts live on the Clips page now: each clip shows whether it is posted and how it is doing.
export default function Page() {
  redirect("/clips");
}
