"use client";

import { Plus, Target, Trash2, TriangleAlert } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";
import { SelectField } from "@/components/select-field";
import { accountLabel } from "@/lib/accounts";

type Goal = {
  id: string;
  name: string;
  target_amount: string | number;
  target_date: string | null;
  account_id: string | null;
  saved_amount: string | number;
  remaining: string | number;
  progress_percent: number;
  months_left: number | null;
  monthly_needed: string | number | null;
  overdue: boolean;
  is_achieved: boolean;
  notes: string | null;
};

type Account = {
  id: string;
  name: string;
  kind: string;
  mask: string | null;
  owner_name: string | null;
};

function monthLabel(value: string | null): string {
  if (!value) return "";
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

/**
 * Things being saved for.
 *
 * The progress ring is decoration; the line beneath it is the feature. "$4,200
 * of $12,000" tells you nothing you could not see — "$650 a month to make June"
 * tells you whether to change something.
 */
export function GoalsManager() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [accountId, setAccountId] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [goalRows, accountRows] = await Promise.all([
      apiFetch<Goal[]>("/goals"),
      apiFetch<Account[]>("/accounts").catch(() => [] as Account[]),
    ]);
    setGoals(goalRows);
    setAccounts(accountRows.filter((item) => item.kind === "asset"));
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiFetch<Goal[]>("/goals"),
      apiFetch<Account[]>("/accounts").catch(() => [] as Account[]),
    ])
      .then(([goalRows, accountRows]) => {
        if (cancelled) return;
        setGoals(goalRows);
        setAccounts(accountRows.filter((item) => item.kind === "asset"));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await apiFetch("/goals", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          target_amount: Number(target || 0),
          target_date: targetDate || null,
          account_id: accountId || null,
          saved_amount: Number(saved || 0),
        }),
      });
      setName("");
      setTarget("");
      setTargetDate("");
      setAccountId("");
      setSaved("");
      setAdding(false);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save that");
    } finally {
      setBusy(false);
    }
  }

  async function remove(goal: Goal) {
    setBusy(true);
    try {
      await apiFetch(`/goals/${goal.id}`, { method: "DELETE" });
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function updateSaved(goal: Goal, amount: string) {
    await apiFetch(`/goals/${goal.id}`, {
      method: "PATCH",
      body: JSON.stringify({ saved_amount: Number(amount || 0) }),
    });
    await load();
  }

  return (
    <article className="panel goals-panel">
      <div className="settings-card-heading goals-heading">
        <div>
          <h2>
            <Target size={16} /> Saving for
          </h2>
          <p className="subtle">
            What you are putting money aside for, and what it takes each month
            to get there.
          </p>
        </div>
        {!adding && (
          <button
            className="ghost-button"
            onClick={() => setAdding(true)}
            type="button"
          >
            <Plus size={14} /> Add a goal
          </button>
        )}
      </div>

      {error && <p className="negative">{error}</p>}

      {adding && (
        <form className="goal-form" onSubmit={create}>
          <label className="field">
            <span>What for</span>
            <input
              autoFocus
              className="form-control"
              maxLength={120}
              onChange={(event) => setName(event.target.value)}
              placeholder="House deposit"
              required
              value={name}
            />
          </label>
          <div className="field-grid">
            <label className="field">
              <span>Target</span>
              <div className="money-input">
                <span>$</span>
                <input
                  min="1"
                  onChange={(event) => setTarget(event.target.value)}
                  placeholder="12000"
                  required
                  step="0.01"
                  type="number"
                  value={target}
                />
              </div>
            </label>
            <label className="field">
              <span>By when</span>
              <input
                className="form-control"
                onChange={(event) => setTargetDate(event.target.value)}
                type="date"
                value={targetDate}
              />
            </label>
          </div>
          <div className="field-grid">
            <div className="field">
              <span>Where it lives</span>
              <SelectField
                ariaLabel="Account holding this goal"
                onChange={setAccountId}
                options={[
                  { value: "", label: "Track it by hand" },
                  ...accounts.map((account) => ({
                    value: account.id,
                    label: accountLabel(account, accounts),
                  })),
                ]}
                value={accountId}
              />
            </div>
            {!accountId && (
              <label className="field">
                <span>Saved so far</span>
                <div className="money-input">
                  <span>$</span>
                  <input
                    min="0"
                    onChange={(event) => setSaved(event.target.value)}
                    placeholder="0.00"
                    step="0.01"
                    type="number"
                    value={saved}
                  />
                </div>
              </label>
            )}
          </div>
          <div className="dialog-actions">
            <button
              className="ghost-button"
              onClick={() => setAdding(false)}
              type="button"
            >
              Cancel
            </button>
            <button className="primary-button" disabled={busy} type="submit">
              Save goal
            </button>
          </div>
        </form>
      )}

      {goals.length === 0 && !adding ? (
        <p className="subtle goals-empty">
          Nothing yet. A goal is worth adding as soon as you know the number —
          Raven works out what it takes each month, and tells you when you drift
          behind.
        </p>
      ) : (
        <ul className="goal-list">
          {goals.map((goal) => {
            const pct = goal.progress_percent;
            return (
              <li
                className={`${goal.is_achieved ? "done" : ""}${goal.overdue ? " overdue" : ""}`}
                key={goal.id}
              >
                <div className="goal-top">
                  <div>
                    <strong>{goal.name}</strong>
                    <small>
                      {currency(Number(goal.saved_amount))} of{" "}
                      {currency(Number(goal.target_amount))}
                      {goal.target_date ? ` · ${monthLabel(goal.target_date)}` : ""}
                    </small>
                  </div>
                  <button
                    aria-label={`Delete ${goal.name}`}
                    className="ghost-button danger"
                    disabled={busy}
                    onClick={() => void remove(goal)}
                    type="button"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>

                <div
                  aria-label={`${Math.round(pct)} percent saved`}
                  className="goal-track"
                >
                  <span style={{ width: `${Math.max(pct, 1)}%` }} />
                </div>

                {/* The line that makes this worth having. */}
                <p className="goal-verdict">
                  {goal.is_achieved ? (
                    <>Done — {currency(Number(goal.target_amount))} put aside.</>
                  ) : goal.overdue ? (
                    <>
                      <TriangleAlert size={12} /> The date has passed with{" "}
                      {currency(Number(goal.remaining))} still to go. Worth
                      picking a new one.
                    </>
                  ) : goal.monthly_needed ? (
                    <>
                      <strong>{currency(Number(goal.monthly_needed))} a month</strong>{" "}
                      for {goal.months_left} more month
                      {goal.months_left === 1 ? "" : "s"} to make it.
                    </>
                  ) : (
                    <>
                      {currency(Number(goal.remaining))} to go. Add a date and
                      Raven will work out the monthly figure.
                    </>
                  )}
                </p>

                {!goal.account_id && !goal.is_achieved && (
                  <label className="goal-update">
                    <span>Saved so far</span>
                    <div className="money-input compact">
                      <span>$</span>
                      <input
                        aria-label={`Amount saved toward ${goal.name}`}
                        defaultValue={String(goal.saved_amount)}
                        min="0"
                        onBlur={(event) =>
                          void updateSaved(goal, event.target.value)
                        }
                        step="0.01"
                        type="number"
                      />
                    </div>
                  </label>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}
