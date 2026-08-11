"use client";

import { AppShell } from "@/components/app-shell";
import { CategoriesManager } from "@/components/categories-manager";

export default function CategoriesPage() {
  return (
    <AppShell active="Categories">
      <CategoriesManager />
    </AppShell>
  );
}
