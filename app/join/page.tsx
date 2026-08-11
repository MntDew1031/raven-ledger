import type { Metadata } from "next";
import { JoinHousehold } from "@/components/join-household";

export const metadata: Metadata = {
  title: "Join a household",
  robots: { index: false, follow: false },
};

export default function JoinPage() {
  return <JoinHousehold />;
}
