"use client";

import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Link2,
  LoaderCircle,
  MailPlus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wrench,
} from "lucide-react";
import Image from "next/image";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ApiKeysManager } from "@/components/api-keys-manager";
import { BackupManager } from "@/components/backup-manager";
import { PlaidLinkButton } from "@/components/plaid-link-button";
import { Account, accountBalance } from "@/lib/accounts";
import { apiFetch } from "@/lib/api";
import { SelectField } from "@/components/select-field";
import { currency } from "@/lib/format";
import { inviteLink } from "@/lib/onboarding";

type Member = {
  id: string;
  email: string;
  display_name: string;
  role: "owner" | "member" | "viewer";
  joined_at: string;
  avatar_url: string | null;
};

type PlaidStatus = {
  connections_in_use: number;
  connection_limit: number | null;
  connections_remaining: number | null;
  configured: boolean;
  environment: "sandbox" | "production";
  webhook_configured: boolean;
  redirect_uri_configured: boolean;
};

type Connection = {
  id: string;
  institution_name: string;
  status: string;
  account_count: number;
  last_synced_at: string | null;
  error_code: string | null;
  sync_stale: boolean;
};

type AiConfig = {
  model: string;
  model_source: string;
  min_batch_size: number;
  min_batch_source: string;
  // Null unless you are an operator: the URL is an address on the household's
  // own network, and an API key handed to another tool should not learn it.
  endpoint: string | null;
  endpoint_configured: boolean;
  batch_ceiling: number;
  // Whether this person may change any of it. False means the deployment has
  // not named them in OPERATOR_EMAILS.
  can_change: boolean;
  // Whether the server names *anybody* as operator. Distinguishes "you are not
  // on the list" from "there is no list", which need opposite actions.
  operator_configured: boolean;
};

const PREFERRED_AI_MODEL = "SP-gemma4:26b";

type AiStatus = {
  configured: boolean;
  model: string | null;
  probe_ok?: boolean | null;
  probe_latency_ms?: number | null;
  probe_error?: string | null;
};

type WorkerStatus = {
  online: boolean;
  last_seen_at: string | null;
  queued_jobs: number;
  heartbeat_ttl_seconds: number;
  ai_configured: boolean | null;
  ai_model: string | null;
  ai_config_matches_backend: boolean | null;
  ai_endpoint_matches_backend: boolean | null;
  ai_model_matches_backend: boolean | null;
  web_backups_enabled: boolean;
};

type InviteResponse = {
  invite_token: string;
  expires_at: string;
};

type PendingInvite = {
  id: string;
  invited_email: string;
  role: "owner" | "member" | "viewer";
  expires_at: string;
  created_at: string;
};

export function SettingsManager() {
  const [members, setMembers] = useState<Member[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [plaidStatus, setPlaidStatus] = useState<PlaidStatus | null>(null);
  const [worker, setWorker] = useState<WorkerStatus | null>(null);
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [aiProbe, setAiProbe] = useState<AiStatus | null>(null);
  const [probing, setProbing] = useState(false);
  const [aiModels, setAiModels] = useState<string[] | null>(null);
  const [aiConfig, setAiConfig] = useState<AiConfig | null>(null);
  const [aiConfigNotice, setAiConfigNotice] = useState("");
  const [aiConfigError, setAiConfigError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [repairing, setRepairing] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [localDisconnect, setLocalDisconnect] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [role, setRole] = useState<Member["role"] | null>(null);
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invite, setInvite] = useState<InviteResponse | null>(null);
  const [pendingInvites, setPendingInvites] = useState<PendingInvite[]>([]);

  const load = useCallback(async () => {
    try {
      const [
        memberResult,
        connectionResult,
        accountResult,
        statusResult,
        sessionResult,
        workerResult,
      ] = await Promise.all([
        apiFetch<Member[]>("/households/members"),
        apiFetch<Connection[]>("/plaid/connections"),
        apiFetch<Account[]>("/accounts"),
        apiFetch<PlaidStatus>("/plaid/status"),
        apiFetch<{ role: Member["role"]; user: { mfa_enabled: boolean } }>(
          "/auth/me",
        ),
        apiFetch<WorkerStatus>("/system/worker"),
      ]);
      setMembers(memberResult);
      setConnections(connectionResult);
      setAccounts(accountResult);
      setPlaidStatus(statusResult);
      setRole(sessionResult.role);
      setMfaEnabled(sessionResult.user.mfa_enabled);
      setWorker(workerResult);
      setPendingInvites(
        sessionResult.role === "owner"
          ? await apiFetch<PendingInvite[]>("/households/invites")
          : [],
      );
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not load settings",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    apiFetch<AiStatus>("/system/ai")
      .then((status) => {
        if (!cancelled) setAi(status);
      })
      .catch(() => {});
    // The current model and batch size, plus where each came from. Loaded up
    // front so the picker shows the truth rather than a placeholder.
    apiFetch<AiConfig>("/system/ai/config")
      .then((config) => {
        if (!cancelled) setAiConfig(config);
      })
      .catch(() => {});
    // The endpoint's own list, so the model is chosen rather than typed.
    apiFetch<{ ok: boolean; models: string[] }>("/system/ai/models")
      .then((found) => {
        if (!cancelled) setAiModels(found.ok ? found.models : []);
      })
      .catch(() => {});
    Promise.all([
      apiFetch<Member[]>("/households/members"),
      apiFetch<Connection[]>("/plaid/connections"),
      apiFetch<Account[]>("/accounts"),
      apiFetch<PlaidStatus>("/plaid/status"),
      apiFetch<{ role: Member["role"]; user: { mfa_enabled: boolean } }>(
        "/auth/me",
      ),
      apiFetch<WorkerStatus>("/system/worker"),
    ])
      .then(
        ([
          memberResult,
          connectionResult,
          accountResult,
          statusResult,
          sessionResult,
          workerResult,
        ]) => {
          if (cancelled) return;
          setMembers(memberResult);
          setConnections(connectionResult);
          setAccounts(accountResult);
          setPlaidStatus(statusResult);
          setRole(sessionResult.role);
          setMfaEnabled(sessionResult.user.mfa_enabled);
          setWorker(workerResult);
          if (sessionResult.role === "owner") {
            void apiFetch<PendingInvite[]>("/households/invites")
              .then((pending) => {
                if (!cancelled) setPendingInvites(pending);
              })
              .catch(() => {});
          } else {
            setPendingInvites([]);
          }
        },
      )
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error ? reason.message : "Could not load settings",
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

  const accountsByConnection = useMemo(() => {
    const result = new Map<string, Account[]>();
    for (const account of accounts) {
      if (!account.connection_id) continue;
      result.set(account.connection_id, [
        ...(result.get(account.connection_id) ?? []),
        account,
      ]);
    }
    return result;
  }, [accounts]);

  async function sync(connection: Connection) {
    setBusy(connection.id);
    setError("");
    try {
      await apiFetch(`/plaid/connections/${connection.id}/sync`, {
        method: "POST",
      });
      setNotice(`${connection.institution_name} sync was queued.`);
      await load();
      window.setTimeout(() => void load(), 2500);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start sync");
    } finally {
      setBusy("");
    }
  }

  async function removeConnection(connection: Connection, forceLocal = false) {
    setBusy(connection.id);
    setError("");
    try {
      await apiFetch<void>(
        `/plaid/connections/${connection.id}${forceLocal ? "?force_local=true" : ""}`,
        { method: "DELETE" },
      );
      setNotice(
        `${connection.institution_name} was disconnected. Its accounts are now manual.`,
      );
      setDisconnecting(null);
      setLocalDisconnect(null);
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not disconnect institution",
      );
      setLocalDisconnect(connection.id);
    } finally {
      setBusy("");
    }
  }

  async function createInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy("invite");
    setError("");
    try {
      const result = await apiFetch<InviteResponse>("/households/invites", {
        method: "POST",
        body: JSON.stringify({
          email: form.get("email"),
          role: form.get("role"),
        }),
      });
      setInvite(result);
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not create invitation",
      );
    } finally {
      setBusy("");
    }
  }

  async function revokeInvite(pending: PendingInvite) {
    setBusy(`invite-${pending.id}`);
    setError("");
    try {
      await apiFetch(`/households/invites/${pending.id}`, {
        method: "DELETE",
      });
      setNotice(`The invitation for ${pending.invited_email} was revoked.`);
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not revoke invitation",
      );
    } finally {
      setBusy("");
    }
  }

  /**
   * Change the model or the batch size.
   *
   * Applies immediately — the next categorization run and the next question
   * both pick it up, because both read the stored value rather than a
   * process-level constant.
   */
  async function saveAiConfig(patch: {
    model?: string;
    min_batch_size?: number;
  }) {
    setAiConfigNotice("");
    setAiConfigError("");
    try {
      const updated = await apiFetch<AiConfig>("/system/ai/config", {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      setAiConfig(updated);
      if (patch.model) {
        setAi((current) =>
          current ? { ...current, model: updated.model } : current,
        );
        // Saving queues an immediate worker status refresh. Give that small
        // background job a moment, then replace the stale pre-save diagnostic.
        window.setTimeout(() => {
          void apiFetch<WorkerStatus>("/system/worker")
            .then(setWorker)
            .catch(() => {});
        }, 1800);
      }
      setAiConfigNotice(
        patch.model
          ? `Now using ${updated.model}.`
          : `Sending ${updated.min_batch_size} merchants per request.`,
      );
    } catch (reason) {
      setAiConfigError(
        reason instanceof Error ? reason.message : "That change did not save",
      );
    }
  }

  async function testAi() {
    setProbing(true);
    setAiProbe(null);
    setAiModels(null);
    try {
      const result = await apiFetch<AiStatus>("/system/ai?probe=true");
      setAiProbe(result);
      // Whatever the outcome, listing the endpoint's models makes a wrong
      // LLM_MODEL immediately obvious.
      const discovered = await apiFetch<{ ok: boolean; models: string[] }>(
        "/system/ai/models",
      );
      setAiModels(discovered.ok ? discovered.models : []);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not test the AI endpoint",
      );
    } finally {
      setProbing(false);
    }
  }

  async function reopenChecklist() {
    setBusy("onboarding");
    setError("");
    try {
      await apiFetch("/onboarding/restore", { method: "POST" });
      window.location.assign("/welcome");
    } catch (reason) {
      setBusy("");
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not reopen the setup checklist",
      );
    }
  }

  async function copyInvite() {
    if (!invite) return;
    await navigator.clipboard.writeText(inviteLink(invite.invite_token));
    setNotice("Join link copied.");
  }

  // Two different powers, split on purpose. Adding a bank spends a shared
  // allowance, which is handled by showing what is left. Disconnecting one
  // destroys its synced history, which is not something to share.
  const canConnectBanks = role !== "viewer";
  const canDisconnectBanks = role === "owner";

  /**
   * A queued sync should finish in seconds. The backend decides when one has
   * gone stale; an offline worker makes it obvious immediately.
   */
  function syncLooksStuck(connection: Connection) {
    if (connection.status !== "syncing") return false;
    return connection.sync_stale || worker?.online === false;
  }

  if (loading) {
    return (
      <div className="account-loading">
        <LoaderCircle className="spin" size={21} />
        Loading household settings…
      </div>
    );
  }

  return (
    <>
      {error && (
        <div className="page-error settings-error">
          <AlertCircle size={16} />
          <span>{error}</span>
          <button className="ghost-button" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}
      {notice && (
        <div className="settings-notice">
          <Check size={15} /> {notice}
        </div>
      )}

      <section className="settings-grid">
        <article className="panel settings-section">
          <div className="settings-card-heading">
            <div>
              <h2>Household members</h2>
              <p>Everyone signs in independently to the shared household.</p>
            </div>
            <span className="settings-count">{members.length}</span>
          </div>
          <div className="settings-list">
            {members.map((member, index) => (
              <div className="member-row" key={member.id}>
                <div>
                  <span>
                    {member.avatar_url ? (
                      <Image
                        alt=""
                        height={36}
                        src={member.avatar_url}
                        unoptimized
                        width={36}
                      />
                    ) : (
                      member.display_name.slice(0, 1).toUpperCase()
                    )}
                  </span>
                  <div>
                    <strong>{member.display_name}</strong>
                    <small>
                      {member.email} · {member.role}
                      {index === 0 ? " · household creator" : ""}
                    </small>
                  </div>
                </div>
                <span className="status-pill positive">Active</span>
              </div>
            ))}
          </div>
          {role === "owner" && pendingInvites.length > 0 && (
            <div className="pending-invites">
              <div className="settings-card-heading compact-heading">
                <div>
                  <h3>Pending invitations</h3>
                  <p>Revoke any link that should no longer grant access.</p>
                </div>
                <span className="settings-count">{pendingInvites.length}</span>
              </div>
              <div className="settings-list">
                {pendingInvites.map((pending) => {
                  const expired = new Date(pending.expires_at) <= new Date();
                  return (
                    <div className="member-row" key={pending.id}>
                      <div>
                        <span>
                          <MailPlus size={16} />
                        </span>
                        <div>
                          <strong>{pending.invited_email}</strong>
                          <small>
                            {pending.role} · {expired ? "expired" : "expires"}{" "}
                            {new Intl.DateTimeFormat("en-US", {
                              month: "short",
                              day: "numeric",
                            }).format(new Date(pending.expires_at))}
                          </small>
                        </div>
                      </div>
                      <button
                        aria-label={`Revoke invitation for ${pending.invited_email}`}
                        className="icon-button danger-icon"
                        disabled={busy === `invite-${pending.id}`}
                        onClick={() => void revokeInvite(pending)}
                        title="Revoke invitation"
                        type="button"
                      >
                        {busy === `invite-${pending.id}` ? (
                          <LoaderCircle className="spin" size={14} />
                        ) : (
                          <Trash2 size={14} />
                        )}
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {role === "owner" && inviteOpen ? (
            <form className="invite-form" onSubmit={createInvite}>
              {invite ? (
                <>
                  <strong>Invitation created</strong>
                  <p>
                    Share this private join link with the invited person. Only
                    the email you entered can use it, and it expires{" "}
                    {new Intl.DateTimeFormat("en-US", {
                      month: "short",
                      day: "numeric",
                    }).format(new Date(invite.expires_at))}
                    .
                  </p>
                  <div className="invite-token">
                    <code>{inviteLink(invite.invite_token)}</code>
                    <button
                      aria-label="Copy join link"
                      className="icon-button"
                      onClick={() => void copyInvite()}
                      type="button"
                    >
                      <Copy size={14} />
                    </button>
                  </div>
                  <div className="dialog-actions">
                    <button
                      className="ghost-button"
                      onClick={() => {
                        setInvite(null);
                        setInviteOpen(false);
                      }}
                      type="button"
                    >
                      Done
                    </button>
                    <button
                      className="primary-button"
                      onClick={() => setInvite(null)}
                      type="button"
                    >
                      <MailPlus size={14} /> Create another
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <label className="field">
                    <span>Email address</span>
                    <input name="email" required type="email" />
                  </label>
                  <label className="field">
                    <span>Access level</span>
                    <select defaultValue="member" name="role">
                      <option value="member">Member — can make changes</option>
                      <option value="viewer">Viewer — read only</option>
                    </select>
                  </label>
                  <div className="dialog-actions">
                    <button
                      className="ghost-button"
                      onClick={() => setInviteOpen(false)}
                      type="button"
                    >
                      Cancel
                    </button>
                    <button
                      className="primary-button"
                      disabled={busy === "invite"}
                      type="submit"
                    >
                      <MailPlus size={14} /> Create invite
                    </button>
                  </div>
                </>
              )}
            </form>
          ) : (
            <div className="household-actions">
              {role === "owner" && (
                <button
                  className="ghost-button"
                  onClick={() => {
                    setInvite(null);
                    setInviteOpen(true);
                  }}
                >
                  <MailPlus size={15} /> Invite household member
                </button>
              )}
              <button
                className="ghost-button"
                disabled={busy === "onboarding"}
                onClick={() => void reopenChecklist()}
                type="button"
              >
                <Sparkles size={15} /> Reopen setup checklist
              </button>
            </div>
          )}
        </article>

        <article className="panel settings-section bank-settings">
          <div className="settings-card-heading">
            <div>
              <h2>Bank connections</h2>
              <p>Live Plaid institutions and the accounts attached to them.</p>
            </div>
            <span
              className={`settings-count${
                plaidStatus?.connections_remaining === 0 ? " negative" : ""
              }`}
              title={
                plaidStatus?.connection_limit
                  ? `${plaidStatus.connections_in_use} of ${plaidStatus.connection_limit} used`
                  : `${connections.length} connected`
              }
            >
              {plaidStatus?.connection_limit
                ? `${plaidStatus.connections_in_use} / ${plaidStatus.connection_limit}`
                : connections.length}
            </span>
          </div>

          {plaidStatus?.configured && (
            /* A running count, because the allowance is shared and spending
               the last one is not something to discover halfway through
               linking a bank. */
            <p className="connection-allowance">
              <strong>
                {plaidStatus.connections_in_use} bank connection
                {plaidStatus.connections_in_use === 1 ? "" : "s"} in use
              </strong>
              {plaidStatus.connection_limit ? (
                plaidStatus.connections_remaining === 0 ? (
                  <>
                    {" "}— that is all {plaidStatus.connection_limit} your plan
                    allows. Disconnect one you no longer need, or import a CSV
                    statement into a manual account instead.
                  </>
                ) : (
                  <>
                    {" "}of {plaidStatus.connection_limit} on your plan
                    {plaidStatus.connections_remaining !== null && (
                      <> · {plaidStatus.connections_remaining} left</>
                    )}
                  </>
                )
              ) : (
                <>
                  {" "}· set <code>PLAID_CONNECTION_LIMIT</code> to whatever
                  your Plaid plan allows and Raven will warn you before you run
                  out.
                </>
              )}
            </p>
          )}

          {plaidStatus?.configured ? (
            <div className="plaid-environment">
              <ShieldCheck size={14} />
              Plaid {plaidStatus.environment} is configured
              {!plaidStatus.webhook_configured && (
                <span> · webhook missing</span>
              )}
              {!plaidStatus.redirect_uri_configured && (
                <span> · OAuth redirect missing</span>
              )}
            </div>
          ) : (
            <div className="plaid-setup-warning">
              <AlertCircle size={17} />
              <div>
                <strong>Plaid credentials are not configured</strong>
                <p>
                  Add <code>PLAID_CLIENT_ID</code>, <code>PLAID_SECRET</code>,
                  and <code>PLAID_WEBHOOK_URL</code> to the backend and worker
                  environments, then redeploy both containers.
                </p>
              </div>
            </div>
          )}

          {worker && !worker.online && (
            <div className="plaid-setup-warning">
              <AlertCircle size={17} />
              <div>
                <strong>Background worker is not responding</strong>
                <p>
                  Syncing, categorization, and the scheduled refresh all run in
                  the worker container. Nothing will update until it is back.
                  {worker.queued_jobs > 0 &&
                    ` ${worker.queued_jobs} job${worker.queued_jobs === 1 ? "" : "s"} waiting.`}
                  {worker.last_seen_at
                    ? ` Last seen ${new Intl.DateTimeFormat("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      }).format(new Date(worker.last_seen_at))}.`
                    : " It has not checked in since the backend started."}
                </p>
              </div>
            </div>
          )}

          <div className="connection-list">
            {connections.map((connection) => {
              const connectedAccounts =
                accountsByConnection.get(connection.id) ?? [];
              const isExpanded = expanded === connection.id;
              return (
                <div className="connection-card" key={connection.id}>
                  <button
                    className="connection-summary"
                    onClick={() =>
                      setExpanded(isExpanded ? null : connection.id)
                    }
                  >
                    <span className="connection-logo">
                      {connection.institution_name.slice(0, 1).toUpperCase()}
                    </span>
                    <span>
                      <strong>{connection.institution_name}</strong>
                      <small>
                        {connection.account_count} account
                        {connection.account_count === 1 ? "" : "s"} ·{" "}
                        {connection.status}
                        {connection.error_code
                          ? ` · ${connection.error_code}`
                          : ""}
                      </small>
                    </span>
                    <span
                      className={`status-pill ${
                        connection.status === "healthy" ? "positive" : "negative"
                      }`}
                    >
                      {connection.status}
                    </span>
                    <ChevronDown
                      className={isExpanded ? "rotated" : ""}
                      size={16}
                    />
                  </button>
                  {isExpanded && (
                    <div className="connection-details">
                      <div className="connected-account-list">
                        {connectedAccounts.map((account) => (
                          <a
                            href={`/accounts?account=${account.id}`}
                            key={account.id}
                          >
                            <span>
                              <strong>{account.name}</strong>
                              <small>
                                {account.mask
                                  ? `Ending ${account.mask}`
                                  : account.type}
                              </small>
                            </span>
                            <strong
                              className={
                                account.kind === "liability" ? "negative" : ""
                              }
                            >
                              {currency(accountBalance(account))}
                            </strong>
                            <ChevronRight size={14} />
                          </a>
                        ))}
                      </div>
                      {syncLooksStuck(connection) && (
                        <p className="onboarding-note negative">
                          This sync was queued but has not completed. The
                          background worker may be offline or restarting.
                        </p>
                      )}
                      {repairing === connection.id ? (
                        <div className="repair-row">
                          <PlaidLinkButton
                            connectionId={connection.id}
                            label="Open Plaid to reconnect"
                            onConnected={() => {
                              setRepairing(null);
                              setNotice(
                                `${connection.institution_name} was reconnected.`,
                              );
                              void load();
                            }}
                          />
                          <button
                            className="text-button"
                            onClick={() => setRepairing(null)}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : canConnectBanks ? (
                        <div className="connection-actions">
                          <button
                            className="ghost-button"
                            disabled={busy === connection.id}
                            onClick={() => void sync(connection)}
                          >
                            <RefreshCw
                              className={
                                busy === connection.id ? "spin" : undefined
                              }
                              size={14}
                            />
                            Sync now
                          </button>
                          <button
                            className="ghost-button"
                            onClick={() => setRepairing(connection.id)}
                          >
                            <Wrench size={14} /> Reconnect
                          </button>
                          {canDisconnectBanks && (
                            <button
                              className="danger-text-button"
                              onClick={() => setDisconnecting(connection.id)}
                            >
                              <Trash2 size={14} /> Disconnect
                            </button>
                          )}
                        </div>
                      ) : (
                        <p className="onboarding-note">
                          Viewers can see this institution but cannot change
                          it.
                        </p>
                      )}
                      {disconnecting === connection.id && (
                        <div className="disconnect-confirm">
                          <div>
                            <strong>Disconnect {connection.institution_name}?</strong>
                            <p>
                              Plaid access will be revoked. Existing accounts
                              and history will remain as editable manual data.
                            </p>
                          </div>
                          <button
                            className="danger-button"
                            disabled={busy === connection.id}
                            onClick={() => void removeConnection(connection)}
                          >
                            Disconnect
                          </button>
                          {localDisconnect === connection.id && (
                            <button
                              className="ghost-button"
                              onClick={() =>
                                void removeConnection(connection, true)
                              }
                            >
                              Remove local connection only
                            </button>
                          )}
                          <button
                            className="text-button"
                            onClick={() => {
                              setDisconnecting(null);
                              setLocalDisconnect(null);
                            }}
                          >
                            Cancel
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            {!connections.length && (
              <div className="settings-empty">
                <Link2 size={19} />
                <strong>No connected institutions</strong>
                <small>
                  Connect Plaid or add manual accounts from the Accounts page.
                </small>
              </div>
            )}
          </div>
          {plaidStatus?.configured &&
            (canConnectBanks ? (
              <PlaidLinkButton
                onConnected={() => {
                  setNotice("Institution connected. Initial sync is running.");
                  window.setTimeout(() => void load(), 2000);
                }}
              />
            ) : (
              <p className="onboarding-note">
                Viewers can see every connected account and its transactions,
                but cannot connect a bank.
              </p>
            ))}
        </article>

        <article className="panel settings-section">
          <Sparkles className="positive" size={22} />
          <h2>AI assistant</h2>
          {ai?.configured ? (
            <>
              <p>
                A local AI endpoint is configured
                {ai.model ? (
                  <>
                    {" "}
                    using model <code>{ai.model}</code>
                  </>
                ) : null}
                . It suggests categories for unreviewed transactions and never
                approves anything by itself.
              </p>
              <div className="ai-health-grid">
                <span className={worker?.online ? "healthy" : "unhealthy"}>
                  <i />
                  <strong>Background worker</strong>
                  <small>{worker?.online ? "Online" : "Offline"}</small>
                </span>
                <span
                  className={
                    worker?.ai_configured === false
                      ? "unhealthy"
                      : worker?.ai_config_matches_backend === false
                        ? "attention"
                      : "healthy"
                  }
                >
                  <i />
                  <strong>Worker AI settings</strong>
                  <small>
                    {worker?.ai_config_matches_backend === false
                      ? worker.ai_model_matches_backend === false
                        ? `Using ${worker.ai_model || "another model"}`
                        : worker.ai_endpoint_matches_backend === false
                          ? "Endpoint differs from backend"
                          : "Settings fingerprint differs"
                      : worker?.ai_configured === false
                        ? "Not configured"
                        : worker?.ai_model || "Awaiting worker restart"}
                  </small>
                </span>
              </div>
              {worker?.ai_config_matches_backend === false && (
                <p className="ai-config-attention ai-probe-result">
                  {worker.ai_model_matches_backend === false
                    ? "The worker has not reported the saved model yet. It reads the shared choice before its next AI job, and this status should refresh shortly."
                    : worker.ai_endpoint_matches_backend === false
                      ? "The backend and worker use different LLM URLs. Set the same LLM_BASE_URL on both containers, then recreate them."
                      : "The backend and worker have different AI environment settings. Recreate both containers from the same configuration."}
                </p>
              )}
              <div className="export-actions">
                <button
                  className="ghost-button"
                  disabled={probing}
                  onClick={() => void testAi()}
                  type="button"
                >
                  {probing ? "Testing…" : "Test connection"}
                </button>
              </div>
              {aiProbe &&
                (aiProbe.probe_ok ? (
                  <p className="positive ai-probe-result">
                    Connected — replied in {aiProbe.probe_latency_ms}ms.
                  </p>
                ) : (
                  <p className="negative ai-probe-result">
                    {aiProbe.probe_error ?? "The endpoint did not respond."}
                  </p>
                ))}
              {aiConfig && (
                <div className="ai-model-picker">
                  <div className="settings-card-heading">
                    <h3>Which model to use</h3>
                    <p className="subtle">
                      Changed here rather than in the deployment, so trying
                      three of them is an evening rather than three restarts.
                      The batch size moves with it on purpose — the right value
                      depends entirely on the model. A 3B starts attaching
                      answers to the wrong transactions past about two at a
                      time; a large one handles a dozen.
                    </p>
                    {/* Said before the fields rather than after a failed save.
                        This choice applies to the whole install, not to one
                        household, so it is gated on the deployment's operator
                        list — and a picker that accepts a click and then
                        refuses it reads as a broken picker. */}
                    {!aiConfig.can_change &&
                      (aiConfig.operator_configured ? (
                        <p className="subtle">
                          Read-only here: the model is one choice for the whole
                          install, so it is changed by whoever runs the server.
                          This server has an operator, and your sign-in address
                          is not among them.
                        </p>
                      ) : (
                        <p className="subtle">
                          Read-only here: <strong>this server has no
                          operator</strong>, so nobody can change the model
                          from this page. Set <code>OPERATOR_EMAILS</code> to
                          your sign-in address in the deployment environment
                          and restart the backend.{" "}
                          <code>RAVEN_OPERATOR_EMAILS</code> works too — it is
                          the name Compose maps from, and either reaches the
                          same setting.
                        </p>
                      ))}
                  </div>
                  <div className="field-grid">
                    <div className="field">
                      <span>Model</span>
                      {aiModels && aiModels.length ? (
                        <SelectField
                          ariaLabel="Model to use"
                          disabled={!aiConfig.can_change}
                          onChange={(value: string) => void saveAiConfig({ model: value })}
                          options={[...aiModels]
                            .sort((a, b) =>
                              a === PREFERRED_AI_MODEL
                                ? -1
                                : b === PREFERRED_AI_MODEL
                                  ? 1
                                  : a.localeCompare(b),
                            )
                            .map((name) => ({
                              value: name,
                              label:
                                name === PREFERRED_AI_MODEL
                                  ? `${name} — preferred`
                                  : name,
                            }))}
                          value={aiConfig.model}
                        />
                      ) : (
                        <input
                          className="form-control"
                          defaultValue={aiConfig.model}
                          disabled={!aiConfig.can_change}
                          onBlur={(event) =>
                            void saveAiConfig({ model: event.target.value })
                          }
                        />
                      )}
                      <small className="field-help">
                        From {aiConfig.model_source}.
                        {aiConfig.model === PREFERRED_AI_MODEL
                          ? " This is Raven's preferred household model."
                          : ` ${PREFERRED_AI_MODEL} is the preferred household model.`}
                      </small>
                    </div>
                    <label className="field">
                      <span>Merchants per request</span>
                      <input
                        className="form-control"
                        defaultValue={aiConfig.min_batch_size}
                        disabled={!aiConfig.can_change}
                        max={aiConfig.batch_ceiling}
                        min={1}
                        onBlur={(event) =>
                          void saveAiConfig({
                            min_batch_size: Number(event.target.value),
                          })
                        }
                        type="number"
                      />
                      <small className="field-help">
                        From {aiConfig.min_batch_source}. Measured on a small
                        model: 2 gave nine right out of ten with none wrong, 4
                        gave eight with two wrong, for the same wall time.
                      </small>
                    </label>
                  </div>
                  {aiConfigNotice && (
                    <p className="positive ai-probe-result">{aiConfigNotice}</p>
                  )}
                  {aiConfigError && (
                    <p className="negative ai-probe-result">{aiConfigError}</p>
                  )}
                  <p className="subtle ai-endpoint-note">
                    {aiConfig.endpoint ? (
                      <>
                        Endpoint <code>{aiConfig.endpoint}</code>
                      </>
                    ) : (
                      <>
                        Endpoint{" "}
                        {aiConfig.endpoint_configured ? "configured" : "not set"}
                      </>
                    )}{" "}
                    — changed in the deployment, never here. A model name is a
                    choice between what this server already offers; an endpoint
                    is where your financial data gets sent.
                  </p>
                </div>
              )}
              {aiModels !== null && !aiModels.length && (
                <p className="ai-probe-result subtle">
                  The endpoint did not list any models, so the model has to be
                  typed rather than chosen.
                </p>
              )}
            </>
          ) : (
            <p>
              No local AI endpoint is configured. Set <code>LLM_BASE_URL</code>{" "}
              (and <code>LLM_MODEL</code> if your gateway routes by model name)
              on the backend and worker to enable category suggestions.
            </p>
          )}
        </article>

        <article className="panel settings-section">
          <ShieldCheck className="positive" size={22} />
          <h2>Security</h2>
          <p>
            Redis-backed sessions, encrypted provider tokens, household roles,
            secure cookies, and fail-closed page protection.
          </p>
          <div className="security-facts">
            <span>
              <Check size={13} /> Independent user logins
            </span>
            <span>
              <Check size={13} /> Household-scoped financial records
            </span>
            <span>
              <Check size={13} /> Encrypted Plaid access tokens
            </span>
          </div>
        </article>

        <ApiKeysManager isOwner={canDisconnectBanks} />
        <BackupManager
          isOperator={worker?.web_backups_enabled === true}
          mfaEnabled={mfaEnabled}
        />
      </section>
    </>
  );
}
