"use client";

import {
  Camera,
  Check,
  ClipboardCopy,
  History,
  KeyRound,
  Laptop,
  LoaderCircle,
  LogOut,
  Palette,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
  UserRound,
} from "lucide-react";
import Image from "next/image";
import {
  ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { LayoutModeToggle } from "@/components/layout-mode";
import { apiFetch } from "@/lib/api";
import {
  applyAppearance,
  DensityPreference,
  ThemePreference,
  UserProfile,
} from "@/lib/profile";

type SessionInfo = {
  id: string;
  current: boolean;
  created_at: string;
  last_seen_at: string;
  user_agent: string;
};

type MfaStatus = {
  enabled: boolean;
  enabled_at: string | null;
  recovery_codes_remaining: number;
};

type MfaSetup = {
  secret: string;
  otpauth_uri: string;
  expires_in_seconds: number;
};

type SecurityEvent = {
  id: string;
  event_type: string;
  success: boolean;
  ip_address: string | null;
  user_agent: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

const themes: {
  value: ThemePreference;
  label: string;
  description: string;
}[] = [
  { value: "system", label: "System", description: "Match this device" },
  { value: "light", label: "Porcelain", description: "Clean and luminous" },
  { value: "parchment", label: "Parchment", description: "Warm paper ledger" },
  { value: "dark", label: "Grove", description: "Deep forest contrast" },
  { value: "midnight", label: "Obsidian", description: "Black violet mineral" },
];

function deviceName(userAgent: string) {
  const browser = userAgent.includes("Safari") && !userAgent.includes("Chrome")
    ? "Safari"
    : userAgent.includes("Chrome")
      ? "Chrome"
      : userAgent.includes("Firefox")
        ? "Firefox"
        : "Browser";
  const device = userAgent.includes("iPhone")
    ? "iPhone"
    : userAgent.includes("iPad")
      ? "iPad"
      : userAgent.includes("Macintosh")
        ? "Mac"
        : userAgent.includes("Android")
          ? "Android"
          : "Device";
  return `${browser} on ${device}`;
}

function securityEventLabel(eventType: string) {
  const labels: Record<string, string> = {
    "account.registered": "Account created",
    "account.password_change": "Password changed",
    "account.mfa_enable": "Two-factor authentication enabled",
    "account.mfa_disable": "Two-factor authentication disabled",
    "account.mfa_recovery_codes_rotated": "Recovery codes replaced",
    "auth.login": "Sign-in",
    "auth.session_revoked": "Device signed out",
    "auth.sessions_revoked": "Other devices signed out",
    "operator.step_up": "Sensitive action confirmed",
    "household.export": "Household data exported",
    "household.invite_created": "Household invitation created",
    "household.invite_accepted": "Household invitation accepted",
    "household.invite_revoked": "Household invitation revoked",
    "api_key.created": "API key created",
    "api_key.revoked": "API key revoked",
    "plaid.link_started": "Bank connection started",
    "plaid.connected": "Bank connected",
    "plaid.disconnected": "Bank disconnected",
    "plaid.repair_started": "Bank repair started",
    "plaid.repair_completed": "Bank repair completed",
    "plaid.sync_requested": "Bank sync requested",
    "plaid.sync_failed": "Bank sync failed",
    "backup.created": "Instance backup created",
    "backup.verified": "Instance backup verified",
    "backup.downloaded": "Instance backup downloaded",
    "backup.deleted": "Instance backup deleted",
    "finance.account_created": "Account added",
    "finance.account_updated": "Account updated",
    "finance.account_hidden": "Account removed",
    "finance.transaction_created": "Transaction added",
    "finance.transaction_updated": "Transaction updated",
    "finance.transaction_deleted": "Transaction deleted",
    "finance.transaction_split": "Transaction split",
    "finance.transaction_unsplit": "Transaction split removed",
    "finance.transactions_reviewed": "Transactions reviewed",
    "finance.transactions_bulk_updated": "Transactions updated in bulk",
    "finance.transactions_imported": "Transactions imported",
    "finance.budget_saved": "Budget saved",
    "finance.category_created": "Category created",
    "finance.category_updated": "Category updated",
    "finance.category_archived": "Category archived",
    "finance.category_deleted": "Category deleted",
    "finance.category_group_created": "Category group created",
    "finance.category_group_updated": "Category group updated",
    "finance.category_group_deleted": "Category group deleted",
    "finance.tag_created": "Tag created",
    "finance.tag_updated": "Tag updated",
    "finance.tag_deleted": "Tag deleted",
    "finance.rule_created": "Automation rule created",
    "finance.rule_updated": "Automation rule updated",
    "finance.rule_deleted": "Automation rule deleted",
    "automation.rules_queued": "Automation rules queued",
    "automation.ai_review_queued": "AI review queued",
  };
  return labels[eventType] ?? eventType.replaceAll(".", " · ");
}

export function ProfileSettings() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [mfa, setMfa] = useState<MfaStatus | null>(null);
  const [mfaSetup, setMfaSetup] = useState<MfaSetup | null>(null);
  const [mfaPassword, setMfaPassword] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [securityEvents, setSecurityEvents] = useState<SecurityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [profileResult, sessionResult, mfaResult, eventsResult] = await Promise.all([
        apiFetch<UserProfile>("/profile"),
        apiFetch<SessionInfo[]>("/profile/sessions"),
        apiFetch<MfaStatus>("/profile/mfa"),
        apiFetch<SecurityEvent[]>("/profile/security-events"),
      ]);
      const normalizedProfile =
        profileResult.theme === "aurora"
          ? { ...profileResult, theme: "midnight" as const }
          : profileResult;
      setProfile(normalizedProfile);
      setSessions(sessionResult);
      setMfa(mfaResult);
      setSecurityEvents(eventsResult);
      applyAppearance(normalizedProfile);
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not load your profile",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  function publishProfile(nextProfile: UserProfile) {
    setProfile(nextProfile);
    applyAppearance(nextProfile);
    window.dispatchEvent(
      new CustomEvent("raven-profile-updated", { detail: nextProfile }),
    );
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile) return;
    const form = new FormData(event.currentTarget);
    setBusy("profile");
    setError("");
    try {
      const result = await apiFetch<UserProfile>("/profile", {
        method: "PATCH",
        body: JSON.stringify({
          display_name: form.get("display_name"),
          theme: profile.theme,
          // Kept in the wire format for backward compatibility with older
          // servers. The client deliberately exposes no decorative accent.
          accent: "plum",
          density: profile.density,
          button_style: "solid",
          start_page: form.get("start_page"),
        }),
      });
      publishProfile(result);
      setNotice("Your profile and appearance were saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save profile");
    } finally {
      setBusy("");
    }
  }

  async function uploadAvatar(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setError("Choose an image that is 5 MB or smaller.");
      return;
    }
    const body = new FormData();
    body.set("avatar", file);
    setBusy("avatar");
    setError("");
    try {
      const result = await apiFetch<UserProfile>("/profile/avatar", {
        method: "POST",
        body,
      });
      publishProfile(result);
      setNotice("Profile picture updated.");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not update the picture",
      );
    } finally {
      setBusy("");
    }
  }

  async function removeAvatar() {
    setBusy("avatar");
    setError("");
    try {
      const result = await apiFetch<UserProfile>("/profile/avatar", {
        method: "DELETE",
      });
      publishProfile(result);
      setNotice("Profile picture removed.");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not remove the picture",
      );
    } finally {
      setBusy("");
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const newPassword = String(form.get("new_password") ?? "");
    if (newPassword !== form.get("confirm_password")) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy("password");
    setError("");
    try {
      await apiFetch<void>("/profile/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: form.get("current_password"),
          new_password: newPassword,
        }),
      });
      event.currentTarget.reset();
      setNotice("Password changed. Other signed-in devices were logged out.");
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not change password",
      );
    } finally {
      setBusy("");
    }
  }

  async function revokeSession(session: SessionInfo) {
    setBusy(session.id);
    setError("");
    try {
      await apiFetch<void>(`/profile/sessions/${session.id}`, {
        method: "DELETE",
      });
      setSessions((current) => current.filter((item) => item.id !== session.id));
      setNotice("That device was signed out.");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not end the session",
      );
    } finally {
      setBusy("");
    }
  }

  async function revokeOthers() {
    setBusy("sessions");
    setError("");
    try {
      const result = await apiFetch<{ revoked: number }>(
        "/profile/sessions/revoke-others",
        { method: "POST" },
      );
      setSessions((current) => current.filter((session) => session.current));
      setNotice(
        result.revoked
          ? `${result.revoked} other session${result.revoked === 1 ? "" : "s"} ended.`
          : "No other active sessions were found.",
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not end other sessions",
      );
    } finally {
      setBusy("");
    }
  }

  async function beginMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("current_password") ?? "");
    setBusy("mfa-setup");
    setError("");
    setRecoveryCodes([]);
    try {
      const result = await apiFetch<MfaSetup>("/profile/mfa/setup", {
        method: "POST",
        body: JSON.stringify({ current_password: password }),
      });
      setMfaPassword(password);
      setMfaSetup(result);
      setNotice("Add Raven Ledger to your authenticator, then verify one code.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start MFA setup");
    } finally {
      setBusy("");
    }
  }

  async function enableMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy("mfa-enable");
    setError("");
    try {
      const result = await apiFetch<{ recovery_codes: string[] }>(
        "/profile/mfa/enable",
        {
          method: "POST",
          body: JSON.stringify({
            current_password: mfaPassword,
            code: form.get("code"),
          }),
        },
      );
      setRecoveryCodes(result.recovery_codes);
      setMfaSetup(null);
      setMfaPassword("");
      setNotice("Two-factor authentication is on. Save the recovery codes now.");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not enable MFA");
    } finally {
      setBusy("");
    }
  }

  async function manageMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement;
    const action = submitter?.value ?? "disable";
    setBusy(`mfa-${action}`);
    setError("");
    try {
      if (action === "rotate") {
        const result = await apiFetch<{ recovery_codes: string[] }>(
          "/profile/mfa/recovery-codes",
          {
            method: "POST",
            body: JSON.stringify({
              current_password: form.get("current_password"),
              code: form.get("code"),
            }),
          },
        );
        setRecoveryCodes(result.recovery_codes);
        setNotice("New recovery codes created. Every previous code is now invalid.");
      } else {
        await apiFetch<void>("/profile/mfa", {
          method: "DELETE",
          body: JSON.stringify({
            current_password: form.get("current_password"),
            code: form.get("code"),
          }),
        });
        setRecoveryCodes([]);
        setNotice("Two-factor authentication was disabled.");
      }
      event.currentTarget.reset();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update MFA");
    } finally {
      setBusy("");
    }
  }

  async function copyRecoveryCodes() {
    await navigator.clipboard.writeText(recoveryCodes.join("\n"));
    setNotice("Recovery codes copied. Store them somewhere private.");
  }

  if (loading || !profile) {
    return (
      <div className="account-loading">
        <LoaderCircle className="spin" size={21} />
        Loading your profile…
      </div>
    );
  }

  const initial = profile.display_name.slice(0, 1).toUpperCase();

  return (
    <section className="profile-settings" id="profile">
      {error && <div className="page-error profile-message">{error}</div>}
      {notice && (
        <div className="settings-notice profile-message">
          <Check size={15} /> {notice}
        </div>
      )}

      <form className="panel profile-panel" onSubmit={saveProfile}>
        <div className="settings-card-heading">
          <div>
            <p className="eyebrow">Your account</p>
            <h2>Profile and appearance</h2>
            <p>Personal settings follow you on every signed-in device.</p>
          </div>
          <UserRound size={22} />
        </div>

        <div className="profile-core">
          <div className="avatar-editor">
            <button
              aria-label="Choose a profile picture"
              className="profile-photo-button"
              disabled={busy === "avatar"}
              onClick={() => fileInput.current?.click()}
              type="button"
            >
              {profile.avatar_url ? (
                <Image
                  alt={`${profile.display_name}'s profile picture`}
                  height={88}
                  key={profile.avatar_url}
                  src={profile.avatar_url}
                  unoptimized
                  width={88}
                />
              ) : (
                <span>{initial}</span>
              )}
              <i>
                <Camera size={15} />
              </i>
            </button>
            <input
              accept="image/png,image/jpeg,image/webp"
              hidden
              onChange={uploadAvatar}
              ref={fileInput}
              type="file"
            />
            <small>PNG, JPEG, or WebP · 5 MB maximum</small>
            {profile.avatar_url && (
              <button
                className="text-button negative"
                disabled={busy === "avatar"}
                onClick={() => void removeAvatar()}
                type="button"
              >
                Remove photo
              </button>
            )}
          </div>

          <div className="profile-fields">
            <label className="field">
              <span>Display name</span>
              <input
                defaultValue={profile.display_name}
                maxLength={120}
                name="display_name"
                required
              />
            </label>
            <label className="field">
              <span>Email address</span>
              <input disabled value={profile.email} />
              <small>Email changes require administrator verification.</small>
            </label>
            <label className="field">
              <span>Start page</span>
              <select defaultValue={profile.start_page} name="start_page">
                <option value="/">Dashboard</option>
                <option value="/accounts">Accounts</option>
                <option value="/transactions">Transactions</option>
                <option value="/budgets">Budget</option>
                <option value="/reports">Reports</option>
              </select>
            </label>
          </div>
        </div>

        <div className="appearance-block">
          <div className="appearance-heading">
            <Palette size={17} />
            <div>
              <strong>Theme</strong>
              <small>Choose the atmosphere for your financial workspace.</small>
            </div>
          </div>
          <div className="theme-options">
            {themes.map((theme) => (
              <button
                aria-pressed={profile.theme === theme.value}
                className={profile.theme === theme.value ? "selected" : ""}
                key={theme.value}
                onClick={() => {
                  const next = { ...profile, theme: theme.value };
                  publishProfile(next);
                }}
                type="button"
              >
                <i className={`theme-preview ${theme.value}`} />
                <span>
                  <strong>{theme.label}</strong>
                  <small>{theme.description}</small>
                </span>
                {profile.theme === theme.value && <Check size={15} />}
              </button>
            ))}
          </div>
        </div>

        <div className="appearance-language">
          <div>
            <i className="interaction" />
            <span>
              <strong>Raven plum</strong>
              <small>Buttons, links, selections, and focus</small>
            </span>
          </div>
          <p>
            Themes change the room, not the meaning. Raven keeps interaction
            and financial colors consistent so every screen reads the same.
          </p>
        </div>

        <div className="appearance-row">
          <fieldset>
            <legend>Display density</legend>
            <div className="density-options">
              {(["comfortable", "compact"] as DensityPreference[]).map(
                (density) => (
                  <button
                    aria-pressed={profile.density === density}
                    className={profile.density === density ? "selected" : ""}
                    key={density}
                    onClick={() => {
                      const next = { ...profile, density };
                      publishProfile(next);
                    }}
                    type="button"
                  >
                    {density === "comfortable" ? "Comfortable" : "Compact"}
                  </button>
                ),
              )}
            </div>
          </fieldset>
          <fieldset>
            <legend>Layout on this device</legend>
            <LayoutModeToggle />
            <p className="field-hint">
              Raven fits your screen by default. Choose full desktop to get the
              wide tables on a phone — you can pinch to zoom, and the choice
              stays on this device only.
            </p>
          </fieldset>
        </div>

        <div className="finance-color-key" aria-label="Financial color key">
          <span><i className="obligation" /> Obligations and bills</span>
          <span><i className="discretionary" /> Wants and subscriptions</span>
          <span><i className="wealth" /> Savings, assets, and retirement</span>
          <small>These meaning colors stay consistent in every theme.</small>
        </div>

        <div className="profile-save">
          <span>
            Changes preview immediately. Save to sync them across your devices.
          </span>
          <button
            className="primary-button"
            disabled={busy === "profile"}
            type="submit"
          >
            <Save size={15} />
            {busy === "profile" ? "Saving…" : "Save profile"}
          </button>
        </div>
      </form>

      <div className="profile-security-grid">
        <form className="panel security-panel" onSubmit={changePassword}>
          <div className="settings-card-heading">
            <div>
              <h2>Password</h2>
              <p>Changing it signs out every other active device.</p>
            </div>
            <KeyRound size={20} />
          </div>
          <label className="field">
            <span>Current password</span>
            <input
              autoComplete="current-password"
              name="current_password"
              required
              type="password"
            />
          </label>
          <label className="field">
            <span>New password</span>
            <input
              autoComplete="new-password"
              minLength={12}
              name="new_password"
              required
              type="password"
            />
          </label>
          <label className="field">
            <span>Confirm new password</span>
            <input
              autoComplete="new-password"
              minLength={12}
              name="confirm_password"
              required
              type="password"
            />
          </label>
          <button
            className="primary-button"
            disabled={busy === "password"}
            type="submit"
          >
            <ShieldCheck size={15} /> Change password
          </button>
        </form>

        <article className="panel security-panel mfa-panel">
          <div className="settings-card-heading">
            <div>
              <h2>Two-factor authentication</h2>
              <p>
                {mfa?.enabled
                  ? "A password and rotating code protect every new sign-in."
                  : "Add a rotating code from any standard authenticator app."}
              </p>
            </div>
            <ShieldCheck size={20} />
          </div>

          {!mfa?.enabled && !mfaSetup && (
            <form className="mfa-form" onSubmit={beginMfa}>
              <label className="field">
                <span>Confirm current password</span>
                <input
                  autoComplete="current-password"
                  name="current_password"
                  required
                  type="password"
                />
              </label>
              <button
                className="primary-button"
                disabled={busy === "mfa-setup"}
                type="submit"
              >
                <KeyRound size={15} /> Set up authenticator
              </button>
            </form>
          )}

          {!mfa?.enabled && mfaSetup && (
            <div className="mfa-enrollment">
              <p>
                Open this setup link on a phone with an authenticator app, or
                enter the key manually.
              </p>
              <a className="ghost-button" href={mfaSetup.otpauth_uri}>
                <KeyRound size={15} /> Open authenticator
              </a>
              <code className="mfa-secret">{mfaSetup.secret}</code>
              <form className="mfa-form" onSubmit={enableMfa}>
                <label className="field">
                  <span>Six-digit code</span>
                  <input
                    autoComplete="one-time-code"
                    autoFocus
                    inputMode="numeric"
                    maxLength={6}
                    minLength={6}
                    name="code"
                    placeholder="123456"
                    required
                  />
                </label>
                <button
                  className="primary-button"
                  disabled={busy === "mfa-enable"}
                  type="submit"
                >
                  <ShieldCheck size={15} /> Verify and enable
                </button>
              </form>
            </div>
          )}

          {mfa?.enabled && (
            <form className="mfa-form" onSubmit={manageMfa}>
              <div className="mfa-status-line">
                <span className="status-dot" />
                <strong>Protected</strong>
                <small>{mfa.recovery_codes_remaining} recovery codes left</small>
              </div>
              <label className="field">
                <span>Current password</span>
                <input
                  autoComplete="current-password"
                  name="current_password"
                  required
                  type="password"
                />
              </label>
              <label className="field">
                <span>Authenticator or recovery code</span>
                <input
                  autoComplete="one-time-code"
                  maxLength={32}
                  minLength={6}
                  name="code"
                  required
                />
              </label>
              <div className="mfa-actions">
                <button
                  className="ghost-button"
                  disabled={busy.startsWith("mfa-")}
                  name="action"
                  type="submit"
                  value="rotate"
                >
                  <RefreshCw size={14} /> Replace recovery codes
                </button>
                <button
                  className="danger-button"
                  disabled={busy.startsWith("mfa-")}
                  name="action"
                  type="submit"
                  value="disable"
                >
                  Disable
                </button>
              </div>
            </form>
          )}

          {recoveryCodes.length > 0 && (
            <div className="recovery-code-box">
              <strong>Save these one-time recovery codes</strong>
              <p>They will not be shown again. Each code works once.</p>
              <div className="recovery-code-grid">
                {recoveryCodes.map((code) => <code key={code}>{code}</code>)}
              </div>
              <button
                className="ghost-button"
                onClick={() => void copyRecoveryCodes()}
                type="button"
              >
                <ClipboardCopy size={14} /> Copy all codes
              </button>
            </div>
          )}
        </article>

        <article className="panel security-panel">
          <div className="settings-card-heading">
            <div>
              <h2>Active sessions</h2>
              <p>Review where your Raven account is currently signed in.</p>
            </div>
            <Laptop size={20} />
          </div>
          <div className="session-list">
            {sessions.map((session) => (
              <div className="session-row" key={session.id}>
                <span>
                  <Laptop size={16} />
                </span>
                <div>
                  <strong>
                    {deviceName(session.user_agent)}
                    {session.current && <em>Current</em>}
                  </strong>
                  <small>
                    Active{" "}
                    {new Intl.DateTimeFormat("en-US", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(session.last_seen_at))}
                  </small>
                </div>
                {!session.current && (
                  <button
                    aria-label={`Sign out ${deviceName(session.user_agent)}`}
                    className="icon-button"
                    disabled={busy === session.id}
                    onClick={() => void revokeSession(session)}
                    title="Sign out this device"
                  >
                    <LogOut size={15} />
                  </button>
                )}
              </div>
            ))}
          </div>
          <button
            className="ghost-button"
            disabled={busy === "sessions"}
            onClick={() => void revokeOthers()}
          >
            <Trash2 size={15} /> Sign out all other devices
          </button>
        </article>

        <article className="panel security-panel security-history-panel">
          <div className="settings-card-heading">
            <div>
              <h2>Account activity</h2>
              <p>Your latest security and financial changes.</p>
            </div>
            <History size={20} />
          </div>
          <div className="security-event-list">
            {securityEvents.slice(0, 12).map((event) => (
              <div className="security-event-row" key={event.id}>
                <span className={event.success ? "positive" : "negative"}>
                  {event.success ? <Check size={14} /> : <KeyRound size={14} />}
                </span>
                <div>
                  <strong>{securityEventLabel(event.event_type)}</strong>
                  <small>
                    {new Intl.DateTimeFormat("en-US", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(event.created_at))}
                    {event.ip_address ? ` · ${event.ip_address}` : ""}
                  </small>
                </div>
              </div>
            ))}
            {securityEvents.length === 0 && (
              <p className="empty-copy">New security activity will appear here.</p>
            )}
          </div>
        </article>
      </div>
    </section>
  );
}
