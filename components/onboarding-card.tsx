"use client";

import { ArrowRight, Check, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import {
  loadOnboarding,
  ONBOARDING_COPY,
  OnboardingStatus,
  requiredProgress,
  visibleSteps,
} from "@/lib/onboarding";

/**
 * Compact setup reminder for the dashboard. It stays out of the way once the
 * essential steps are done or the household member dismisses it.
 */
export function OnboardingCard() {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadOnboarding()
      .then((result) => {
        if (!cancelled) setStatus(result);
      })
      .catch(() => {
        // The checklist is a helper, not a requirement for the dashboard.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!status || hidden || status.dismissed) return null;

  const progress = requiredProgress(status);
  if (progress.finished) return null;

  async function dismiss() {
    setHidden(true);
    try {
      await apiFetch("/onboarding/dismiss", { method: "POST" });
    } catch {
      // A failed dismissal only means the card returns on the next visit.
    }
  }

  // The count above tracks essentials, so the list must not advertise
  // optional steps as if they were part of it.
  const remaining = visibleSteps(status).filter(
    (step) => !step.complete && !ONBOARDING_COPY[step.key].optional,
  );

  return (
    <section className="onboarding-banner">
      <div className="onboarding-banner-icon" aria-hidden="true">
        <Sparkles size={16} />
      </div>
      <div className="onboarding-banner-body">
        <p className="eyebrow">Finish setting up</p>
        <strong>
          {progress.complete} of {progress.total} essentials done
        </strong>
        <ul>
          {remaining.slice(0, 3).map((step) => (
            <li key={step.key}>
              <Check size={11} aria-hidden="true" />
              {ONBOARDING_COPY[step.key].title}
            </li>
          ))}
        </ul>
      </div>
      <div className="onboarding-banner-actions">
        <Link className="primary-button" href="/welcome">
          Continue setup <ArrowRight size={14} />
        </Link>
        <button
          className="icon-button"
          onClick={dismiss}
          title="Hide setup checklist"
          type="button"
        >
          <X size={14} />
          <span className="sr-only">Hide setup checklist</span>
        </button>
      </div>
    </section>
  );
}
