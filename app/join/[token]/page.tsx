import type { Metadata } from "next";
import { JoinHousehold } from "@/components/join-household";

export const metadata: Metadata = {
  title: "Join a household",
  robots: { index: false, follow: false },
};

export default async function JoinPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <JoinHousehold token={token} />;
}
