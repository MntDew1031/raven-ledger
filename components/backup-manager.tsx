"use client";

import {
  Check,
  Database,
  Download,
  LoaderCircle,
  ShieldAlert,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Backup = {
  name: string;
  created_at: string;
  bytes: number;
  sha256: string;
  app_version: string | null;
  encryption_fingerprint: string | null;
  row_counts: Record<string, number> | null;
  verified_at: string | null;
  verify_ok: boolean | null;
  verify_error: string | null;
};

type BackupList = {
  backups: Backup[];
  keep: number;
  directory: string;
  encryption_fingerprint: string;
  writable: boolean;
  error: string | null;
};

type VerifyResult = {
  ok: boolean;
  error: string | null;
  duration_ms: number | null;
  encryption_key_matches: boolean | null;
  expected_counts: Record<string, number>;
  restored_counts: Record<string, number>;
  shortfalls: Record<string, { expected: number; restored: number }>;
};

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function when(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

// A nightly backup that is over a day and a half old means the job stopped.
const STALE_AFTER_MS = 1000 * 60 * 60 * 36;
// Matches the server's grant window; the server is the authority either way.
const CONFIRM_WINDOW_MS = 5 * 60 * 1000;

function rows(counts: Record<string, number> | null): number {
  if (!counts) return 0;
  return counts.transactions ?? 0;
}

export function BackupManager({
  isOperator,
  mfaEnabled,
}: {
  isOperator: boolean;
  mfaEnabled: boolean;
}) {
  const [data, setData] = useState<BackupList | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verified, setVerified] = useState<
    Record<string, VerifyResult | undefined>
  >({});
  const [loadedAt] = useState(() => Date.now());
  // A password confirmation buys a few minutes of sensitive access. Kept in
  // state only as a hint for the UI — the server holds the real grant.
  const [confirmedUntil, setConfirmedUntil] = useState(0);
  const [pending, setPending] = useState<
    { action: "download" | "delete"; name: string } | null
  >(null);
  const [password, setPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");

  const load = useCallback(async () => {
    if (!isOperator) return;
    try {
      setData(await apiFetch<BackupList>("/system/backups"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load backups");
    }
  }, [isOperator]);

  useEffect(() => {
    if (!isOperator) return;
    let cancelled = false;
    apiFetch<BackupList>("/system/backups")
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(
            cause instanceof Error ? cause.message : "Could not load backups",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isOperator]);

  if (!isOperator) {
    return (
      <article className="panel settings-section">
        <Database className="positive" size={22} />
        <h2>Backups and exports</h2>
        <p>
          A database backup contains every household on this server, so it is
          managed by whoever runs it rather than by any household role. Your own
          household exports are always available here.
        </p>
        <div className="export-actions">
          <a className="ghost-button" href="/api/v1/households/export?format=csv">
            <Download size={14} /> Transactions CSV
          </a>
          <a className="ghost-button" href="/api/v1/households/export?format=json">
            <Download size={14} /> Household JSON
          </a>
        </div>
      </article>
    );
  }

  async function createBackup() {
    setBusy("create");
    setError(null);
    try {
      await apiFetch<Backup>("/system/backups", { method: "POST" });
      await load();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "The backup could not be taken",
      );
    } finally {
      setBusy(null);
    }
  }

  async function verify(name: string) {
    setBusy(name);
    setError(null);
    try {
      const result = await apiFetch<VerifyResult>(
        `/system/backups/${encodeURIComponent(name)}/verify`,
        { method: "POST" },
      );
      setVerified((current) => ({ ...current, [name]: result }));
      await load();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "The check could not be run",
      );
    } finally {
      setBusy(null);
    }
  }

  /**
   * Step up before anything leaves the machine or is destroyed.
   *
   * The grant lives on the server against this session and expires on its own;
   * `confirmedUntil` only decides whether to show the prompt again.
   */
  async function confirmPassword() {
    setError(null);
    try {
      await apiFetch("/system/operator/confirm", {
        method: "POST",
        body: JSON.stringify({ password, mfa_code: mfaCode || null }),
      });
      setPassword("");
      setMfaCode("");
      setConfirmedUntil(Date.now() + CONFIRM_WINDOW_MS);
      const action = pending;
      setPending(null);
      if (action?.action === "download") startDownload(action.name);
      if (action?.action === "delete") await remove(action.name, true);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "That password was not accepted",
      );
    }
  }

  function startDownload(name: string) {
    window.location.href = `/api/v1/system/backups/${encodeURIComponent(
      name,
    )}/download`;
  }

  function requestDownload(name: string) {
    if (Date.now() < confirmedUntil) {
      startDownload(name);
      return;
    }
    setPending({ action: "download", name });
  }

  async function remove(name: string, confirmed = false) {
    if (!confirmed && Date.now() >= confirmedUntil) {
      setPending({ action: "delete", name });
      return;
    }
    setBusy(name);
    try {
      await apiFetch(`/system/backups/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete it");
    } finally {
      setBusy(null);
    }
  }

  const latest = data?.backups[0];
  // Read the clock once, when the list arrives, rather than on every render:
  // a value that changes mid-render makes the component non-idempotent.
  const stale =
    latest !== undefined &&
    loadedAt - new Date(latest.created_at).getTime() > STALE_AFTER_MS;

  return (
    <article className="panel settings-section backup-settings">
      <Database className="positive" size={22} />
      <h2>Backups</h2>
      <p>
        A dump is written every night at 3:10 and immediately restored into a
        scratch database to prove it works. {data ? data.keep : 14} are kept.
      </p>

      {data && !data.writable && (
        <p className="negative ai-probe-result">
          <TriangleAlert size={13} /> {data.error}
        </p>
      )}

      {data && data.writable && (
        <p
          className={
            latest && !stale && latest.verify_ok
              ? "positive ai-probe-result"
              : "ai-probe-result subtle"
          }
        >
          {!latest ? (
            "No backup has been taken yet."
          ) : latest.verify_ok ? (
            <>
              <Check size={13} /> Last proven restorable {when(latest.verified_at)}
              {stale ? " — but the newest backup is over a day old." : "."}
            </>
          ) : latest.verify_ok === false ? (
            <>
              <ShieldAlert size={13} /> The newest backup failed its restore
              check: {latest.verify_error}
            </>
          ) : (
            "The newest backup has not been checked yet."
          )}
        </p>
      )}

      <div className="export-actions">
        <button
          className="ghost-button"
          disabled={busy !== null}
          onClick={() => void createBackup()}
          type="button"
        >
          {busy === "create" ? (
            <>
              <LoaderCircle className="spin" size={14} /> Backing up…
            </>
          ) : (
            <>
              <Database size={14} /> Back up now
            </>
          )}
        </button>
        <a className="ghost-button" href="/api/v1/households/export?format=csv">
          <Download size={14} /> Transactions CSV
        </a>
        <a className="ghost-button" href="/api/v1/households/export?format=json">
          <Download size={14} /> Household JSON
        </a>
      </div>

      {pending && (
        <form
          className="operator-confirm"
          onSubmit={(event) => {
            event.preventDefault();
            void confirmPassword();
          }}
        >
          <p>
            <ShieldAlert size={13} /> This archive holds every household on the
            server. Confirm your password{mfaEnabled ? " and MFA code" : ""} to{" "}
            {pending.action === "download" ? "download" : "delete"} it.
          </p>
          <div>
            <input
              aria-label="Your password"
              autoComplete="current-password"
              autoFocus
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Your password"
              type="password"
              value={password}
            />
            {mfaEnabled && (
              <input
                aria-label="Authentication or recovery code"
                autoComplete="one-time-code"
                onChange={(event) => setMfaCode(event.target.value)}
                placeholder="Authentication code"
                type="text"
                value={mfaCode}
              />
            )}
            <button className="primary-button" type="submit">
              Confirm
            </button>
            <button
              className="ghost-button"
              onClick={() => {
                setPending(null);
                setPassword("");
                setMfaCode("");
              }}
              type="button"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {error && <p className="negative ai-probe-result">{error}</p>}

      {data && data.backups.length > 0 && (
        <ul className="backup-list">
          {data.backups.map((backup) => {
            const result = verified[backup.name];
            const foreignKey =
              backup.encryption_fingerprint !== null &&
              backup.encryption_fingerprint !== data.encryption_fingerprint;
            return (
              <li className="backup-row" key={backup.name}>
                <div className="backup-row-main">
                  <span className="backup-when">{when(backup.created_at)}</span>
                  <span className="backup-meta">
                    {size(backup.bytes)} · {rows(backup.row_counts).toLocaleString()}{" "}
                    transactions
                    {backup.app_version ? ` · v${backup.app_version}` : ""}
                  </span>
                  {foreignKey && (
                    <span className="backup-meta negative">
                      <TriangleAlert size={12} /> Written under a different
                      encryption key — bank connections in it will not decrypt.
                    </span>
                  )}
                  {backup.verified_at && !result && (
                    <span
                      className={`backup-meta ${
                        backup.verify_ok ? "positive" : "negative"
                      }`}
                    >
                      {backup.verify_ok
                        ? `Restore checked ${when(backup.verified_at)}`
                        : backup.verify_error}
                    </span>
                  )}
                  {result && (
                    <span
                      className={`backup-meta ${
                        result.ok ? "positive" : "negative"
                      }`}
                    >
                      {result.ok
                        ? `Restored cleanly in ${result.duration_ms}ms — ` +
                          `${(
                            result.restored_counts.transactions ?? 0
                          ).toLocaleString()} transactions came back.`
                        : result.error}
                    </span>
                  )}
                </div>
                <div className="backup-row-actions">
                  <button
                    className="ghost-button"
                    disabled={busy !== null}
                    onClick={() => void verify(backup.name)}
                    type="button"
                  >
                    {busy === backup.name ? (
                      <LoaderCircle className="spin" size={13} />
                    ) : (
                      "Verify"
                    )}
                  </button>
                  <button
                    aria-label={`Download backup from ${when(
                      backup.created_at,
                    )}`}
                    className="ghost-button"
                    disabled={busy !== null}
                    onClick={() => requestDownload(backup.name)}
                    type="button"
                  >
                    <Download size={13} />
                  </button>
                  <button
                    aria-label={`Delete backup from ${when(backup.created_at)}`}
                    className="ghost-button danger"
                    disabled={busy !== null}
                    onClick={() => void remove(backup.name)}
                    type="button"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <p className="onboarding-note">
        Verifying restores into a throwaway database and never touches live
        data. Download a copy off this machine — a backup stored only on the
        host it protects is not a backup. To restore for real, run{" "}
        <code>./scripts/restore.sh &lt;file&gt;</code>.
      </p>
    </article>
  );
}
