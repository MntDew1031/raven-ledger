"use client";

import { AppShell } from "@/components/app-shell";
import { BudgetManager } from "@/components/budget-manager";

export default function BudgetPage() {
  return (
    <AppShell active="Budget">
      <BudgetManager />
    </AppShell>
  );
}
