"use client";

import { AppShell } from "@/components/app-shell";
import { ProfileSettings } from "@/components/profile-settings";
import { SettingsManager } from "@/components/settings-manager";

export default function SettingsPage() {
  return (
    <AppShell active="Settings">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Household controls</p>
          <h1>Private by default, shared by choice.</h1>
          <p className="subtle">
            Manage independent users, connections, sessions, and data retention.
          </p>
        </div>
      </div>

      <ProfileSettings />
      <SettingsManager />
    </AppShell>
  );
}
