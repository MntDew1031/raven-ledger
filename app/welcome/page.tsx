"use client";

import { AppShell } from "@/components/app-shell";
import { OnboardingGuide } from "@/components/onboarding-guide";

export default function WelcomePage() {
  return (
    <AppShell active="/welcome">
      <OnboardingGuide />
    </AppShell>
  );
}
