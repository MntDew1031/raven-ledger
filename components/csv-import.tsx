"use client";

import { AlertTriangle, FileUp, LoaderCircle, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";
import { prettyMerchant } from "@/lib/merchant";

type Row = {
  row: number;
  posted_date: string;
  amount: string;
  merchant: string;
  duplicate?: boolean;
};

type Preview = {
  rows: Row[];
  skipped: { row: number; reason: string }[];
  outflows: number;
  inflows: number;
  duplicates: number;
  all_one_direction: boolean;
  columns: Record<string, string | null>;
};

/**
 * Import a statement.
 *
 * The preview is the feature, not a nicety. Banks export wildly different
 * shapes, and reading a debit column as a credit inverts a whole statement —
 * rent becomes income and the month looks wonderful. So the file is parsed,
 * what Raven concluded is shown, and nothing is written until somebody agrees.
 */
export function CsvImport({
  accountId,
  accountName,
  onClose,
  onImported,
}: {
  accountId: string;
  accountName: string;
  onClose: () => void;
  onImported: (count: number) => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [skip, setSkip] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement | null>(null);

  async function read(file: File) {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await apiFetch<Preview>(
        `/transactions/import/preview?account_id=${accountId}`,
        { method: "POST", body: form },
      );
      setPreview(result);
      // Duplicates start deselected: importing the same file twice should be
      // boring rather than something to unpick afterwards.
      setSkip(new Set(result.rows.filter((r) => r.duplicate).map((r) => r.row)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not read that file");
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!preview) return;
    const rows = preview.rows.filter((r) => !skip.has(r.row));
    if (!rows.length) return;
    setBusy(true);
    try {
      const result = await apiFetch<{ imported: number }>(
        "/transactions/import/commit",
        {
          method: "POST",
          body: JSON.stringify({
            account_id: accountId,
            rows: rows.map((r) => ({
              posted_date: r.posted_date,
              amount: Number(r.amount),
              merchant: r.merchant,
            })),
          }),
        },
      );
      onImported(result.imported);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "That import failed");
      setBusy(false);
    }
  }

  const chosen = preview ? preview.rows.length - skip.size : 0;

  return (
    <div className="dialog-layer">
      <button aria-label="Close" className="dialog-backdrop" onClick={onClose} />
      <section aria-modal="true" className="account-dialog import-dialog" role="dialog">
        <div className="dialog-header">
          <div>
            <p className="eyebrow">
              <FileUp size={12} /> Import
            </p>
            <h2>Bring a statement into {accountName}</h2>
            <p>
              A CSV from your bank. Raven reads it and shows you what it found —
              nothing is added until you say so.
            </p>
          </div>
          <button aria-label="Close" className="dialog-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {!preview ? (
          <div className="import-drop">
            <input
              accept=".csv,text/csv"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void read(file);
              }}
              ref={fileInput}
              type="file"
            />
            <button
              className="primary-button"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
              type="button"
            >
              {busy ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}
              Choose a CSV
            </button>
            <small>
              Most banks offer one. Raven works out which columns are the date,
              the amount and the description.
            </small>
          </div>
        ) : (
          <>
            <div className="import-summary">
              <span>
                <strong>{preview.rows.length}</strong> rows read
              </span>
              <span>
                <strong>{preview.outflows}</strong> money out
              </span>
              <span>
                <strong>{preview.inflows}</strong> money in
              </span>
              {preview.duplicates > 0 && (
                <span>
                  <strong>{preview.duplicates}</strong> already here
                </span>
              )}
              {preview.skipped.length > 0 && (
                <span className="negative">
                  <strong>{preview.skipped.length}</strong> unreadable
                </span>
              )}
            </div>

            {preview.all_one_direction && (
              /* Almost always a misread sign column rather than a real
                 statement, so it is asked about rather than imported and
                 discovered a month later. */
              <p className="import-warning">
                <AlertTriangle size={14} /> Every row is going the same way.
                That usually means the amount column was read with the wrong
                sign — check a few below before importing.
              </p>
            )}

            <ul className="import-rows">
              {preview.rows.slice(0, 80).map((row) => (
                <li className={skip.has(row.row) ? "skipped" : ""} key={row.row}>
                  <input
                    aria-label={`Import ${row.merchant}`}
                    checked={!skip.has(row.row)}
                    onChange={() =>
                      setSkip((current) => {
                        const next = new Set(current);
                        if (next.has(row.row)) next.delete(row.row);
                        else next.add(row.row);
                        return next;
                      })
                    }
                    type="checkbox"
                  />
                  <span className="import-date">{row.posted_date}</span>
                  <span className="import-merchant">
                    {prettyMerchant(row.merchant)}
                    {row.duplicate && <em> already here</em>}
                  </span>
                  <span
                    className={Number(row.amount) < 0 ? "negative" : "positive"}
                  >
                    {currency(Number(row.amount))}
                  </span>
                </li>
              ))}
            </ul>
            {preview.rows.length > 80 && (
              <p className="subtle import-more">
                Showing the first 80 of {preview.rows.length}. All selected rows
                are imported.
              </p>
            )}

            {preview.skipped.length > 0 && (
              <details className="import-skipped">
                <summary>{preview.skipped.length} rows Raven could not read</summary>
                <ul>
                  {preview.skipped.slice(0, 20).map((s) => (
                    <li key={s.row}>
                      Row {s.row}: {s.reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}

        {error && <p className="dialog-error">{error}</p>}

        {preview && (
          <div className="dialog-actions">
            <button className="ghost-button" onClick={onClose} type="button">
              Cancel
            </button>
            <button
              className="primary-button"
              disabled={busy || !chosen}
              onClick={() => void commit()}
              type="button"
            >
              {busy ? <LoaderCircle className="spin" size={14} /> : null}
              Import {chosen} transaction{chosen === 1 ? "" : "s"}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
