"use client";

import {
  ArrowRight,
  Check,
  Copy,
  LoaderCircle,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { PlaidLinkButton } from "@/components/plaid-link-button";
import {
  AccountKind,
  AccountType,
  accountTypeOptions,
  kindForType,
} from "@/lib/accounts";
import { apiFetch } from "@/lib/api";
import {
  inviteLink,
  loadOnboarding,
  ONBOARDING_COPY,
  OnboardingStatus,
  OnboardingStepKey,
  requiredProgress,
  visibleSteps,
} from "@/lib/onboarding";

type PlaidStatus = { configured: boolean };

export function OnboardingGuide() {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [plaid, setPlaid] = useState<PlaidStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [accountType, setAccountType] = useState<AccountType>("checking");
  const [invite, setInvite] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);

  const refresh = useCallback(async () => {
    const next = await loadOnboarding();
    setStatus(next);
    return next;
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      loadOnboarding(),
      apiFetch<PlaidStatus>("/plaid/status").catch(() => ({
        configured: false,
      })),
    ])
      .then(([statusResult, plaidResult]) => {
        if (cancelled) return;
        setStatus(statusResult);
        setPlaid(plaidResult);
        setError("");
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load your setup checklist",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function createAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    const kind: AccountKind = kindForType(accountType);
    setBusy("account");
    setError("");
    try {
      await apiFetch("/accounts", {
        method: "POST",
        body: JSON.stringify({
          name: form.get("name"),
          institution_name: form.get("institution_name") || null,
          type: accountType,
          kind,
          current_balance: Number(form.get("current_balance") ?? 0),
          is_on_budget: true,
          credit_limit: null,
        }),
      });
      await refresh();
      element.reset();
      setAccountType("checking");
      setNotice("Account added.");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not add the account",
      );
    } finally {
      setBusy("");
    }
  }

  async function createInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy("partner");
    setError("");
    try {
      const result = await apiFetch<{ invite_token: string }>(
        "/households/invites",
        {
          method: "POST",
          body: JSON.stringify({
            email: form.get("email"),
            role: form.get("role"),
          }),
        },
      );
      setInvite(inviteLink(result.invite_token));
      await refresh();
      setNotice("Invitation ready. Share the link privately.");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not create the invitation",
      );
    } finally {
      setBusy("");
    }
  }

  async function copyInvite() {
    if (!invite) return;
    await navigator.clipboard.writeText(invite);
    setNotice("Join link copied.");
  }

  async function finish() {
    setFinishing(true);
    try {
      await apiFetch("/onboarding/dismiss", { method: "POST" });
      window.location.assign("/");
    } catch (reason) {
      setFinishing(false);
      setError(
        reason instanceof Error ? reason.message : "Could not save your progress",
      );
    }
  }

  if (loading) {
    return (
      <div className="onboarding-loading">
        <LoaderCircle className="spin" size={22} aria-hidden="true" />
        <p>Preparing your household…</p>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="panel">
        <h2>Setup unavailable</h2>
        <p className="negative">{error || "Could not load your checklist."}</p>
      </div>
    );
  }

  const steps = visibleSteps(status);
  const progress = requiredProgress(status);

  function stepAction(key: OnboardingStepKey, complete: boolean) {
    if (key === "household") return null;

    if (key === "account") {
      return (
        <form className="onboarding-form" onSubmit={createAccount}>
          <div className="field">
            <span>Account name</span>
            <input
              className="form-control"
              maxLength={160}
              name="name"
              placeholder="Everyday checking"
              required
              type="text"
            />
          </div>
          <div className="field">
            <span>Institution</span>
            <input
              className="form-control"
              maxLength={255}
              name="institution_name"
              placeholder="Optional"
              type="text"
            />
          </div>
          <div className="field">
            <label htmlFor="onboarding-account-type">Type</label>
            <select
              className="form-control"
              id="onboarding-account-type"
              onChange={(event) =>
                setAccountType(event.target.value as AccountType)
              }
              value={accountType}
            >
              {accountTypeOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <span>
              {kindForType(accountType) === "liability"
                ? "Amount owed"
                : "Current balance"}
            </span>
            <input
              className="form-control"
              defaultValue="0"
              name="current_balance"
              required
              step="0.01"
              type="number"
            />
          </div>
          <button
            className="primary-button"
            disabled={busy === "account"}
            type="submit"
          >
            {busy === "account" ? "Adding…" : complete ? "Add another" : "Add account"}
          </button>
        </form>
      );
    }

    if (key === "bank") {
      if (!plaid?.configured) {
        return (
          <p className="onboarding-note">
            Plaid is not configured on this server yet. Manual accounts work
            without it, and you can connect banks later from Settings.
          </p>
        );
      }
      return (
        <div className="onboarding-actions">
          <PlaidLinkButton label="Connect a bank" onConnected={refresh} />
        </div>
      );
    }

    if (key === "partner") {
      return (
        <>
          <form className="onboarding-form" onSubmit={createInvite}>
            <div className="field">
              <span>Their email</span>
              <input
                className="form-control"
                name="email"
                placeholder="partner@example.com"
                required
                type="email"
              />
            </div>
            <div className="field">
              <label htmlFor="onboarding-invite-role">Access</label>
              <select
                className="form-control"
                defaultValue="member"
                id="onboarding-invite-role"
                name="role"
              >
                <option value="member">Member — view and edit</option>
                <option value="viewer">Viewer — view only</option>
                <option value="owner">Owner — full control</option>
              </select>
            </div>
            <button
              className="primary-button"
              disabled={busy === "partner"}
              type="submit"
            >
              {busy === "partner" ? "Creating…" : "Create join link"}
            </button>
          </form>
          {invite && (
            <div className="invite-link">
              <code>{invite}</code>
              <button
                className="ghost-button"
                onClick={copyInvite}
                type="button"
              >
                <Copy size={14} /> Copy
              </button>
              <p className="onboarding-note">
                This link is valid for 7 days and can only be used by the email
                you entered. Share it privately.
              </p>
            </div>
          )}
        </>
      );
    }

    const destination = key === "budget" ? "/budgets" : "/transactions";
    return (
      <div className="onboarding-actions">
        <Link className="ghost-button" href={destination}>
          {key === "budget" ? "Open budget" : "Open transactions"}
          <ArrowRight size={14} />
        </Link>
      </div>
    );
  }

  return (
    <div className="onboarding-page">
      <header className="onboarding-header">
        <p className="eyebrow">
          <Sparkles size={13} aria-hidden="true" /> Getting started
        </p>
        <h1>Welcome to {status.household_name}</h1>
        <p>
          A few short steps and your dashboard, budget, and reports will have
          real numbers in them.
        </p>
        <div className="onboarding-progress">
          <div
            aria-label={`${progress.complete} of ${progress.total} required steps complete`}
            className="onboarding-progress-track"
            role="img"
          >
            <span
              style={{
                width: `${progress.total ? (progress.complete / progress.total) * 100 : 0}%`,
              }}
            />
          </div>
          <small>
            {progress.complete} of {progress.total} essentials done
          </small>
        </div>
      </header>

      {notice && <p className="onboarding-notice">{notice}</p>}
      {error && (
        <p className="negative" role="alert">
          {error}
        </p>
      )}

      <ol className="onboarding-steps">
        {steps.map((step, index) => {
          const copy = ONBOARDING_COPY[step.key];
          return (
            <li
              className={`onboarding-step${step.complete ? " complete" : ""}`}
              key={step.key}
            >
              <div className="onboarding-step-mark" aria-hidden="true">
                {step.complete ? <Check size={14} /> : index + 1}
              </div>
              <div className="onboarding-step-body">
                <div className="onboarding-step-heading">
                  <strong>{copy.title}</strong>
                  {copy.optional && <em>Optional</em>}
                  {step.complete && (
                    <span className="onboarding-step-state">Done</span>
                  )}
                </div>
                <p>{copy.detail}</p>
                {stepAction(step.key, step.complete)}
              </div>
            </li>
          );
        })}
      </ol>

      <footer className="onboarding-footer">
        <button
          className="primary-button"
          disabled={finishing}
          onClick={finish}
          type="button"
        >
          {finishing
            ? "Saving…"
            : progress.finished
              ? "Go to dashboard"
              : "Finish later"}
        </button>
        <p>
          You can reopen this checklist any time from Settings.
        </p>
      </footer>
    </div>
  );
}
