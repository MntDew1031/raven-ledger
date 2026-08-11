import { redirect } from "next/navigation";

/**
 * Folded into /automation in 1.45.0. Kept as a redirect rather than deleted so
 * bookmarks and anything still linking here land somewhere useful.
 */
export default function RulesPage() {
  redirect("/automation");
}
