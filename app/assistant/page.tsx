"use client";

import { AppShell } from "@/components/app-shell";
import { AssistantChat } from "@/components/assistant-chat";

export default function AssistantPage() {
  return (
    <AppShell active="Assistant">
      <AssistantChat />
    </AppShell>
  );
}
