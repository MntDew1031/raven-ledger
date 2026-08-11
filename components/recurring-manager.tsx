"use client";

import {
  BellOff,
  BellRing,
  LoaderCircle,
  RefreshCw,
  Repeat,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";

export type RecurringItem = {
  id: string;
  display_name: string;
  direction: "inflow" | "outflow";
  cadence: string;
  average_amount: string;
  last_amount: string;
  occurrences: number;
  last_seen: string;
  next_due: string;
  category_id: string | null;
  category_name: string | null;
  account_name: string | null;
  is_active: boolean;
};

const CADENCE_LABELS: Record<string, string> = {
  weekly: "Weekly",
  biweekly: "Every 2 weeks",
  monthly: "Monthly",
  bimonthly: "Every 2 months",
  quarterly: "Quarterly",
  yearly: "Yearly",
};

const MONTHLY_MULTIPLIERS: Record<string, number> = {
  weekly: 4.33,
  biweekly: 2.17,
  monthly: 1,
  bimonthly: 0.5,
  quarterly: 1 / 3,
  yearly: 1 / 12,
};

export function cadenceLabel(cadence: string) {
  return CADENCE_LABELS[cadence] ?? cadence;
}

function dueLabel(nextDue: string): { text: string; overdue: boolean } {
  const due = new Date(`${nextDue}T12:00:00`);
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  const days = Math.round((due.getTime() - today.getTime()) / 86_400_000);
  if (days < 0) return { text: `${-days}d overdue`, overdue: true };
  if (days === 0) return { text: "Due today", overdue: false };
  if (days === 1) return { text: "Due tomorrow", overdue: false };
  return {
    text: `Due ${new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
    }).format(due)}`,
    overdue: false,
  };
}

export function RecurringManager() {
  const [items, setItems] = useState<RecurringItem[]>([]);
  const [role, setRole] = useState<"owner" | "member" | "viewer" | null>(null);
  const [showMuted, setShowMuted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState("");

  async function load(includeMuted: boolean) {
    try {
      const result = await apiFetch<RecurringItem[]>(
        `/recurring?include_muted=${includeMuted}`,
      );
      setItems(result);
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not load recurring activity",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ role: "owner" | "member" | "viewer" }>("/auth/me")
      .then((session) => {
        if (!cancelled) setRole(session.role);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // load() lives outside the effect for reuse; its setters are async.
    const timer = window.setTimeout(() => void load(showMuted), 0);
    return () => window.clearTimeout(timer);
  }, [showMuted]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const canEdit = role !== null && role !== "viewer";

  const bills = useMemo(
    () => items.filter((item) => item.direction === "outflow"),
    [items],
  );
  const income = useMemo(
    () => items.filter((item) => item.direction === "inflow"),
    [items],
  );
  const monthlyEstimate = useMemo(
    () =>
      bills
        .filter((item) => item.is_active)
        .reduce((total, item) => {
          const amount = Number(item.average_amount);
          return total + amount * (MONTHLY_MULTIPLIERS[item.cadence] ?? 1);
        }, 0),
    [bills],
  );
  const monthlyIncomeEstimate = useMemo(
    () =>
      income
        .filter((item) => item.is_active)
        .reduce(
          (total, item) =>
            total +
            Number(item.average_amount) *
              (MONTHLY_MULTIPLIERS[item.cadence] ?? 1),
          0,
        ),
    [income],
  );
  const upcoming = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const horizon = new Date(today);
    horizon.setDate(horizon.getDate() + 30);
    return items
      .filter((item) => {
        if (!item.is_active) return false;
        const due = new Date(`${item.next_due}T12:00:00`);
        return due <= horizon;
      })
      .sort((a, b) => a.next_due.localeCompare(b.next_due))
      .slice(0, 6);
  }, [items]);
  const incomeCoverage = monthlyEstimate
    ? (monthlyIncomeEstimate / monthlyEstimate) * 100
    : null;

  async function detectNow() {
    setBusy("detect");
    try {
      await apiFetch("/recurring/detect", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setToast("Scanning your history for recurring activity…");
      window.setTimeout(() => void load(showMuted), 5000);
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Detection failed to queue",
      );
    } finally {
      setBusy("");
    }
  }

  async function toggleMute(item: RecurringItem) {
    setBusy(item.id);
    try {
      await apiFetch(`/recurring/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !item.is_active }),
      });
      setToast(
        item.is_active
          ? `${item.display_name} muted. It will stay out of upcoming bills.`
          : `${item.display_name} restored.`,
      );
      await load(showMuted);
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Could not update the item",
      );
    } finally {
      setBusy("");
    }
  }

  function renderTable(rows: RecurringItem[], emptyLabel: string) {
    if (!rows.length) {
      return <p className="subtle recurring-empty-note">{emptyLabel}</p>;
    }
    return (
      <table className="data-table recurring-table">
        <thead>
          <tr>
            <th>Merchant</th>
            <th>Cadence</th>
            <th>Average</th>
            <th>Next</th>
            <th>Category</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => {
            const due = dueLabel(item.next_due);
            return (
              <tr className={item.is_active ? "" : "rule-inactive"} key={item.id}>
                <td data-label="Merchant">
                  <strong>{item.display_name}</strong>
                  {item.account_name && <small>{item.account_name}</small>}
                </td>
                <td data-label="Cadence">{cadenceLabel(item.cadence)}</td>
                <td
                  className={item.direction === "inflow" ? "positive" : ""}
                  data-label="Average"
                >
                  {item.direction === "inflow" ? "+" : ""}
                  {currency(
                    Number(item.average_amount) *
                      (item.direction === "inflow" ? 1 : -1),
                  )}
                </td>
                <td data-label="Next">
                  <span className={due.overdue ? "negative" : undefined}>
                    {due.text}
                  </span>
                </td>
                <td data-label="Category">
                  <span className="category-chip">
                    {item.category_name ?? "Uncategorized"}
                  </span>
                </td>
                <td data-label="Actions">
                  {canEdit && (
                    <button
                      aria-label={
                        item.is_active
                          ? `Mute ${item.display_name}`
                          : `Restore ${item.display_name}`
                      }
                      className="icon-button"
                      disabled={busy === item.id}
                      onClick={() => void toggleMute(item)}
                      title={item.is_active ? "Mute" : "Restore"}
                      type="button"
                    >
                      {item.is_active ? (
                        <BellOff size={13} />
                      ) : (
                        <BellRing size={13} />
                      )}
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  }

  if (loading) {
    return (
      <div className="account-loading">
        <LoaderCircle className="spin" size={21} />
        Loading recurring activity…
      </div>
    );
  }

  return (
    <>
      {toast && <div className="toast">{toast}</div>}
      <div className="page-heading">
        <div>
          <p className="eyebrow">Recurring</p>
          <h1>Bills, subscriptions, and paychecks.</h1>
          <p className="subtle">
            Detected automatically from repeating merchants — steady cadence,
            steady amount. Mute anything that is not really recurring.
          </p>
        </div>
        <div className="heading-actions">
          <label className="toggle-inline">
            <input
              checked={showMuted}
              onChange={(event) => setShowMuted(event.target.checked)}
              type="checkbox"
            />
            Show muted
          </label>
          {canEdit && (
            <button
              className="primary-button"
              disabled={busy === "detect"}
              onClick={() => void detectNow()}
              type="button"
            >
              <RefreshCw
                className={busy === "detect" ? "spin" : undefined}
                size={14}
              />
              Detect now
            </button>
          )}
        </div>
      </div>

      {error && <div className="page-error">{error}</div>}

      {items.length > 0 && (
        <>
          <section className="recurring-summary" aria-label="Recurring plan summary">
            <span className="obligation">
              <small>Monthly bills</small>
              <strong>{currency(monthlyEstimate)}</strong>
            </span>
            <span className="wealth">
              <small>Recurring income</small>
              <strong>{currency(monthlyIncomeEstimate)}</strong>
            </span>
            <span className={incomeCoverage !== null && incomeCoverage >= 100 ? "wealth" : "want"}>
              <small>Income coverage</small>
              <strong>{incomeCoverage === null ? "—" : `${Math.round(incomeCoverage)}%`}</strong>
            </span>
            <span>
              <small>Due in 30 days</small>
              <strong>{upcoming.length}</strong>
            </span>
          </section>

          <section className="panel recurring-timeline">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Next 30 days</p>
                <h2>Your money timeline</h2>
              </div>
              <span className="subtle">Upcoming active items</span>
            </div>
            {upcoming.length ? (
              <div className="timeline-list">
                {upcoming.map((item) => {
                  const due = new Date(`${item.next_due}T12:00:00`);
                  return (
                    <article className={item.direction} key={item.id}>
                      <time dateTime={item.next_due}>
                        <small>
                          {new Intl.DateTimeFormat("en-US", { month: "short" }).format(due)}
                        </small>
                        <strong>{due.getDate()}</strong>
                      </time>
                      <span>
                        <strong>{item.display_name}</strong>
                        <small>{item.category_name ?? cadenceLabel(item.cadence)}</small>
                      </span>
                      <strong>
                        {item.direction === "inflow" ? "+" : "-"}
                        {currency(Number(item.average_amount))}
                      </strong>
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="subtle recurring-empty-note">
                Nothing active is expected in the next 30 days.
              </p>
            )}
          </section>
        </>
      )}

      {items.length === 0 && !error ? (
        <section className="panel rules-empty">
          <Repeat size={20} />
          <strong>Nothing recurring detected yet</strong>
          <small>
            Detection needs at least three occurrences of a merchant on a
            steady schedule. It runs automatically after every bank sync and
            nightly — or trigger it now.
          </small>
        </section>
      ) : (
        <div className="recurring-grid">
          <section className="data-panel">
            <div className="recurring-section-heading">
              <h2>Bills and subscriptions</h2>
              <span className="subtle">
                ≈ {currency(-monthlyEstimate)} per month
              </span>
            </div>
            {renderTable(bills, "No recurring bills detected.")}
          </section>
          <section className="data-panel">
            <div className="recurring-section-heading">
              <h2>Recurring income</h2>
            </div>
            {renderTable(income, "No recurring income detected.")}
          </section>
        </div>
      )}
    </>
  );
}
