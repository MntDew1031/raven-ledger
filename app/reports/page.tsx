"use client";

import { AppShell } from "@/components/app-shell";
import { ReportsManager } from "@/components/reports-manager";

export default function ReportsPage() {
  return (
    <AppShell active="Reports">
      <ReportsManager />
    </AppShell>
  );
}
