import type { Metadata } from "next";
import { ReactNode } from "react";

export const metadata: Metadata = {
  // Static metadata, so it has to describe the page for the visitor who will
  // overwhelmingly see it: a stranger reaching a server whose household
  // already exists. "Create your household" reads as an invitation in the
  // browser tab and in any link preview, which is the opposite of true.
  title: "Join a household",
  description:
    "Raven Ledger servers host a single private household. Members join " +
    "through a private invitation link, never through a public sign-up.",
  robots: { index: false, follow: false },
};

export default function RegisterLayout({
  children,
}: {
  children: ReactNode;
}) {
  return children;
}
