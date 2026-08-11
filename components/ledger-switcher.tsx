"use client";

import {
  Check,
  FlaskConical,
  LoaderCircle,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "@/lib/api";

type Ledger = {
  id: string;
  name: string;
  role: string;
  is_sandbox: boolean;
  cloned_at: string | null;
};

function whenCloned(value: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * Move between the real ledger and disposable copies of it.
 *
 * The thing this has to get right is never leaving somebody unsure which one
 * they are in. A sandbox looks like the real thing by construction — that is
 * the point of it — so the app has to say so loudly and constantly, not once
 * at the moment of switching.
 *
 * The second thing, learned the hard way: they have to be *distinguishable*.
 * Several copies all called "Alex and Jordan (sandbox)" is not a list anybody
 * can choose from, so they arrive numbered and can be renamed for whatever is
 * being tried out in them.
 */
export function LedgerSwitcher({ currentName }: { currentName: string }) {
  const [open, setOpen] = useState(false);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  // Load on mount, not on open. The badge has to announce a sandbox the moment
  // the page appears — waiting until somebody opens this dialog would mean the
  // one time it matters, nobody has asked.
  useEffect(() => {
    let cancelled = false;
    apiFetch<Ledger[]>("/households/ledgers")
      .then((rows) => {
        if (!cancelled) setLedgers(rows);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const current = ledgers.find((item) => item.name === currentName);
  const real = ledgers.filter((item) => !item.is_sandbox);
  const sandboxes = ledgers.filter((item) => item.is_sandbox);

  async function reload() {
    setLedgers(await apiFetch<Ledger[]>("/households/ledgers"));
  }

  async function act(run: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await run();
      // Every figure on screen belongs to the ledger we just left, so a full
      // reload is the honest way to change ledgers rather than patching a
      // dozen caches and hoping none was missed.
      window.location.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That did not work");
      setBusy(false);
    }
  }

  /** Renaming and deleting change the list, not which ledger you are in. */
  async function inPlace(run: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await run();
      await reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That did not work");
    } finally {
      setBusy(false);
    }
  }

  function openLedger(id: string) {
    void act(() =>
      apiFetch("/households/switch", {
        method: "POST",
        body: JSON.stringify({ household_id: id }),
      }),
    );
  }

  function row(ledger: Ledger) {
    const here = ledger.name === currentName;
    const isRenaming = renaming === ledger.id;
    return (
      <li className={ledger.is_sandbox ? "sandbox" : ""} key={ledger.id}>
        {isRenaming ? (
          <form
            className="ledger-rename"
            onSubmit={(event) => {
              event.preventDefault();
              const name = renameValue.trim();
              if (!name) return;
              void inPlace(async () => {
                await apiFetch(`/households/sandboxes/${ledger.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({ name }),
                });
                setRenaming(null);
              });
            }}
          >
            <input
              aria-label={`Rename ${ledger.name}`}
              autoFocus
              maxLength={120}
              onChange={(event) => setRenameValue(event.target.value)}
              placeholder="What are you trying out?"
              value={renameValue}
            />
            <button aria-label="Save name" disabled={busy} type="submit">
              <Check size={14} />
            </button>
            <button
              aria-label="Cancel"
              onClick={() => setRenaming(null)}
              type="button"
            >
              <X size={14} />
            </button>
          </form>
        ) : (
          <>
            <button
              className="ledger-open"
              disabled={busy || here}
              onClick={() => openLedger(ledger.id)}
              type="button"
            >
              <strong>{ledger.name}</strong>
              <small>
                {here
                  ? "You are here"
                  : ledger.is_sandbox
                    ? `Copied ${whenCloned(ledger.cloned_at)}`
                    : "Your real ledger"}
              </small>
            </button>
            {ledger.is_sandbox && (
              <div className="ledger-row-actions">
                <button
                  aria-label={`Rename ${ledger.name}`}
                  className="ghost-button"
                  disabled={busy}
                  onClick={() => {
                    setRenaming(ledger.id);
                    setRenameValue(ledger.name);
                  }}
                  type="button"
                >
                  <Pencil size={13} />
                </button>
                <button
                  aria-label={`Delete ${ledger.name}`}
                  className="ghost-button danger"
                  disabled={busy}
                  onClick={() =>
                    void inPlace(() =>
                      apiFetch(`/households/sandboxes/${ledger.id}`, {
                        method: "DELETE",
                      }),
                    )
                  }
                  type="button"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            )}
          </>
        )}
      </li>
    );
  }

  const dialog = (
    <div className="dialog-layer">
      <button
        aria-label="Close dialog"
        className="dialog-backdrop"
        onClick={() => setOpen(false)}
      />
      <section
        aria-label="Ledgers"
        aria-modal="true"
        className="account-dialog ledger-dialog"
        role="dialog"
      >
        <div className="dialog-header">
          <div>
            <p className="eyebrow">
              <FlaskConical size={12} /> Ledgers
            </p>
            <h2>Work somewhere safe</h2>
            <p>
              A sandbox is a full copy of your ledger that you can change
              however you like and then throw away. It holds no bank
              connection, so it can never touch a real account.
            </p>
          </div>
          <button
            aria-label="Close"
            className="dialog-close"
            onClick={() => setOpen(false)}
          >
            <X size={18} />
          </button>
        </div>

        <ul className="ledger-list">{real.map(row)}</ul>

        <div className="ledger-section-heading">
          <h3>Sandboxes</h3>
          <span>{sandboxes.length} of 8</span>
        </div>
        {sandboxes.length ? (
          <ul className="ledger-list">{sandboxes.map(row)}</ul>
        ) : (
          <p className="subtle ledger-empty">
            None yet. Copy your ledger below and it will appear here to come
            back to whenever you like.
          </p>
        )}

        {error && <p className="dialog-error">{error}</p>}

        <form
          className="ledger-create"
          onSubmit={(event) => {
            event.preventDefault();
            void act(async () => {
              // Duplicating a sheet puts you in the duplicate. Staying in the
              // real ledger after pressing this reads as nothing having
              // happened at all.
              const made = await apiFetch<Ledger>("/households/sandboxes", {
                method: "POST",
                body: JSON.stringify({ name: newName.trim() || null }),
              });
              await apiFetch("/households/switch", {
                method: "POST",
                body: JSON.stringify({ household_id: made.id }),
              });
            });
          }}
        >
          <input
            aria-label="Name for the new sandbox"
            maxLength={120}
            onChange={(event) => setNewName(event.target.value)}
            placeholder="Name it — e.g. “What if we buy a house”"
            value={newName}
          />
          <button
            className="primary-button"
            disabled={busy || Boolean(current?.is_sandbox)}
            type="submit"
          >
            {busy ? (
              <LoaderCircle className="spin" size={14} />
            ) : (
              <Plus size={14} />
            )}
            Copy my ledger
          </button>
        </form>
        {current?.is_sandbox && (
          <p className="subtle ledger-empty">
            You are in a sandbox. Go back to your real ledger to make another
            copy — copying a copy would start from numbers you have already
            changed.
          </p>
        )}
      </section>
    </div>
  );

  return (
    <>
      <button
        aria-expanded={open}
        className={`ledger-button${current?.is_sandbox ? " sandbox" : ""}`}
        onClick={() => setOpen(true)}
        title="Switch ledger"
        type="button"
      >
        <FlaskConical size={14} />
        <span>{current?.is_sandbox ? "Sandbox" : "Ledgers"}</span>
      </button>

      {/* Portalled to <body> rather than rendered here. This button lives in
          `.topbar`, which sets `backdrop-filter` — and a filtered element
          becomes the containing block for `position: fixed` descendants, just
          as `transform` does. The dialog's `inset: 0` therefore resolved
          against a 62px-tall bar instead of the viewport, and `place-items:
          end` pushed it off the top of the screen: only the last few pixels of
          the create button were visible, and the list of sandboxes could not be
          reached at all.

          No mounted-guard is needed: `open` only becomes true from a click, so
          the server render never reaches this branch. */}
      {open && createPortal(dialog, document.body)}
    </>
  );
}
