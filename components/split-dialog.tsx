"use client";

import { LoaderCircle, Plus, Scissors, Trash2, Undo2, X } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { SelectField } from "@/components/select-field";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";
import type { Category, Transaction } from "@/lib/finance";

type Line = {
  key: string;
  category_id: string;
  amount: string;
  notes: string;
};

let sequence = 0;
const nextKey = () => `line-${(sequence += 1)}`;

function toCents(value: string): number {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.round(parsed * 100);
}

function fromCents(cents: number): string {
  return (cents / 100).toFixed(2);
}

/**
 * Seed the editor with something worth editing.
 *
 * An existing split loads its own lines. A fresh one starts as two lines
 * holding the whole amount and nothing — not a 50/50 guess, which looks like
 * an answer and has to be undone before it can be corrected.
 */
function initialLines(transaction: Transaction): Line[] {
  if (transaction.splits.length > 0) {
    return transaction.splits.map((line) => ({
      key: nextKey(),
      category_id: line.category_id ?? "",
      amount: Number.parseFloat(line.amount).toFixed(2),
      notes: line.notes ?? "",
    }));
  }
  const total = toCents(transaction.amount);
  return [
    {
      key: nextKey(),
      category_id: transaction.category_id ?? "",
      amount: fromCents(total),
      notes: "",
    },
    { key: nextKey(), category_id: "", amount: "", notes: "" },
  ];
}

export function SplitDialog({
  transaction,
  categories,
  onClose,
  onSaved,
}: {
  transaction: Transaction;
  categories: Category[];
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [lines, setLines] = useState<Line[]>(() => initialLines(transaction));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const merchant =
    transaction.merchant_name || transaction.original_description;
  const totalCents = toCents(transaction.amount);
  const assignedCents = useMemo(
    () => lines.reduce((sum, line) => sum + toCents(line.amount), 0),
    [lines],
  );
  const remainingCents = totalCents - assignedCents;
  const balanced = remainingCents === 0;

  function update(key: string, patch: Partial<Line>) {
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    );
  }

  function addLine() {
    // Pre-fill the new line with whatever is still unassigned: the common case
    // is splitting a charge in two, and this makes that a single keystroke.
    setLines((current) => [
      ...current,
      {
        key: nextKey(),
        category_id: "",
        amount: remainingCents === 0 ? "" : fromCents(remainingCents),
        notes: "",
      },
    ]);
  }

  function removeLine(key: string) {
    setLines((current) => current.filter((line) => line.key !== key));
  }

  function assignRemainder(key: string) {
    const line = lines.find((item) => item.key === key);
    if (!line) return;
    update(key, { amount: fromCents(toCents(line.amount) + remainingCents) });
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await apiFetch<Transaction>(
        `/transactions/${transaction.id}/split`,
        {
          method: "PUT",
          body: JSON.stringify({
            lines: lines.map((line) => ({
              category_id: line.category_id || null,
              amount: line.amount,
              notes: line.notes.trim() || null,
            })),
          }),
        },
      );
      onSaved(`${merchant} was split into ${lines.length} lines.`);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "The split could not be saved",
      );
    } finally {
      setSaving(false);
    }
  }

  async function removeSplit() {
    setSaving(true);
    setError("");
    try {
      await apiFetch<Transaction>(`/transactions/${transaction.id}/split`, {
        method: "DELETE",
      });
      onSaved(`${merchant} is one transaction again.`);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "The split could not be removed",
      );
    } finally {
      setSaving(false);
    }
  }

  const options = [
    { value: "", label: "Uncategorized" },
    ...categories.map((item) => ({
      value: item.id,
      label: item.name,
      group: item.group_name,
      color: item.color,
    })),
  ];

  return (
    <div className="dialog-layer">
      <button
        aria-label="Close dialog"
        className="dialog-backdrop"
        onClick={onClose}
      />
      <section
        aria-label="Split transaction"
        aria-modal="true"
        className="account-dialog split-dialog"
        role="dialog"
      >
        <div className="dialog-header">
          <div>
            <p className="eyebrow">
              <Scissors size={12} /> Split
            </p>
            <h2>Divide this transaction</h2>
            <p>
              {merchant} · {currency(Number(transaction.amount))} — every line
              keeps its own category, and together they must add back up to the
              charge.
            </p>
          </div>
          <button aria-label="Close" className="dialog-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <form onSubmit={save}>
          <ul className="split-lines">
            {lines.map((line, index) => (
              <li className="split-line" key={line.key}>
                <SelectField
                  ariaLabel={`Category for line ${index + 1}`}
                  onChange={(next) => update(line.key, { category_id: next })}
                  options={options}
                  value={line.category_id}
                />
                <input
                  aria-label={`Amount for line ${index + 1}`}
                  inputMode="decimal"
                  onChange={(event) =>
                    update(line.key, { amount: event.target.value })
                  }
                  placeholder="0.00"
                  step="0.01"
                  type="number"
                  value={line.amount}
                />
                <input
                  aria-label={`Note for line ${index + 1}`}
                  maxLength={2000}
                  onChange={(event) =>
                    update(line.key, { notes: event.target.value })
                  }
                  placeholder="Note (optional)"
                  type="text"
                  value={line.notes}
                />
                <div className="split-line-actions">
                  {remainingCents !== 0 && (
                    <button
                      className="ghost-button"
                      onClick={() => assignRemainder(line.key)}
                      title="Give this line whatever is left over"
                      type="button"
                    >
                      {/* Magnitude only: the sign is already the
                          charge's, and "+-$10.00" reads as nonsense. */}
                      +{currency(Math.abs(remainingCents) / 100)}
                    </button>
                  )}
                  <button
                    aria-label={`Remove line ${index + 1}`}
                    className="ghost-button danger"
                    disabled={lines.length <= 2}
                    onClick={() => removeLine(line.key)}
                    type="button"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </li>
            ))}
          </ul>

          <div className="split-summary">
            <button className="ghost-button" onClick={addLine} type="button">
              <Plus size={13} /> Add line
            </button>
            <span className={balanced ? "positive" : "negative"}>
              {balanced
                ? "Balanced"
                : `${currency(Math.abs(remainingCents) / 100)} ${
                    // Compare magnitudes: on a purchase, lines totalling more
                    // than the charge are over-assigned even though the signed
                    // remainder is positive.
                    Math.abs(assignedCents) > Math.abs(totalCents)
                      ? "over"
                      : "left to assign"
                  }`}
            </span>
          </div>

          {error && <p className="dialog-error">{error}</p>}

          <div className="dialog-actions full">
            {transaction.is_split && (
              <button
                className="danger-text-button"
                disabled={saving}
                onClick={() => void removeSplit()}
                type="button"
              >
                <Undo2 size={13} /> Remove split
              </button>
            )}
            <button className="ghost-button" onClick={onClose} type="button">
              Cancel
            </button>
            <button
              className="primary-button"
              disabled={saving || !balanced}
              type="submit"
            >
              {saving ? (
                <>
                  <LoaderCircle className="spin" size={14} /> Saving…
                </>
              ) : (
                "Save split"
              )}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
