"use client";

import { RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Undoable = {
  available: boolean;
  id?: string;
  kind?: string;
  summary?: string;
  created_at?: string;
  affects?: number;
};

/**
 * The way back from a bulk action.
 *
 * Shown after anything that changed several rows at once, because the reason
 * to hesitate before "apply all" is not knowing whether it can be taken back.
 * Polling is deliberately absent — the bar is refreshed by the pages that
 * cause actions, via the `raven:acted` event, so an idle tab is not asking the
 * server every few seconds whether a mistake has happened.
 */
export function UndoBar() {
  const [entry, setEntry] = useState<Undoable | null>(null);
  const [busy, setBusy] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    const check = () =>
      apiFetch<Undoable>("/activity/undoable")
        .then((result) => {
          if (!cancelled) setEntry(result);
        })
        .catch(() => {
          if (!cancelled) setEntry(null);
        });
    void check();
    // Refreshed by whatever caused an action rather than by polling, so an
    // idle tab is not asking the server every few seconds whether a mistake
    // has happened.
    const handler = () => void check();
    window.addEventListener("raven:acted", handler);
    return () => {
      cancelled = true;
      window.removeEventListener("raven:acted", handler);
    };
  }, []);

  if (notice) {
    return (
      <div className="undo-bar done" role="status">
        <RotateCcw size={14} /> {notice}
        <button
          aria-label="Dismiss"
          className="ghost-button"
          onClick={() => setNotice("")}
          type="button"
        >
          <X size={13} />
        </button>
      </div>
    );
  }

  if (!entry?.available || !entry.id || dismissed === entry.id) return null;

  return (
    <div className="undo-bar" role="status">
      <div>
        <strong>{entry.summary}</strong>
        {entry.affects ? <small>{entry.affects} transactions</small> : null}
      </div>
      <div className="undo-bar-actions">
        <button
          aria-label="Dismiss"
          className="ghost-button"
          onClick={() => setDismissed(entry.id ?? null)}
          type="button"
        >
          <X size={13} />
        </button>
        <button
          className="ghost-button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void apiFetch<{ restored: number; skipped: number }>(
              "/activity/undo",
              { method: "POST" },
            )
              .then((result) => {
                setNotice(
                  `Put back ${result.restored} change${result.restored === 1 ? "" : "s"}.` +
                    (result.skipped
                      ? ` ${result.skipped} had been edited since and were left alone.`
                      : ""),
                );
                setEntry(null);
                window.dispatchEvent(new Event("raven:undone"));
              })
              .finally(() => setBusy(false));
          }}
          type="button"
        >
          <RotateCcw size={13} /> Undo
        </button>
      </div>
    </div>
  );
}
