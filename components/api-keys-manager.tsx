"use client";

import {
  Copy,
  Eye,
  KeyRound,
  LoaderCircle,
  PenLine,
  Trash2,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  can_write: boolean;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
};

type Created = ApiKey & { secret: string };

function when(value: string | null): string {
  if (!value) return "never";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "never";
  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function ApiKeysManager({ isOwner }: { isOwner: boolean }) {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [name, setName] = useState("");
  const [canWrite, setCanWrite] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!isOwner) return;
    try {
      setKeys(await apiFetch<ApiKey[]>("/households/api-keys"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load keys");
    }
  }, [isOwner]);

  useEffect(() => {
    if (!isOwner) return;
    let cancelled = false;
    apiFetch<ApiKey[]>("/households/api-keys")
      .then((rows) => {
        if (!cancelled) setKeys(rows);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [isOwner]);

  if (!isOwner) {
    return (
      <article className="panel settings-section">
        <KeyRound className="positive" size={22} />
        <h2>API keys</h2>
        <p className="onboarding-note">
          A key can read or change everything in this household, so keys are
          managed by its owner.
        </p>
      </article>
    );
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      const key = await apiFetch<Created>("/households/api-keys", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), can_write: canWrite }),
      });
      setCreated(key);
      setName("");
      setCanWrite(false);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create it");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(key: ApiKey) {
    setBusy(true);
    try {
      await apiFetch(`/households/api-keys/${key.id}`, { method: "DELETE" });
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not revoke it");
    } finally {
      setBusy(false);
    }
  }

  const live = keys.filter((key) => !key.revoked_at);

  return (
    <article className="panel settings-section api-keys">
      <KeyRound className="positive" size={22} />
      <h2>API keys</h2>
      <p>
        Give another tool its own key, so it can be revoked on its own. A
        read key answers questions about this ledger; a write key can also
        change it. No key can reach backups or create other keys.
      </p>

      <form className="api-key-form" onSubmit={create}>
        <input
          aria-label="What is this key for"
          maxLength={80}
          onChange={(event) => setName(event.target.value)}
          placeholder="What is it for? e.g. Open WebUI"
          required
          value={name}
        />
        <div className="api-key-scope" role="group" aria-label="What it may do">
          <button
            aria-pressed={!canWrite}
            className={!canWrite ? "active" : ""}
            onClick={() => setCanWrite(false)}
            type="button"
          >
            <Eye size={13} /> Read only
          </button>
          <button
            aria-pressed={canWrite}
            className={canWrite ? "active" : ""}
            onClick={() => setCanWrite(true)}
            type="button"
          >
            <PenLine size={13} /> Read and write
          </button>
        </div>
        <button className="primary-button" disabled={busy || !name.trim()} type="submit">
          {busy ? <LoaderCircle className="spin" size={14} /> : <KeyRound size={14} />}
          Create key
        </button>
      </form>

      {created && (
        <div className="api-key-secret" role="status">
          <p>
            <strong>Copy this now.</strong> It is the only time Raven can show
            it — only a hash is stored, so it cannot be recovered.
          </p>
          <code>{created.secret}</code>
          <div>
            <button
              className="ghost-button"
              onClick={() => {
                void navigator.clipboard?.writeText(created.secret);
                setCopied(true);
              }}
              type="button"
            >
              <Copy size={13} /> {copied ? "Copied" : "Copy"}
            </button>
            <button
              className="ghost-button"
              onClick={() => setCreated(null)}
              type="button"
            >
              Done
            </button>
          </div>
        </div>
      )}

      {error && <p className="negative ai-probe-result">{error}</p>}

      {live.length > 0 && (
        <ul className="api-key-list">
          {live.map((key) => (
            <li key={key.id}>
              <div>
                <strong>{key.name}</strong>
                <small>
                  <code>{key.prefix}…</code> ·{" "}
                  {key.can_write ? "read and write" : "read only"} · last used{" "}
                  {when(key.last_used_at)}
                </small>
              </div>
              <button
                aria-label={`Revoke ${key.name}`}
                className="ghost-button danger"
                disabled={busy}
                onClick={() => void revoke(key)}
                type="button"
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <p className="onboarding-note">
        Send it as <code>Authorization: Bearer …</code>, or{" "}
        <code>X-Raven-Key</code> if your tool reserves that header. Revoking
        takes effect on the key&apos;s next request.
      </p>
    </article>
  );
}
