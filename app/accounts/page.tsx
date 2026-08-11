"use client";

import { AccountManager } from "@/components/account-manager";
import { AppShell } from "@/components/app-shell";
import { ReconcilePanel } from "@/components/reconcile-panel";

export default function AccountsPage() {
  return (
    <AppShell active="Accounts">
      <AccountManager />
      {/* Below the accounts rather than above: it is a check on what is there,
          and it should not be the first thing on the page when nothing is
          wrong. */}
      <ReconcilePanel />
    </AppShell>
  );
}
