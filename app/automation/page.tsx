"use client";

import { Repeat, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { OrganizerReview } from "@/components/organizer-review";
import { RecurringManager } from "@/components/recurring-manager";
import { RulesManager } from "@/components/rules-manager";

type Tab = "organizer" | "rules" | "recurring";

const TABS: { id: Tab; label: string; icon: typeof Wand2 }[] = [
  { id: "organizer", label: "Organizer", icon: Sparkles },
  { id: "rules", label: "Rules", icon: Wand2 },
  { id: "recurring", label: "Recurring", icon: Repeat },
];

/**
 * Rules, recurring bills and the organizer are one idea — things Raven does so
 * you do not have to — and they were three separate sidebar entries out of
 * eleven. Folding them together shortens the list and, more usefully, makes the
 * Organizer something you find rather than something you have to know about.
 */
export default function AutomationPage() {
  const [tab, setTab] = useState<Tab>("organizer");

  return (
    <AppShell active="Automation">
      <nav className="segmented-control automation-tabs" aria-label="Automation">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            aria-pressed={tab === id}
            className={tab === id ? "active" : ""}
            key={id}
            onClick={() => setTab(id)}
            type="button"
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </nav>

      {tab === "organizer" && <OrganizerReview />}
      {tab === "rules" && <RulesManager />}
      {tab === "recurring" && <RecurringManager />}
    </AppShell>
  );
}
