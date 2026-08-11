"use client";

import {
  ArrowDown,
  ArrowUp,
  LoaderCircle,
  Pencil,
  Play,
  Plus,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Category } from "@/lib/finance";
import { currency } from "@/lib/format";

type MatchType = "exact" | "contains" | "regex";

export type CategorizationRule = {
  id: string;
  name: string;
  match_type: MatchType;
  merchant_pattern: string;
  min_amount: string | null;
  max_amount: string | null;
  category_id: string;
  category_name: string;
  priority: number;
  is_active: boolean;
};

type Preview = {
  scanned: number;
  matched: number;
  uncategorized_matched: number;
  samples: { merchant: string; amount: string; posted_date: string }[];
};

const MATCH_LABELS: Record<MatchType, string> = {
  contains: "Merchant contains",
  exact: "Merchant is exactly",
  regex: "Merchant matches regex",
};

function RuleDialog({
  categories,
  onClose,
  onSaved,
  rule,
}: {
  categories: Category[];
  onClose: () => void;
  onSaved: (message: string) => void;
  rule?: CategorizationRule;
}) {
  const [name, setName] = useState(rule?.name ?? "");
  const [matchType, setMatchType] = useState<MatchType>(
    rule?.match_type ?? "contains",
  );
  const [pattern, setPattern] = useState(rule?.merchant_pattern ?? "");
  const [categoryId, setCategoryId] = useState(
    rule?.category_id ?? categories[0]?.id ?? "",
  );
  const [minAmount, setMinAmount] = useState(rule?.min_amount ?? "");
  const [maxAmount, setMaxAmount] = useState(rule?.max_amount ?? "");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  // Live preview, debounced so typing does not spam the API.
  useEffect(() => {
    const timer = window.setTimeout(async () => {
      if (!pattern.trim()) {
        setPreview(null);
        return;
      }
      setPreviewBusy(true);
      try {
        const result = await apiFetch<Preview>("/rules/preview", {
          method: "POST",
          body: JSON.stringify({
            match_type: matchType,
            merchant_pattern: pattern,
            min_amount: minAmount || null,
            max_amount: maxAmount || null,
          }),
        });
        setPreview(result);
        setMessage("");
      } catch (reason) {
        setPreview(null);
        setMessage(
          reason instanceof Error ? reason.message : "Preview failed",
        );
      } finally {
        setPreviewBusy(false);
      }
    }, 450);
    return () => window.clearTimeout(timer);
  }, [pattern, matchType, minAmount, maxAmount]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    const body = {
      name: name.trim() || `${MATCH_LABELS[matchType]} "${pattern.trim()}"`,
      match_type: matchType,
      merchant_pattern: pattern.trim(),
      category_id: categoryId,
      min_amount: minAmount || null,
      max_amount: maxAmount || null,
    };
    try {
      if (rule) {
        await apiFetch(`/rules/${rule.id}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        onSaved("Rule updated.");
      } else {
        await apiFetch("/rules", { method: "POST", body: JSON.stringify(body) });
        onSaved("Rule created. It now runs before every other categorizer.");
      }
    } catch (reason) {
      setMessage(
        reason instanceof Error ? reason.message : "Could not save the rule",
      );
      setSaving(false);
    }
  }

  const groups = [...new Set(categories.map((item) => item.group_name))];

  return (
    <div className="dialog-layer">
      <button
        aria-label="Close dialog"
        className="dialog-backdrop"
        onClick={onClose}
        type="button"
      />
      <section
        aria-label={rule ? "Edit rule" : "Create rule"}
        aria-modal="true"
        className="account-dialog rule-dialog"
        role="dialog"
      >
        <div className="dialog-header">
          <div>
            <p className="eyebrow">{rule ? "Edit rule" : "New rule"}</p>
            <h2>{rule ? rule.name : "Categorize automatically"}</h2>
          </div>
          <button
            aria-label="Close"
            className="dialog-close"
            onClick={onClose}
            type="button"
          >
            <X size={16} />
          </button>
        </div>
        <form className="dialog-form" onSubmit={save}>
          <div className="field">
            <span>Rule name</span>
            <input
              maxLength={120}
              onChange={(event) => setName(event.target.value)}
              placeholder="Optional — named after the pattern if blank"
              type="text"
              value={name}
            />
          </div>
          <div className="field-grid">
            <div className="field">
              <label htmlFor="rule-match-type">Match</label>
              <select
                id="rule-match-type"
                onChange={(event) =>
                  setMatchType(event.target.value as MatchType)
                }
                value={matchType}
              >
                {Object.entries(MATCH_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <span>Pattern</span>
              <input
                maxLength={255}
                onChange={(event) => setPattern(event.target.value)}
                placeholder={
                  matchType === "regex" ? "^(uber|lyft)\\b" : "Chipotle"
                }
                required
                type="text"
                value={pattern}
              />
            </div>
          </div>
          <div className="field-grid">
            <div className="field">
              <span>Minimum amount (optional)</span>
              <input
                min="0"
                onChange={(event) => setMinAmount(event.target.value)}
                placeholder="0.00"
                step="0.01"
                type="number"
                value={minAmount}
              />
            </div>
            <div className="field">
              <span>Maximum amount (optional)</span>
              <input
                min="0"
                onChange={(event) => setMaxAmount(event.target.value)}
                placeholder="No limit"
                step="0.01"
                type="number"
                value={maxAmount}
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="rule-category">Assign category</label>
            <select
              id="rule-category"
              onChange={(event) => setCategoryId(event.target.value)}
              required
              value={categoryId}
            >
              {groups.map((group) => (
                <optgroup key={group} label={group}>
                  {categories
                    .filter((category) => category.group_name === group)
                    .map((category) => (
                      <option key={category.id} value={category.id}>
                        {category.name}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </div>

          <div className="rule-preview">
            {previewBusy ? (
              <p className="subtle">
                <LoaderCircle className="spin" size={12} /> Checking existing
                transactions…
              </p>
            ) : preview ? (
              <>
                <strong>
                  Matches {preview.matched} of your last {preview.scanned}{" "}
                  transactions
                  {preview.uncategorized_matched > 0 &&
                    ` (${preview.uncategorized_matched} uncategorized)`}
                </strong>
                {preview.samples.length > 0 && (
                  <ul>
                    {preview.samples.map((sample, index) => (
                      <li key={index}>
                        <span>{sample.merchant}</span>
                        <em>{currency(Number(sample.amount))}</em>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <p className="subtle">
                Type a pattern to see which transactions it would match.
              </p>
            )}
          </div>

          {message && (
            <p className="negative" role="alert">
              {message}
            </p>
          )}
          <div className="dialog-actions">
            <button className="ghost-button" onClick={onClose} type="button">
              Cancel
            </button>
            <button className="primary-button" disabled={saving} type="submit">
              {saving ? "Saving…" : rule ? "Save rule" : "Create rule"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export function RulesManager() {
  const [rules, setRules] = useState<CategorizationRule[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [role, setRole] = useState<"owner" | "member" | "viewer" | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [editing, setEditing] = useState<CategorizationRule | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<CategorizationRule | null>(null);
  const [busy, setBusy] = useState("");

  async function load() {
    try {
      const [ruleResult, categoryResult] = await Promise.all([
        apiFetch<CategorizationRule[]>("/rules"),
        apiFetch<Category[]>("/categories"),
      ]);
      setRules(ruleResult);
      setCategories(categoryResult);
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not load rules",
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
    Promise.all([
      apiFetch<CategorizationRule[]>("/rules"),
      apiFetch<Category[]>("/categories"),
    ])
      .then(([ruleResult, categoryResult]) => {
        if (cancelled) return;
        setRules(ruleResult);
        setCategories(categoryResult);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error ? reason.message : "Could not load rules",
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

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const canEdit = role !== null && role !== "viewer";
  const editParams = useMemo(
    () => ({ canEdit }),
    [canEdit],
  );

  async function toggleActive(rule: CategorizationRule) {
    setBusy(rule.id);
    try {
      await apiFetch(`/rules/${rule.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !rule.is_active }),
      });
      await load();
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Could not update the rule",
      );
    } finally {
      setBusy("");
    }
  }

  async function move(rule: CategorizationRule, direction: -1 | 1) {
    const index = rules.findIndex((item) => item.id === rule.id);
    const neighbor = rules[index + direction];
    if (!neighbor) return;
    setBusy(rule.id);
    try {
      // Swap priorities so the pair trade places.
      await apiFetch(`/rules/${rule.id}`, {
        method: "PATCH",
        body: JSON.stringify({ priority: neighbor.priority }),
      });
      await apiFetch(`/rules/${neighbor.id}`, {
        method: "PATCH",
        body: JSON.stringify({ priority: rule.priority }),
      });
      await load();
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Could not reorder rules",
      );
    } finally {
      setBusy("");
    }
  }

  async function removeRule(rule: CategorizationRule) {
    setBusy(rule.id);
    try {
      await apiFetch<void>(`/rules/${rule.id}`, { method: "DELETE" });
      setDeleting(null);
      setToast("Rule deleted. Already-categorized transactions are unchanged.");
      await load();
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Could not delete the rule",
      );
    } finally {
      setBusy("");
    }
  }

  async function runNow() {
    setBusy("run");
    try {
      const result = await apiFetch<{ queued: number }>("/rules/run", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setToast(
        result.queued
          ? `Categorizing ${result.queued} uncategorized transaction${result.queued === 1 ? "" : "s"}…`
          : "Rules queued. Nothing is currently uncategorized.",
      );
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Could not run rules",
      );
    } finally {
      setBusy("");
    }
  }

  if (loading) {
    return (
      <div className="account-loading">
        <LoaderCircle className="spin" size={21} />
        Loading rules…
      </div>
    );
  }

  return (
    <>
      {toast && <div className="toast">{toast}</div>}
      <div className="page-heading">
        <div>
          <p className="eyebrow">Automation</p>
          <h1>Rules run first, every time.</h1>
          <p className="subtle">
            Deterministic rules beat the keyword classifier and the AI. New
            transactions are matched top to bottom; the first hit wins.
          </p>
        </div>
        {editParams.canEdit && (
          <div className="heading-actions">
            <button
              className="ghost-button"
              disabled={busy === "run"}
              onClick={() => void runNow()}
              type="button"
            >
              <Play size={14} />
              {busy === "run" ? "Queuing…" : "Run rules now"}
            </button>
            <button
              className="primary-button"
              disabled={!categories.length}
              onClick={() => setCreating(true)}
              type="button"
            >
              <Plus size={15} /> New rule
            </button>
          </div>
        )}
      </div>

      {error && <div className="page-error">{error}</div>}

      {rules.length === 0 ? (
        <section className="panel rules-empty">
          <Wand2 size={20} />
          <strong>No rules yet</strong>
          <small>
            Rules categorize new transactions instantly and deterministically
            — for example, anything containing Chipotle is Dining. You can also
            create one from any transaction&apos;s edit dialog.
          </small>
        </section>
      ) : (
        <section className="data-panel">
          <table className="data-table rules-table">
            <thead>
              <tr>
                <th>Order</th>
                <th>Rule</th>
                <th>Condition</th>
                <th>Category</th>
                <th>Active</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rules.map((rule, index) => (
                <tr className={rule.is_active ? "" : "rule-inactive"} key={rule.id}>
                  <td data-label="Order">
                    <span className="rule-order">
                      {editParams.canEdit && (
                        <button
                          aria-label={`Move ${rule.name} earlier`}
                          className="rule-move"
                          disabled={index === 0 || busy === rule.id}
                          onClick={() => void move(rule, -1)}
                          type="button"
                        >
                          <ArrowUp size={12} />
                        </button>
                      )}
                      <em>{index + 1}</em>
                      {editParams.canEdit && (
                        <button
                          aria-label={`Move ${rule.name} later`}
                          className="rule-move"
                          disabled={index === rules.length - 1 || busy === rule.id}
                          onClick={() => void move(rule, 1)}
                          type="button"
                        >
                          <ArrowDown size={12} />
                        </button>
                      )}
                    </span>
                  </td>
                  <td data-label="Rule">
                    <strong>{rule.name}</strong>
                  </td>
                  <td data-label="Condition">
                    <span className="rule-condition">
                      {MATCH_LABELS[rule.match_type]}{" "}
                      <code>{rule.merchant_pattern}</code>
                      {rule.min_amount && ` · ≥ ${currency(Number(rule.min_amount))}`}
                      {rule.max_amount && ` · ≤ ${currency(Number(rule.max_amount))}`}
                    </span>
                  </td>
                  <td data-label="Category">
                    <span className="category-chip">{rule.category_name}</span>
                  </td>
                  <td data-label="Active">
                    {editParams.canEdit ? (
                      <button
                        aria-pressed={rule.is_active}
                        className={`rule-toggle ${rule.is_active ? "on" : ""}`}
                        disabled={busy === rule.id}
                        onClick={() => void toggleActive(rule)}
                        type="button"
                      >
                        {rule.is_active ? "On" : "Off"}
                      </button>
                    ) : (
                      <span>{rule.is_active ? "On" : "Off"}</span>
                    )}
                  </td>
                  <td data-label="Actions">
                    {editParams.canEdit && (
                      <span className="rule-actions">
                        <button
                          aria-label={`Edit ${rule.name}`}
                          className="icon-button"
                          onClick={() => setEditing(rule)}
                          type="button"
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          aria-label={`Delete ${rule.name}`}
                          className="icon-button"
                          onClick={() => setDeleting(rule)}
                          type="button"
                        >
                          <Trash2 size={13} />
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {(creating || editing) && (
        <RuleDialog
          categories={categories}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={(saved) => {
            setCreating(false);
            setEditing(null);
            setToast(saved);
            void load();
          }}
          rule={editing ?? undefined}
        />
      )}

      {deleting && (
        <div className="dialog-layer">
          <button
            aria-label="Close dialog"
            className="dialog-backdrop"
            onClick={() => setDeleting(null)}
            type="button"
          />
          <section
            aria-label="Delete rule"
            aria-modal="true"
            className="account-dialog"
            role="dialog"
          >
            <div className="dialog-header">
              <div>
                <p className="eyebrow">Delete rule</p>
                <h2>{deleting.name}</h2>
              </div>
            </div>
            <p className="auth-hint">
              New transactions will stop matching this rule. Transactions it
              already categorized keep their categories.
            </p>
            <div className="dialog-actions">
              <button
                className="ghost-button"
                onClick={() => setDeleting(null)}
                type="button"
              >
                Cancel
              </button>
              <button
                className="danger-button"
                disabled={busy === deleting.id}
                onClick={() => void removeRule(deleting)}
                type="button"
              >
                Delete rule
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
