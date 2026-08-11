"use client";

import { KeyRound, LogIn } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { AuthShell } from "@/components/auth-shell";
import { ApiError, apiFetch } from "@/lib/api";
import { loadRegistrationStatus } from "@/lib/onboarding";

export default function LoginPage() {
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [signupsOpen, setSignupsOpen] = useState(false);
  const [mfaRequired, setMfaRequired] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadRegistrationStatus().then((status) => {
      if (!cancelled) setSignupsOpen(status.open);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setMessage("");
    try {
      const session = await apiFetch<{
        user: { start_page: string };
      }>("/auth/login", {
        body: JSON.stringify({
          email: form.get("email"),
          password: form.get("password"),
          mfa_code: mfaRequired ? form.get("mfa_code") : undefined,
        }),
        method: "POST",
      });
      const returnTo = new URLSearchParams(window.location.search).get("next");
      window.location.replace(
        returnTo?.startsWith("/") && !returnTo.startsWith("//")
          ? returnTo
          : session.user.start_page,
      );
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 428) {
        setMfaRequired(true);
        setMessage("Enter the code from your authenticator app.");
      } else {
        setMessage(
          mfaRequired
            ? "That authenticator or recovery code was not accepted."
            : "Sign-in failed. Check your email and password.",
        );
      }
      setSubmitting(false);
    }
  }

  return (
    <AuthShell
      headline="A shared financial life, without a shared password."
      intro="Your accounts, budgets, goals, and household history stay on infrastructure you control."
    >
      <form className="login-form" onSubmit={login}>
        <h2>Welcome back</h2>
        <p>Sign in to your household ledger.</p>
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
        {mfaRequired && (
          <div className="form-row auth-mfa-field">
            <label htmlFor="mfa_code">Authenticator or recovery code</label>
            <div className="input-with-icon">
              <KeyRound aria-hidden="true" size={15} />
              <input
                autoComplete="one-time-code"
                autoFocus
                id="mfa_code"
                maxLength={32}
                minLength={6}
                name="mfa_code"
                placeholder="123456"
                required
              />
            </div>
          </div>
        )}
        <div className="form-row">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            autoComplete="current-password"
            minLength={12}
            name="password"
            required
            type="password"
          />
        </div>
        {message && (
          <p className="negative" role="alert">
            {message}
          </p>
        )}
        <button className="primary-button" disabled={submitting} type="submit">
          <LogIn size={16} />
          {submitting
            ? mfaRequired
              ? "Verifying…"
              : "Signing in…"
            : mfaRequired
              ? "Verify and sign in"
              : "Sign in"}
        </button>
        {signupsOpen && (
          <p className="auth-alt">
            No household yet? <Link href="/register">Create one</Link>
          </p>
        )}
      </form>
    </AuthShell>
  );
}
