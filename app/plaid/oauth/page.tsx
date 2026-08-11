"use client";

import { LoaderCircle } from "lucide-react";
import dynamic from "next/dynamic";
import { AppShell } from "@/components/app-shell";

// The return leg reads the interrupted Link session out of localStorage during
// its first render, so it must never be pre-rendered on the server.
const PlaidOAuthReturn = dynamic(
  () =>
    import("@/components/plaid-oauth-return").then(
      (module) => module.PlaidOAuthReturn,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="onboarding-loading">
        <LoaderCircle className="spin" size={22} aria-hidden="true" />
        <p>Returning from your bank…</p>
      </div>
    ),
  },
);

export default function PlaidOAuthPage() {
  return (
    <AppShell active="/settings">
      <PlaidOAuthReturn />
    </AppShell>
  );
}
