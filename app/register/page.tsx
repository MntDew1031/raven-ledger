"use client";

import { Check, LoaderCircle, ShieldCheck, UserPlus } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { AuthShell } from "@/components/auth-shell";
import { apiFetch } from "@/lib/api";
import { registrationMessage } from "@/lib/auth-errors";
import { loadRegistrationStatus, RegistrationStatus } from "@/lib/onboarding";

const MIN_PASSWORD_LENGTH = 12;

export default function RegisterPage() {
  const [status, setStatus] = useState<RegistrationStatus | null>(null);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadRegistrationStatus().then((result) => {
      if (!cancelled) setStatus(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const longEnough = password.length >= MIN_PASSWORD_LENGTH;
  const matches = confirmation.length > 0 && password === confirmation;

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (password !== confirmation) {
      setMessage("The two passwords do not match.");
      return;
    }
    setSubmitting(true);
    setMessage("");
    try {
      await apiFetch("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          email: form.get("email"),
          display_name: form.get("display_name"),
          household_name: form.get("household_name"),
          password,
        }),
      });
      window.location.replace("/welcome");
    } catch (reason) {
      setMessage(registrationMessage(reason));
      setSubmitting(false);
    }
  }

  if (!status) {
    return (
      <AuthShell
        headline="Start your household ledger."
        intro="Create the first account. You can invite the rest of your household once you are in."
      >
        <div className="login-form auth-status">
          <LoaderCircle className="spin" size={20} aria-hidden="true" />
          <p>Checking this server…</p>
        </div>
      </AuthShell>
    );
  }

  if (!status.open) {
    return (
      <AuthShell
        headline="This ledger is invitation-only."
        intro="Its household already exists. New members join through a private invitation link, never through a public sign-up."
      >
        <div className="login-form">
          <div className="invite-callout">
            <strong>
              <ShieldCheck size={14} aria-hidden="true" /> Sign-ups are closed
            </strong>
            <span>
              This server hosts a private household. Ask its owner to send you
              an invitation link.
            </span>
          </div>
          <p className="auth-alt">
            Already have an account? <Link href="/login">Sign in</Link>
          </p>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      headline="Start your household ledger."
      intro="Create the first account. You can invite the rest of your household once you are in."
    >
      <form className="login-form" onSubmit={register}>
        <h2>Create your household</h2>
        <p>This first account becomes the household owner.</p>
        <div className="form-row">
          <label htmlFor="display_name">Your name</label>
          <input
            autoComplete="name"
            id="display_name"
            maxLength={120}
            name="display_name"
            required
            type="text"
          />
        </div>
        <div className="form-row">
          <label htmlFor="household_name">Household name</label>
          <input
            autoComplete="off"
            id="household_name"
            maxLength={120}
            name="household_name"
            placeholder="Example Household"
            required
            type="text"
          />
        </div>
        <div className="form-row">
          <label htmlFor="email">Email</label>
          <input
            autoComplete="username"
            id="email"
            name="email"
            required
            type="email"
          />
        </div>
        <div className="form-row">
          <label htmlFor="password">Password</label>
          <input
            autoComplete="new-password"
            id="password"
            minLength={MIN_PASSWORD_LENGTH}
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </div>
        <div className="form-row">
          <label htmlFor="confirmation">Confirm password</label>
          <input
            autoComplete="new-password"
            id="confirmation"
            minLength={MIN_PASSWORD_LENGTH}
            name="confirmation"
            onChange={(event) => setConfirmation(event.target.value)}
            required
            type="password"
            value={confirmation}
          />
        </div>
        <ul className="auth-checklist">
          <li className={longEnough ? "met" : undefined}>
            <Check size={12} aria-hidden="true" /> At least{" "}
            {MIN_PASSWORD_LENGTH} characters
          </li>
          <li className={matches ? "met" : undefined}>
            <Check size={12} aria-hidden="true" /> Both passwords match
          </li>
        </ul>
        {message && (
          <p className="negative" role="alert">
            {message}
          </p>
        )}
        <button className="primary-button" disabled={submitting} type="submit">
          <UserPlus size={16} />{" "}
          {submitting ? "Creating household…" : "Create household"}
        </button>
        <p className="auth-alt">
          Already have an account? <Link href="/login">Sign in</Link>
        </p>
      </form>
    </AuthShell>
  );
}
