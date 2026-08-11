import { apiFetch } from "@/lib/api";

export type OnboardingStepKey =
  | "household"
  | "account"
  | "transactions"
  | "budget"
  | "bank"
  | "partner";

export type OnboardingStatus = {
  household_name: string;
  role: "owner" | "member" | "viewer";
  dismissed: boolean;
  steps: { key: OnboardingStepKey; complete: boolean }[];
};

export const ONBOARDING_ORDER: OnboardingStepKey[] = [
  "household",
  "account",
  "bank",
  "transactions",
  "budget",
  "partner",
];

export const ONBOARDING_COPY: Record<
  OnboardingStepKey,
  { title: string; detail: string; optional?: boolean }
> = {
  household: {
    title: "Create your household",
    detail: "Everyone you invite shares this ledger with their own sign-in.",
  },
  account: {
    title: "Add your first account",
    detail:
      "Checking, savings, credit cards, loans — anything that moves your net worth.",
  },
  bank: {
    title: "Connect a bank",
    detail: "Let Plaid keep balances and transactions up to date for you.",
    optional: true,
  },
  transactions: {
    title: "Record a transaction",
    detail: "Add spending or income so cash flow and reports have something to show.",
  },
  budget: {
    title: "Plan your first month",
    detail: "Choose category budgeting or a simpler flex plan.",
  },
  partner: {
    title: "Invite your household",
    detail: "Send a private join link. They pick their own password.",
    optional: true,
  },
};

export type RegistrationStatus = {
  open: boolean;
  reason: "bootstrap" | "enabled" | "closed";
};

/**
 * Whether this server still accepts household creation without an invitation.
 * Treat a failed lookup as closed so a stranger is never shown a form the
 * backend is going to reject.
 */
export function loadRegistrationStatus() {
  return apiFetch<RegistrationStatus>("/auth/registration").catch(
    (): RegistrationStatus => ({ open: false, reason: "closed" }),
  );
}

/** Absolute join link for an invitation token. */
export function inviteLink(token: string) {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  // Fragments are never sent to Cloudflare, Next.js, or access logs. The join
  // page reads the capability in the browser and submits it in a POST body.
  return `${origin}/join#${encodeURIComponent(token)}`;
}

export function loadOnboarding() {
  return apiFetch<OnboardingStatus>("/onboarding");
}

/** Inviting people and connecting banks are both owner-only actions. */
const OWNER_ONLY_STEPS: OnboardingStepKey[] = ["partner", "bank"];

export function visibleSteps(status: OnboardingStatus) {
  const owner = status.role === "owner";
  return status.steps
    .filter((step) => owner || !OWNER_ONLY_STEPS.includes(step.key))
    .sort(
      (left, right) =>
        ONBOARDING_ORDER.indexOf(left.key) - ONBOARDING_ORDER.indexOf(right.key),
    );
}

/**
 * The optional steps should not keep the checklist alive forever, so progress
 * is measured against the steps a household genuinely needs.
 */
export function requiredProgress(status: OnboardingStatus) {
  const required = visibleSteps(status).filter(
    (step) => !ONBOARDING_COPY[step.key].optional,
  );
  return {
    complete: required.filter((step) => step.complete).length,
    total: required.length,
    finished: required.every((step) => step.complete),
  };
}
