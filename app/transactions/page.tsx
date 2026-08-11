"use client";

import { AppShell } from "@/components/app-shell";
import { TransactionManager } from "@/components/transaction-manager";

export default function TransactionsPage() {
  return (
    <AppShell active="Transactions">
      <TransactionManager />
    </AppShell>
  );
}
