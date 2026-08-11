"use client";

import { Check, LoaderCircle, LogOut, UserPlus } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { AuthShell } from "@/components/auth-shell";
import { ApiError, apiFetch } from "@/lib/api";
import { registrationMessage } from "@/lib/auth-errors";

const MIN_PASSWORD_LENGTH = 12;

type InvitePreview = {
  household_name: string;
  invited_email: string;
  role: "owner" | "member" | "viewer";
  expires_at: string;
};

type Session = {
  user: { email: string };
};

const ROLE_COPY: Record<InvitePreview["role"], string> = {
  owner: "You will be able to manage everything in this household.",
  member: "You will be able to view and edit household finances.",
  viewer: "You will be able to view household finances without editing them.",
};

export function JoinHousehold({ token: initialToken }: { token?: string }) {
  const tokenRef = useRef(initialToken ?? "");
  const [invite, setInvite] = useState<InvitePreview | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [inviteError, setInviteError] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const longEnough = password.length >= MIN_PASSWORD_LENGTH;
  const matches = confirmation.length > 0 && password === confirmation;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      let token = initialToken ?? "";
      if (!token) {
        const fragment = window.location.hash.slice(1);
        if (!fragment) {
          if (!cancelled) {
            setInviteError("This invitation link is missing its private code.");
            setLoading(false);
          }
          return;
        }
        try {
          token = decodeURIComponent(fragment);
          window.history.replaceState(null, "", "/join");
        } catch {
          if (!cancelled) {
            setInviteError("This invitation link is not valid.");
            setLoading(false);
          }
          return;
        }
      }
      tokenRef.current = token;
      try {
        const preview = await apiFetch<InvitePreview>(
          "/auth/invites/preview",
          {
            method: "POST",
            body: JSON.stringify({ token }),
          },
        );
        if (!cancelled) setInvite(preview);
      } catch (reason) {
        if (!cancelled) {
          setInviteError(
            reason instanceof ApiError && reason.status === 404
              ? "This invitation is invalid, already used, or expired."
              : "This invitation could not be loaded right now.",
          );
        }
      }
      try {
        const active = await apiFetch<Session>("/auth/me");
        if (!cancelled) setSession(active);
      } catch {
        if (!cancelled) setSession(null);
      }
      if (!cancelled) setLoading(false);
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [initialToken]);

  async function signOut() {
    try {
      await apiFetch("/auth/logout", { method: "POST" });
    } finally {
      window.location.reload();
    }
  }

  async function join(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!invite) return;
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
          email: invite.invited_email,
          display_name: form.get("display_name"),
          invite_token: tokenRef.current,
          password,
        }),
      });
      window.location.replace("/");
    } catch (reason) {
      setMessage(registrationMessage(reason));
      setSubmitting(false);
    }
  }

  return (
    <AuthShell
      headline="Join the household."
      intro="One shared ledger, separate sign-ins. Your password is only ever yours."
    >
      {loading && (
        <div className="login-form auth-status">
          <LoaderCircle className="spin" size={20} aria-hidden="true" />
          <p>Checking this invitation…</p>
        </div>
      )}

      {!loading && inviteError && (
        <div className="login-form">
          <h2>Invitation unavailable</h2>
          <p>{inviteError}</p>
          <p className="auth-alt">
            Ask the household owner to send a new invitation, or{" "}
            <Link href="/login">sign in</Link> if you already have an account.
          </p>
        </div>
      )}

      {!loading && invite && !inviteError && session && (
        <div className="login-form">
          <h2>Already signed in</h2>
          <p>
            You are signed in as <strong>{session.user.email}</strong>. This
            invitation belongs to <strong>{invite.invited_email}</strong>.
          </p>
          <div className="invite-callout">
            <strong>{invite.household_name}</strong>
            <span>{ROLE_COPY[invite.role]}</span>
          </div>
          <p className="auth-hint">
            Sign out first, then open this invitation link again to accept it.
          </p>
          <button className="ghost-button" onClick={signOut} type="button">
            <LogOut size={15} /> Sign out
          </button>
        </div>
      )}

      {!loading && invite && !inviteError && !session && (
        <form className="login-form" onSubmit={join}>
          <h2>You have been invited</h2>
          <p>Set up your own sign-in for this household.</p>
          <div className="invite-callout">
            <strong>{invite.household_name}</strong>
            <span>{ROLE_COPY[invite.role]}</span>
          </div>
          <div className="form-row">
            <label htmlFor="invited_email">Email</label>
            <input
              autoComplete="username"
              defaultValue={invite.invited_email}
              id="invited_email"
              name="invited_email"
              readOnly
              type="email"
            />
          </div>
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
            {submitting ? "Joining household…" : "Join household"}
          </button>
        </form>
      )}
    </AuthShell>
  );
}
