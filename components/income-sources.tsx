"use client";

import {
  CalendarClock,
  LoaderCircle,
  Pencil,
  Plus,
  Trash2,
  Users,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";
import { SelectField } from "@/components/select-field";

type Cadence = "weekly" | "biweekly" | "semimonthly" | "monthly" | "annual";

type IncomeSource = {
  id: string;
  name: string;
  amount: string | number;
  cadence: Cadence;
  is_active: boolean;
  first_paid_on: string | null;
  notes: string | null;
  monthly_equivalent: string | number;
  cadence_label: string;
  extra_paycheque_months: number;
};

type Summary = { sources: IncomeSource[]; monthly_total: string | number };

const CADENCES = [
  { value: "biweekly", label: "Every 2 weeks" },
  { value: "semimonthly", label: "Twice a month" },
  { value: "weekly", label: "Every week" },
  { value: "monthly", label: "Monthly" },
  { value: "annual", label: "Yearly" },
];

// The cadences where "how many land in August" is a real question. Twice a
// month is twice in every month; every two weeks is not.
const NEEDS_AN_ANCHOR: Cadence[] = ["weekly", "biweekly"];

const BLANK = {
  name: "",
  amount: "",
  cadence: "biweekly" as Cadence,
  firstPaidOn: "",
};

/**
 * Who earns what, how often, and starting when.
 *
 * This replaces a single "expected monthly income" box, which could not
 * describe a household with two earners paid different amounts on different
 * schedules — and quietly invited the bi-weekly mistake, since the only way to
 * fill it was to work the total out by hand.
 *
 * **One real pay date turns an average into a count.** Without it the best
 * Raven can say is $4,441.02 a month; with it, it can say August holds two
 * paychecks and therefore $4,099.40, which is the number that matches the bank.
 */
export function IncomeSources({
  onTotalChange,
  onChanged,
}: {
  onTotalChange?: (total: number) => void;
  onChanged?: () => void;
}) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [draft, setDraft] = useState({ ...BLANK });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // null = closed, "new" = adding, otherwise the id being edited.
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    const result = await apiFetch<Summary>("/income-sources");
    setSummary(result);
    onTotalChange?.(Number(result.monthly_total));
    onChanged?.();
  }, [onTotalChange, onChanged]);

  useEffect(() => {
    let cancelled = false;
    apiFetch<Summary>("/income-sources")
      .then((result) => {
        if (cancelled) return;
        setSummary(result);
        onTotalChange?.(Number(result.monthly_total));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // Deliberately mount-only: re-running on every parent render would refetch
    // the list on each keystroke elsewhere in the budget form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startAdding() {
    setDraft({ ...BLANK });
    setError("");
    setOpen("new");
  }

  function startEditing(source: IncomeSource) {
    setDraft({
      name: source.name,
      amount: String(source.amount),
      cadence: source.cadence,
      firstPaidOn: source.first_paid_on ?? "",
    });
    setError("");
    setOpen(source.id);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const body = JSON.stringify({
      name: draft.name.trim(),
      amount: Number(draft.amount || 0),
      cadence: draft.cadence,
      // Empty string clears it, which is why the API reads `model_fields_set`
      // rather than testing for null — a field you can set but never unset is
      // a trap.
      first_paid_on: draft.firstPaidOn || null,
    });
    try {
      if (open === "new") {
        await apiFetch("/income-sources", { method: "POST", body });
      } else {
        await apiFetch(`/income-sources/${open}`, { method: "PATCH", body });
      }
      setOpen(null);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save that");
    } finally {
      setBusy(false);
    }
  }

  async function remove(source: IncomeSource) {
    setBusy(true);
    try {
      await apiFetch(`/income-sources/${source.id}`, { method: "DELETE" });
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not remove it");
    } finally {
      setBusy(false);
    }
  }

  if (!summary) return null;

  const active = summary.sources.filter((item) => item.is_active);
  const missingAnchor = active.filter(
    (item) => NEEDS_AN_ANCHOR.includes(item.cadence) && !item.first_paid_on,
  );

  const form = (
    <form className="income-add" onSubmit={save}>
      <input
        aria-label="Whose income"
        autoFocus
        maxLength={80}
        onChange={(event) =>
          setDraft((d) => ({ ...d, name: event.target.value }))
        }
        placeholder="Name"
        required
        value={draft.name}
      />
      <div className="money-input compact">
        <span>$</span>
        <input
          aria-label="Amount each payday"
          min="0"
          onChange={(event) =>
            setDraft((d) => ({ ...d, amount: event.target.value }))
          }
          placeholder="0.00"
          required
          step="0.01"
          type="number"
          value={draft.amount}
        />
      </div>
      <SelectField
        ariaLabel="How often"
        onChange={(value) =>
          setDraft((d) => ({ ...d, cadence: value as Cadence }))
        }
        options={CADENCES}
        value={draft.cadence}
      />
      {NEEDS_AN_ANCHOR.includes(draft.cadence) && (
        <label className="income-anchor">
          <span>Any one payday</span>
          <input
            aria-label="Any one payday"
            onChange={(event) =>
              setDraft((d) => ({ ...d, firstPaidOn: event.target.value }))
            }
            type="date"
            value={draft.firstPaidOn}
          />
          <small>
            Past or future, either works. It is what lets Raven count the
            paydays in a given month instead of averaging them.
          </small>
        </label>
      )}
      <div className="income-add-actions">
        <button
          className="ghost-button"
          onClick={() => setOpen(null)}
          type="button"
        >
          Cancel
        </button>
        <button className="primary-button" disabled={busy} type="submit">
          {busy ? <LoaderCircle className="spin" size={14} /> : null}
          {open === "new" ? "Add" : "Save"}
        </button>
      </div>
    </form>
  );

  return (
    <section className="income-sources">
      <div className="income-heading">
        <span>
          <Users size={13} /> Who earns what
        </span>
        <strong>{currency(Number(summary.monthly_total))} a month</strong>
      </div>

      {active.length > 0 && (
        <ul className="income-list">
          {active.map((source) =>
            open === source.id ? (
              <li className="income-editing" key={source.id}>
                {form}
              </li>
            ) : (
              <li key={source.id}>
                <div>
                  <strong>{source.name}</strong>
                  <small>
                    {currency(Number(source.amount))} {source.cadence_label}
                    {NEEDS_AN_ANCHOR.includes(source.cadence) &&
                      !source.first_paid_on && (
                        <em className="income-missing">
                          {" "}
                          · add a payday to count months exactly
                        </em>
                      )}
                  </small>
                </div>
                <span className="income-monthly">
                  {currency(Number(source.monthly_equivalent))}
                  <small>average a month</small>
                </span>
                <button
                  aria-label={`Edit ${source.name}`}
                  className="ghost-button"
                  disabled={busy}
                  onClick={() => startEditing(source)}
                  type="button"
                >
                  <Pencil size={13} />
                </button>
                <button
                  aria-label={`Remove ${source.name}`}
                  className="ghost-button danger"
                  disabled={busy}
                  onClick={() => void remove(source)}
                  type="button"
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ),
          )}
        </ul>
      )}

      {missingAnchor.length > 0 && (
        <p className="income-note">
          <CalendarClock size={13} />{" "}
          {missingAnchor.map((item) => item.name).join(" and ")} —{" "}
          {missingAnchor.length === 1 ? "this is" : "these are"} still an
          average. Add one real payday and the month figure becomes a count of
          actual paydays, so a two-paycheck month stops looking like a
          three-paycheck one.
        </p>
      )}

      {error && <p className="negative income-note">{error}</p>}

      {open === "new" ? (
        form
      ) : (
        <button
          className="ghost-button income-add-button"
          onClick={startAdding}
          type="button"
        >
          <Plus size={14} /> Add an earner
        </button>
      )}
    </section>
  );
}
