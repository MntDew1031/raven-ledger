"use client";

import {
  Bookmark,
  Check,
  CheckCheck,
  ChevronRight,
  Download,
  Keyboard,
  LoaderCircle,
  Plus,
  RotateCcw,
  Scissors,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Account, accountLabel } from "@/lib/accounts";
import { apiFetch } from "@/lib/api";
import { SelectField } from "@/components/select-field";
import { SplitDialog } from "@/components/split-dialog";
import { Category, Tag, Transaction } from "@/lib/finance";
import { currency } from "@/lib/format";
import { prettyMerchant } from "@/lib/merchant";

type SavedTransactionView = {
  account: string;
  category: string;
  review: "all" | "needs-review" | "reviewed";
  source: string;
  start?: string;
  end?: string;
  direction?: "all" | "inflow" | "outflow";
  tag?: string;
  sort?: "newest" | "oldest" | "amount-high" | "amount-low";
};

function today() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function TransactionDialog({
  accounts,
  categories,
  tags,
  onClose,
  onSaved,
  onSplit,
  presetAccountId = "",
  transaction,
}: {
  accounts: Account[];
  categories: Category[];
  tags: Tag[];
  onClose: () => void;
  onSaved: (message: string) => void;
  onSplit?: (transaction: Transaction) => void;
  presetAccountId?: string;
  transaction?: Transaction;
}) {
  const existingAmount = Number(transaction?.amount ?? 0);
  const [merchant, setMerchant] = useState(
    transaction?.merchant_name || transaction?.original_description || "",
  );
  const [accountId, setAccountId] = useState(
    // A nudge that names an account opens the form already on it.
    transaction?.account_id || presetAccountId || accounts[0]?.id || "",
  );
  const [categoryId, setCategoryId] = useState(transaction?.category_id ?? "");
  const [date, setDate] = useState(transaction?.posted_date ?? today());
  const [direction, setDirection] = useState<"spending" | "income">(
    existingAmount > 0 ? "income" : "spending",
  );
  const [amount, setAmount] = useState(
    transaction ? String(Math.abs(existingAmount)) : "",
  );
  const [notes, setNotes] = useState(transaction?.notes ?? "");
  const [tagIds, setTagIds] = useState<string[]>(
    transaction?.tags?.map((tag) => tag.id) ?? [],
  );
  const [reviewed, setReviewed] = useState(transaction?.reviewed ?? true);
  const [createRule, setCreateRule] = useState(false);
  const [excluded, setExcluded] = useState(
    transaction?.excluded_from_budget ?? false,
  );
  /**
   * Which month's plan this counts against, as `YYYY-MM`, or "" for the month
   * it posted in.
   *
   * Rent is why. It is due on the 1st, so it comes out of the previous
   * month's pay and posts in the new month — which made August's Housing line
   * read as satisfied while the money had left in July, and nothing said to
   * set September's rent aside out of August's pay.
   */
  const [budgetMonth, setBudgetMonth] = useState(
    transaction?.budget_month ? transaction.budget_month.slice(0, 7) : "",
  );

  /**
   * The months worth offering, relative to the date this posted.
   *
   * Two either side is enough for the case this exists for — a bill paid a
   * month early or a month late — and a short list is readable where a full
   * date picker is not. The one he needs is labelled "the month before" so it
   * does not require working out which month that was.
   */
  const postedAt = new Date(`${date || "2000-01-01"}T12:00:00`);
  const monthValue = (offset: number) => {
    const d = new Date(postedAt.getFullYear(), postedAt.getMonth() + offset, 1);
    return {
      value: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
      label: new Intl.DateTimeFormat("en-US", {
        month: "long",
        year: "numeric",
      }).format(d),
    };
  };
  const postedMonthLabel = monthValue(0).label;
  const budgetMonthChoices = [
    { ...monthValue(-2), label: `${monthValue(-2).label} — two months before` },
    { ...monthValue(-1), label: `${monthValue(-1).label} — the month before` },
    { ...monthValue(1), label: `${monthValue(1).label} — the month after` },
  ];
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState("");
  const isManual = transaction?.is_manual ?? true;
  const isSplitParent = transaction?.is_split ?? false;

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", closeOnEscape);
    document.body.classList.add("dialog-open");
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.body.classList.remove("dialog-open");
    };
  }, [onClose]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const signedAmount =
      direction === "spending"
        ? -Math.abs(Number(amount))
        : Math.abs(Number(amount));
    try {
      if (createRule && categoryId && merchant.trim()) {
        // Fire-and-forget is not good enough here: surface failures.
        await apiFetch("/rules", {
          method: "POST",
          body: JSON.stringify({
            name: `Always categorize ${merchant.trim()}`,
            match_type: "contains",
            merchant_pattern: merchant.trim(),
            category_id: categoryId,
          }),
        });
      }
      if (transaction) {
        await apiFetch<Transaction>(`/transactions/${transaction.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            ...(isManual
              ? {
                  merchant_name: merchant.trim(),
                  account_id: accountId,
                  posted_date: date,
                  amount: signedAmount,
                }
              : {}),
            category_id: categoryId || null,
            notes: notes.trim() || null,
            reviewed,
            excluded_from_budget: excluded,
            budget_month: budgetMonth ? `${budgetMonth}-01` : null,
            tag_ids: tagIds,
          }),
        });
        onSaved(`${merchant} was updated.`);
      } else {
        await apiFetch<Transaction>("/transactions", {
          method: "POST",
          body: JSON.stringify({
            merchant_name: merchant.trim(),
            account_id: accountId,
            category_id: categoryId || null,
            posted_date: date,
            amount: signedAmount,
            notes: notes.trim() || null,
            reviewed,
            tag_ids: tagIds,
          }),
        });
        onSaved(`${merchant} was added.`);
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not save transaction",
      );
      setSaving(false);
    }
  }

  async function remove() {
    if (!transaction) return;
    setSaving(true);
    setError("");
    try {
      await apiFetch<void>(`/transactions/${transaction.id}`, {
        method: "DELETE",
      });
      onSaved(`${merchant} was deleted.`);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not delete transaction",
      );
      setSaving(false);
    }
  }

  return (
    <div className="dialog-layer">
      <button
        aria-label="Close dialog"
        className="dialog-backdrop"
        onClick={onClose}
      />
      <section
        aria-label={transaction ? "Edit transaction" : "Add transaction"}
        aria-modal="true"
        className="account-dialog"
        role="dialog"
      >
        <div className="dialog-header">
          <div>
            <p className="eyebrow">
              {transaction
                ? transaction.is_manual
                  ? "Manual transaction"
                  : "Plaid transaction"
                : "New transaction"}
            </p>
            <h2>{transaction ? "Review transaction" : "Add transaction"}</h2>
            <p>
              Plaid transaction details stay synced; organization and notes are
              always editable.
            </p>
          </div>
          <button aria-label="Close" className="dialog-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <form className="account-form transaction-form" onSubmit={save}>
          <label className="field full">
            <span>Merchant or description</span>
            <input
              disabled={!isManual}
              maxLength={255}
              onChange={(event) => setMerchant(event.target.value)}
              required
              value={merchant}
            />
          </label>
          <label className="field">
            <span>Account</span>
            <select
              disabled={!isManual}
              onChange={(event) => setAccountId(event.target.value)}
              required
              value={accountId}
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {accountLabel(account, accounts)}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Category</span>
            <select
              onChange={(event) => setCategoryId(event.target.value)}
              value={categoryId}
            >
              <option value="">Uncategorized</option>
              {Array.from(new Set(categories.map((item) => item.group_name))).map(
                (group) => (
                  <optgroup key={group} label={group}>
                    {categories
                      .filter((category) => category.group_name === group)
                      .map((category) => (
                        <option key={category.id} value={category.id}>
                          {category.name}
                        </option>
                      ))}
                  </optgroup>
                ),
              )}
            </select>
          </label>
          <div className="field full">
            <span>Transaction type</span>
            <div className="segmented-control">
              <button
                className={direction === "spending" ? "active spending" : ""}
                disabled={!isManual}
                onClick={() => setDirection("spending")}
                type="button"
              >
                Spending
              </button>
              <button
                className={direction === "income" ? "active income" : ""}
                disabled={!isManual}
                onClick={() => setDirection("income")}
                type="button"
              >
                Income
              </button>
            </div>
          </div>
          <label className="field">
            <span>Amount</span>
            <div className={`money-input ${!isManual ? "disabled" : ""}`}>
              <span>$</span>
              <input
                disabled={!isManual}
                min="0"
                onChange={(event) => setAmount(event.target.value)}
                required
                step="0.01"
                type="number"
                value={amount}
              />
            </div>
          </label>
          <label className="field">
            <span>Date</span>
            <input
              disabled={!isManual}
              onChange={(event) => setDate(event.target.value)}
              required
              type="date"
              value={date}
            />
          </label>
          <label className="field full">
            <span>Notes</span>
            <textarea
              maxLength={4000}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Add context for your household"
              value={notes}
            />
          </label>
          {tags.length > 0 && (
            <div className="field full">
              <span>Tags</span>
              <div className="transaction-tag-picker">
                {tags.map((tag) => (
                  <label
                    className={tagIds.includes(tag.id) ? "selected" : ""}
                    key={tag.id}
                    style={{ "--tag-color": tag.color } as React.CSSProperties}
                  >
                    <input
                      checked={tagIds.includes(tag.id)}
                      onChange={(event) =>
                        setTagIds((current) =>
                          event.target.checked
                            ? [...current, tag.id]
                            : current.filter((id) => id !== tag.id),
                        )
                      }
                      type="checkbox"
                    />
                    <i /> {tag.name}
                  </label>
                ))}
              </div>
              <small className="field-help">
                Manage reusable tags from the Categories page.
              </small>
            </div>
          )}
          <label className="toggle-row full">
            <input
              checked={reviewed}
              onChange={(event) => setReviewed(event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>Mark as reviewed</strong>
              <small>Remove this transaction from your review queue.</small>
            </span>
          </label>
          <label className="toggle-row full">
            <input
              checked={excluded}
              onChange={(event) => setExcluded(event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>Exclude from budget and reports</strong>
              <small>Useful for reimbursements and exceptional activity.</small>
            </span>
          </label>
          {/* A `<select>`, not `<input type="month">`. **Safari does not
              implement the month input** — it degrades silently to a plain
              text box with no picker and no hint, which is exactly what Alex
              got: "what do i even put in this field?". Named months also say
              what the choice means, which a bare `2026-07` does not. */}
          <label className="field full">
            <span>Count in a different budget month</span>
            <select
              onChange={(event) => setBudgetMonth(event.target.value)}
              value={budgetMonth}
            >
              <option value="">
                {postedMonthLabel} — the month it posted in
              </option>
              {budgetMonthChoices.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {choice.label}
                </option>
              ))}
            </select>
            <small className="field-help">
              {budgetMonth
                ? `Counts against that month's plan. Reports still show it on ${date} — this changes the budget only.`
                : "For a bill paid out of last month's pay. Rent due on the 1st comes from the previous month, so counting it there leaves this month's plan showing what you still need to set aside."}
              {/* The lines are what the budget counts — the charge itself is
                  excluded from every total — so say plainly that moving the
                  charge moves all of them. One Venmo payment split five ways
                  is exactly the case this is for. */}
              {isSplitParent && (
                <>
                  {" "}
                  All {transaction?.splits?.length ?? 0} lines of this split move
                  with it.
                </>
              )}
            </small>
          </label>
          {categoryId && merchant.trim() && (
            <label className="toggle-row full">
              <input
                checked={createRule}
                onChange={(event) => setCreateRule(event.target.checked)}
                type="checkbox"
              />
              <span>
                <strong>Always categorize “{merchant.trim()}” like this</strong>
                <small>
                  Creates a rule so future matching transactions are
                  categorized automatically. Manage rules in the Rules page.
                </small>
              </span>
            </label>
          )}
          {error && <p className="form-error full">{error}</p>}
          {transaction?.is_manual && (
            <div className="account-danger-zone full">
              {confirmDelete ? (
                <div>
                  <span>
                    <strong>Delete this manual transaction?</strong>
                    <small>This cannot be undone.</small>
                  </span>
                  <button
                    className="danger-button"
                    disabled={saving}
                    onClick={() => void remove()}
                    type="button"
                  >
                    <Trash2 size={14} /> Delete
                  </button>
                  <button
                    className="text-button"
                    onClick={() => setConfirmDelete(false)}
                    type="button"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  className="danger-text-button"
                  onClick={() => setConfirmDelete(true)}
                  type="button"
                >
                  <Trash2 size={14} /> Delete transaction
                </button>
              )}
            </div>
          )}
          <div className="dialog-actions full">
            {/* Splitting lives here rather than in the row: it is a rare,
                deliberate action, and the row has no space left for it on a
                phone. Here there is room to say what it does. */}
            {transaction && onSplit && !transaction.parent_transaction_id && (
              <button
                className="ghost-button"
                onClick={() => onSplit(transaction)}
                type="button"
              >
                <Scissors size={13} />
                {transaction.is_split ? "Edit split" : "Split across categories"}
              </button>
            )}
            <button className="ghost-button" onClick={onClose} type="button">
              Cancel
            </button>
            <button className="primary-button" disabled={saving} type="submit">
              {saving ? (
                <LoaderCircle className="spin" size={15} />
              ) : (
                <Check size={15} />
              )}
              Save transaction
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

type AiProgress = {
  state: "idle" | "queued" | "running" | "done" | "failed";
  total: number;
  processed: number;
  suggested: number;
  abstained: number;
  invalid: number;
  remaining: number;
  failed_batches: number;
  merchants: number;
  merchants_done: number;
  updated_at: number;
  started_at: number;
  error: string | null;
};

type WorkerStatus = {
  online: boolean;
  queued_jobs: number;
  ai_configured: boolean | null;
  ai_model: string | null;
  ai_config_matches_backend: boolean | null;
  ai_endpoint_matches_backend: boolean | null;
  ai_model_matches_backend: boolean | null;
};

// Why a category is already filled in. Worth showing: a person reviewing a
// row decides differently when the answer came from their own past choice
// than when a model guessed it. Sources with nothing useful to say — a manual
// edit, the keyword table — deliberately show no chip.
const SOURCE_CHIPS: Record<string, { label: string; title: string; tone: string }> = {
  ai: {
    label: "AI",
    title: "Suggested by your local AI. Nothing is approved until you say so.",
    tone: "ai-chip",
  },
  merchant_memory: {
    label: "Learned",
    title: "Applied from how you categorized this merchant before.",
    tone: "ai-chip source-chip-learned",
  },
  provider_category: {
    label: "Bank",
    title: "Taken from your bank's own category for this transaction.",
    tone: "ai-chip source-chip-bank",
  },
  household_rule: {
    label: "Rule",
    title: "Matched one of your categorization rules.",
    tone: "ai-chip source-chip-rule",
  },
};

function sourceChip(source: string | null) {
  const chip = source ? SOURCE_CHIPS[source] : undefined;
  if (!chip) return null;
  return (
    <em className={chip.tone} title={chip.title}>
      {chip.label}
    </em>
  );
}

export function TransactionManager() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [account, setAccount] = useState("");
  const [source, setSource] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [direction, setDirection] = useState<"all" | "inflow" | "outflow">("all");
  const [tag, setTag] = useState("");
  const [sort, setSort] = useState<"newest" | "oldest" | "amount-high" | "amount-low">("newest");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkCategory, setBulkCategory] = useState("");
  const [review, setReview] = useState<"all" | "needs-review" | "reviewed">(
    () =>
      typeof window !== "undefined" &&
      new URLSearchParams(window.location.search).get("review") ===
        "needs-review"
        ? "needs-review"
        : "all",
  );
  const [role, setRole] = useState<"owner" | "member" | "viewer" | null>(null);
  const [aiConfigured, setAiConfigured] = useState(false);
  const [worker, setWorker] = useState<WorkerStatus | null>(null);
  const [rowBusy, setRowBusy] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiProgress, setAiProgress] = useState<AiProgress | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [editing, setEditing] = useState<Transaction | null>(null);
  const [splitting, setSplitting] = useState<Transaction | null>(null);
  const [adding, setAdding] = useState(false);
  // Set by the dashboard nudge deep-link so the form opens on that account.
  const [presetAccountId, setPresetAccountId] = useState<string>("");
  const [savedView, setSavedView] = useState<SavedTransactionView | null>(null);

  useEffect(() => {
    let frame: number | undefined;
    try {
      const stored = window.localStorage.getItem("raven-transaction-view");
      if (stored) {
        const parsed = JSON.parse(stored) as SavedTransactionView;
        frame = window.requestAnimationFrame(() => setSavedView(parsed));
      }
    } catch {
      // A malformed local preference should never block transaction review.
    }
    return () => {
      if (frame !== undefined) window.cancelAnimationFrame(frame);
    };
  }, []);

  async function load() {
    try {
      const [transactionResult, accountResult, categoryResult, tagResult] =
        await Promise.all([
          apiFetch<Transaction[]>(
        "/transactions?limit=500&include_split_lines=true",
      ),
          apiFetch<Account[]>("/accounts"),
          apiFetch<Category[]>("/categories"),
          apiFetch<Tag[]>("/categories/tags"),
        ]);
      setTransactions(transactionResult);
      setAccounts(accountResult);
      setCategories(categoryResult);
      setTags(tagResult);
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not load transactions",
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
      apiFetch<{ configured: boolean }>("/system/ai"),
      apiFetch<WorkerStatus>("/system/worker"),
      apiFetch<AiProgress>("/transactions/ai-review/progress"),
    ])
      .then(([status, workerStatus, progress]) => {
        if (cancelled) return;
        setAiConfigured(status.configured);
        setWorker(workerStatus);
        if (progress.state !== "idle") setAiProgress(progress);
        if (progress.state === "queued" || progress.state === "running") {
          setAiBusy(true);
        }
      })
      .catch(() => {});
    Promise.all([
      apiFetch<Transaction[]>(
        "/transactions?limit=500&include_split_lines=true",
      ),
      apiFetch<Account[]>("/accounts"),
      apiFetch<Category[]>("/categories"),
      apiFetch<Tag[]>("/categories/tags"),
    ])
      .then(([transactionResult, accountResult, categoryResult, tagResult]) => {
        if (cancelled) return;
        setTransactions(transactionResult);
        setAccounts(accountResult);
        setCategories(categoryResult);
        setTags(tagResult);
        const requestedTransaction = new URLSearchParams(
          window.location.search,
        ).get("transaction");
        const requestedAction = new URLSearchParams(
          window.location.search,
        ).get("action");
        if (requestedTransaction) {
          setEditing(
            transactionResult.find(
              (transaction) => transaction.id === requestedTransaction,
            ) ?? null,
          );
        }
        if (requestedAction === "add" && accountResult.length) {
          // A nudge that names an account should open the form already on it,
          // otherwise the person has to find it again in a dropdown.
          const requestedAccount = new URLSearchParams(
            window.location.search,
          ).get("account");
          if (
            requestedAccount &&
            accountResult.some((item) => item.id === requestedAccount)
          ) {
            setPresetAccountId(requestedAccount);
          }
          setAdding(true);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load transactions",
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

  // Poll while a categorization run is live. A local model can take minutes,
  // so the UI reports real progress instead of guessing with a timeout.
  useEffect(() => {
    if (!aiBusy) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const progress = await apiFetch<AiProgress>(
          "/transactions/ai-review/progress",
        );
        if (cancelled) return;
          setAiProgress(progress);
        if (progress.state === "done" || progress.state === "failed") {
          window.clearInterval(timer);
          setAiBusy(false);
          await load();
          if (progress.suggested > 0) {
            setReview("needs-review");
            setSource("ai");
          }
          setToast(
            progress.state === "done"
              ? progress.suggested
                ? `AI suggested ${progress.suggested} categor${progress.suggested === 1 ? "y" : "ies"}. Review each suggestion before approving it.`
                : `AI made no suggestions. ${progress.abstained} were uncertain and ${progress.invalid + progress.remaining} could not be safely applied.`
              : progress.error || "AI categorization failed.",
          );
        }
      } catch {
        // A dropped poll is not fatal; the next tick retries.
      }
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [aiBusy]);

  const accountMap = useMemo(
    () => new Map(accounts.map((item) => [item.id, item])),
    [accounts],
  );
  const categoryMap = useMemo(
    () => new Map(categories.map((item) => [item.id, item])),
    [categories],
  );
  // Two people here hold the same two cards, so a row saying "Discover it
  // Card" does not say whose. `accountLabel` adds the owner only where the
  // name repeats, leaving every other row as short as it was.
  const accountName = useCallback(
    (accountId: string) => {
      const account = accountMap.get(accountId);
      return account ? accountLabel(account, accounts) : "Unknown account";
    },
    [accountMap, accounts],
  );
  const canEdit = role !== null && role !== "viewer";
  const aiReady =
    aiConfigured &&
    worker?.online === true &&
    worker.ai_configured !== false;

  const incomeCategoryIds = useMemo(
    () =>
      new Set(
        categories
          .filter((item) => item.group_is_income && !item.excluded_from_budget)
          .map((item) => item.id),
      ),
    [categories],
  );
  const switchedOffCategoryIds = useMemo(
    () =>
      new Set(
        categories.filter((item) => item.excluded_from_budget).map((i) => i.id),
      ),
    [categories],
  );
  // A transfer has no category to confirm and an excluded row is outside every
  // budget, so neither can be made to satisfy this and refusing leaves them in
  // the queue forever. Mirrors `_review_needs_a_category` on the API.
  function needsACategory(transaction: Transaction) {
    return !transaction.is_transfer && !transaction.excluded_from_budget;
  }

  // Why a row is not in the totals, in the row's own words. One function, so
  // the strip's arithmetic and the note beside the number cannot drift apart —
  // a green "+$265.98" with no explanation is the whole complaint.
  function notCountedNote(transaction: Transaction) {
    if (transaction.is_transfer) return "transfer · not counted";
    if (transaction.excluded_from_budget) return "not counted";
    const amount = Number(transaction.amount);
    const category = transaction.category_id;
    if (amount >= 0) {
      if (accountMap.get(transaction.account_id)?.kind === "liability") {
        return "paid onto a card · not income";
      }
      // A refund filed in a spending category reduces that category; it is
      // not earnings. The totals have always known this — the row said
      // nothing, so a green "+$38.50" sat above a "Money in" that excluded it.
      if (category && !incomeCategoryIds.has(category)) {
        return "refund · not income";
      }
    } else if (category && incomeCategoryIds.has(category)) {
      return "in an income category · not spending";
    }
    return null;
  }

  const quickApprove = useCallback(async (transaction: Transaction) => {
    if (
      !transaction.category_id &&
      !transaction.is_transfer &&
      !transaction.excluded_from_budget
    ) {
      setToast("Choose a category before approving this transaction.");
      return;
    }
    setRowBusy(transaction.id);
    try {
      const updated = await apiFetch<Transaction>(
        `/transactions/${transaction.id}`,
        { method: "PATCH", body: JSON.stringify({ reviewed: true }) },
      );
      setTransactions((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Could not mark reviewed",
      );
    } finally {
      setRowBusy("");
    }
  }, []);

  async function quickCategorize(transaction: Transaction, categoryId: string) {
    setRowBusy(transaction.id);
    try {
      const updated = await apiFetch<Transaction>(
        `/transactions/${transaction.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ category_id: categoryId || null }),
        },
      );
      setTransactions((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Could not set category",
      );
    } finally {
      setRowBusy("");
    }
  }

  async function markAllReviewed(ids: string[]) {
    setBulkBusy(true);
    try {
      const result = await apiFetch<{
        reviewed: number;
        skipped_uncategorized: number;
      }>(
        "/transactions/review",
        { method: "POST", body: JSON.stringify({ transaction_ids: ids }) },
      );
      // Not "categorized transactions" any more: most of what this clears now
      // is transfers, which are approved precisely because they have no
      // category. Saying otherwise described the old refusal, not the result.
      setToast(
        `${result.reviewed} transaction${result.reviewed === 1 ? "" : "s"} approved${result.skipped_uncategorized ? `; ${result.skipped_uncategorized} still need a category` : ""}.`,
      );
      await load();
      setSelectedIds([]);
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Could not mark reviewed",
      );
    } finally {
      setBulkBusy(false);
    }
  }

  async function runBulkAction(action: "categorize" | "exclude" | "include") {
    if (!selectedIds.length) return;
    if (action === "categorize" && !bulkCategory) {
      setToast("Choose a category for the selected transactions.");
      return;
    }
    setBulkBusy(true);
    try {
      const result = await apiFetch<{ updated: number }>("/transactions/bulk", {
        method: "POST",
        body: JSON.stringify({
          transaction_ids: selectedIds,
          action,
          category_id: action === "categorize" ? bulkCategory : null,
        }),
      });
      setToast(
        `${result.updated} transaction${result.updated === 1 ? "" : "s"} ${
          action === "categorize"
            ? "categorized"
            : action === "exclude"
              ? "excluded from budgets and reports"
              : "returned to budgets and reports"
        }.`,
      );
      setSelectedIds([]);
      await load();
    } catch (reason) {
      setToast(reason instanceof Error ? reason.message : "Bulk update failed");
    } finally {
      setBulkBusy(false);
    }
  }

  async function askAi() {
    setAiBusy(true);
    setToast("");
    try {
      const result = await apiFetch<{ queued: number }>(
        "/transactions/ai-review",
        { method: "POST", body: JSON.stringify({}) },
      );
      if (!result.queued) {
        setToast("Nothing for the AI to categorize right now.");
        setAiBusy(false);
        return;
      }
      setAiProgress({
        state: "queued",
        total: result.queued,
        processed: 0,
        suggested: 0,
        abstained: 0,
        invalid: 0,
        remaining: result.queued,
        failed_batches: 0,
        merchants: 0,
        merchants_done: 0,
        updated_at: 0,
        started_at: Math.floor(Date.now() / 1000),
        error: null,
      });
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "AI suggestions failed",
      );
      setAiBusy(false);
    }
  }

  // Filters that only a split line can satisfy.
  const categorical = Boolean(category) || Boolean(tag) || Boolean(source);
  const activeFilters = [
    account,
    category,
    source,
    tag,
    start,
    end,
    review !== "all" ? review : "",
    direction !== "all" ? direction : "",
    sort !== "newest" ? sort : "",
  ].filter(Boolean).length;
  const filtered = useMemo(
    () => {
      const matches = transactions.filter((transaction) => {
        const merchant =
          prettyMerchant(
            transaction.merchant_name || transaction.original_description,
          );
        const amount = Number(transaction.amount);
        return (
          merchant.toLowerCase().includes(query.toLowerCase()) &&
          // A split parent carries no category and its lines do. Asking a
          // categorical question means the lines are the answer; asking none
          // means the bank charge is. Showing both would list the same money
          // twice, so exactly one side is visible at a time.
          (categorical
            ? !transaction.is_split
            : transaction.parent_transaction_id === null) &&
          (!category || transaction.category_id === category) &&
          (!account || transaction.account_id === account) &&
          (!start || transaction.posted_date >= start) &&
          (!end || transaction.posted_date <= end) &&
          (direction === "all" ||
            (direction === "inflow" ? amount > 0 : amount < 0)) &&
          (!tag || (transaction.tags ?? []).some((item) => item.id === tag)) &&
          (!source ||
            (source === "uncategorized"
              ? !transaction.category_id
              : transaction.categorization_source === source)) &&
          (review === "all" ||
            (review === "reviewed"
              ? transaction.reviewed
              : !transaction.reviewed))
        );
      });
      return matches.sort((left, right) => {
        if (sort === "oldest") {
          return left.posted_date.localeCompare(right.posted_date);
        }
        if (sort === "amount-high") {
          return Math.abs(Number(right.amount)) - Math.abs(Number(left.amount));
        }
        if (sort === "amount-low") {
          return Math.abs(Number(left.amount)) - Math.abs(Number(right.amount));
        }
        return right.posted_date.localeCompare(left.posted_date);
      });
    },
    [
      account,
      categorical,
      category,
      direction,
      end,
      query,
      review,
      sort,
      source,
      start,
      tag,
      transactions,
    ],
  );
  // Headline counts are about bank charges, not the lines inside them. The
  // fetch includes lines so a category filter can reach them, so every count
  // has to say which it means.
  const charges = transactions.filter(
    (item) => item.parent_transaction_id === null,
  );
  const needsReview = charges.filter((item) => !item.reviewed).length;
  // ---- Keyboard review -----------------------------------------------------
  // Reviewing is the most repeated thing anyone does here, and doing it with a
  // pointer means three clicks per row. These shortcuts turn a long queue into
  // a rhythm: move, assign, approve, move.
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const focusedRef = useRef<string | null>(null);
  const filteredRef = useRef<Transaction[]>([]);
  const quickRef = useRef<Category[]>([]);
  const shortcutsRef = useRef(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  // On a phone the ten filter controls filled a screen and a half before a
  // single transaction was visible. They collapse behind one control, and the
  // count keeps them honest — a hidden filter that is silently narrowing the
  // list is worse than a visible one.
  const [filtersOpen, setFiltersOpen] = useState(false);

  // The number keys map to the categories this household actually uses, not
  // the first nine alphabetically. A shortcut you have to look up is not a
  // shortcut.
  const quickCategories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of transactions) {
      if (!item.category_id) continue;
      counts.set(item.category_id, (counts.get(item.category_id) ?? 0) + 1);
    }
    const ranked = [...categories].sort(
      (left, right) =>
        (counts.get(right.id) ?? 0) - (counts.get(left.id) ?? 0) ||
        left.name.localeCompare(right.name),
    );
    return ranked.slice(0, 9);
  }, [categories, transactions]);

  const previousReview = useRef<number | null>(null);
  const [justCleared, setJustCleared] = useState(false);

  useEffect(() => {
    const before = previousReview.current;
    previousReview.current = needsReview;
    // Arriving at an already-empty queue is calm, not a trophy. Only the
    // moment of finishing earns anything.
    if (before === null || before === 0 || needsReview !== 0) return;
    setJustCleared(true);
    const timer = setTimeout(() => setJustCleared(false), 6000);
    return () => clearTimeout(timer);
  }, [needsReview]);
  const aiSuggestions = charges.filter(
    (item) =>
      !item.reviewed && item.category_id && item.categorization_source === "ai",
  ).length;
  const approvableVisible = filtered.filter(
    (item) => !item.reviewed && (item.category_id || !needsACategory(item)),
  );
  const visibleIds = filtered.map((item) => item.id);
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));
  /**
   * Money in and money out for the rows on screen.
   *
   * **Transfers and excluded rows are not money in or money out.** Paying
   * $265.98 off a card posts a positive amount, and counting it here put it
   * straight into "Money in" — which is what "it is still pulling credit card
   * payments as income" was pointing at. The backend has stopped counting
   * these in five separate places; this strip was doing its own arithmetic in
   * the browser and never learned.
   *
   * **Nor is an inflow onto a credit card**, whether or not anything has
   * recognised it as a transfer yet. Nobody is paid into a card: money
   * arriving there is a payment or a refund. The backend's income query has
   * said so since 1.39.0 and this strip did not, so a card payment counted as
   * "Money in" here right up until the next sync paired it — the dashboard
   * read $2,600 and this page read $3,100 off the same rows, and the $500
   * between them was a card payment. Waiting for the flag is not good enough
   * when the flag is what arrives late.
   *
   * **And the category has to be consulted, not just the sign.** This is the
   * same rule `spending_scope.py` defines for every backend report, written
   * out a third time here because the browser has no access to it — so it is
   * kept deliberately literal rather than clever:
   *
   * - money in = positive, in an income category or none yet;
   * - money out = negative, *not* in an income category.
   *
   * Without those two clauses a $38.50 fuel refund filed under Transportation
   * counted as income and a $250 payroll reversal counted as spending, and
   * this strip disagreed with the dashboard by exactly those amounts on the
   * same screenful of rows.
   *
   * The excluded count rides along so the total is explainable rather than
   * merely smaller than the rows suggest.
   */
  const visibleTotals = filtered.reduce(
    (totals, item) => {
      const amount = Number(item.amount);
      const onACard = accountMap.get(item.account_id)?.kind === "liability";
      const uncategorized = !item.category_id;
      if (item.is_transfer || item.excluded_from_budget) {
        totals.notCounted += 1;
        return totals;
      }
      if (amount >= 0) {
        const earned =
          !onACard &&
          (uncategorized || incomeCategoryIds.has(item.category_id as string));
        if (earned) totals.income += amount;
        else totals.notCounted += 1;
      } else {
        const counts =
          uncategorized ||
          (!incomeCategoryIds.has(item.category_id as string) &&
            !switchedOffCategoryIds.has(item.category_id as string));
        if (counts) totals.spending += Math.abs(amount);
        else totals.notCounted += 1;
      }
      return totals;
    },
    { income: 0, spending: 0, notCounted: 0 },
  );

  // The listener binds once and reads through refs, so it never goes stale and
  // never re-subscribes on every keystroke-adjacent state change.
  useEffect(() => {
    focusedRef.current = focusedId;
  }, [focusedId]);
  useEffect(() => {
    filteredRef.current = filtered;
  }, [filtered]);
  useEffect(() => {
    quickRef.current = quickCategories;
  }, [quickCategories]);
  useEffect(() => {
    shortcutsRef.current = showShortcuts;
  }, [showShortcuts]);

  // One global listener rather than per-row handlers, so the shortcuts work
  // wherever you are on the page — but it defers completely whenever the
  // keystroke could belong to something else.
  useEffect(() => {
    if (!canEdit) return;
    const onKey = (event: KeyboardEvent) => {
      // Never steal a keystroke from a field, from the command palette, or
      // from a dialog. This is the difference between a shortcut and a bug.
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }
      // Order matters here. Checking for an open dialog first meant Escape was
      // swallowed before it could close the very sheet these shortcuts opened.
      if (shortcutsRef.current) {
        if (event.key === "Escape" || event.key === "?") {
          event.preventDefault();
          setShowShortcuts(false);
        }
        return;
      }
      // Any other dialog, or the command palette, owns the keyboard entirely.
      if (
        document.querySelector(".dialog-layer") ||
        document.querySelector(".command-palette")
      ) {
        return;
      }

      const rows = filteredRef.current;
      if (event.key === "?") {
        event.preventDefault();
        setShowShortcuts(true);
        return;
      }
      if (event.key === "Escape") {
        setFocusedId(null);
        return;
      }
      if (!rows.length) return;

      const index = rows.findIndex((item) => item.id === focusedRef.current);
      const move = (delta: number) => {
        event.preventDefault();
        // No focus yet means start at the first row that still needs a person.
        const next =
          index === -1
            ? Math.max(
                0,
                rows.findIndex((item) => !item.reviewed),
              )
            : Math.min(Math.max(index + delta, 0), rows.length - 1);
        setFocusedId(rows[next]?.id ?? null);
      };

      if (event.key === "j" || event.key === "ArrowDown") return move(1);
      if (event.key === "k" || event.key === "ArrowUp") return move(-1);

      const focused = index === -1 ? null : rows[index];
      if (!focused) return;

      if (event.key >= "1" && event.key <= "9") {
        const category = quickRef.current[Number(event.key) - 1];
        if (!category) return;
        event.preventDefault();
        if (focused.is_split) {
          setToast("That transaction is split. Press s to edit its lines.");
          return;
        }
        void quickCategorize(focused, category.id);
        return;
      }
      if (event.key === "a") {
        event.preventDefault();
        void quickApprove(focused);
        // Approving is the end of that row's business, so move on rather than
        // making somebody press j as well.
        const next = rows[index + 1];
        if (next) setFocusedId(next.id);
        return;
      }
      if (event.key === "s") {
        event.preventDefault();
        setSplitting(focused);
        return;
      }
      if (event.key === "x") {
        event.preventDefault();
        setSelectedIds((current) =>
          current.includes(focused.id)
            ? current.filter((id) => id !== focused.id)
            : [...current, focused.id],
        );
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canEdit, quickApprove]);

  // Keep the focused row on screen without yanking the page around.
  useEffect(() => {
    if (!focusedId) return;
    document
      .querySelector(`[data-row-id="${focusedId}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [focusedId]);

  function applyView(view: SavedTransactionView) {
    setAccount(view.account);
    setCategory(view.category);
    setReview(view.review);
    setSource(view.source);
    setStart(view.start ?? "");
    setEnd(view.end ?? "");
    setDirection(view.direction ?? "all");
    setTag(view.tag ?? "");
    setSort(view.sort ?? "newest");
  }

  function resetFilters() {
    setQuery("");
    applyView({
      account: "",
      category: "",
      review: "all",
      source: "",
      start: "",
      end: "",
      direction: "all",
      tag: "",
      sort: "newest",
    });
    setSelectedIds([]);
  }

  function saveCurrentView() {
    const view: SavedTransactionView = {
      account,
      category,
      review,
      source,
      start,
      end,
      direction,
      tag,
      sort,
    };
    setSavedView(view);
    window.localStorage.setItem(
      "raven-transaction-view",
      JSON.stringify(view),
    );
    setToast("Transaction view saved on this device.");
  }

  function saved(message: string) {
    setEditing(null);
    setAdding(false);
    setToast(message);
    void load();
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Transactions</p>
          <h1>Every purchase, organized.</h1>
          <p className="subtle">
            Search, categorize, review, exclude, and annotate household activity.
          </p>
        </div>
        <div className="heading-actions">
          <a
            className="ghost-button"
            href="/api/v1/households/export?format=csv"
          >
            <Download size={15} /> Export CSV
          </a>
          <button
            className="primary-button"
            disabled={!accounts.length}
            onClick={() => setAdding(true)}
          >
            <Plus size={15} /> Add transaction
          </button>
        </div>
      </div>

      <section className="transaction-summary-strip">
        <span>
          <strong>{charges.length}</strong>
          Transactions loaded
        </span>
        <span className={needsReview ? "negative" : "positive"}>
          <strong>{needsReview}</strong>
          Need review
        </span>
        <span>
          <strong>{aiSuggestions}</strong>
          AI suggestions
        </span>
        <span>
          <strong>
            {
              transactions.filter((item) => item.excluded_from_budget).length
            }
          </strong>
          Excluded
        </span>
      </section>

      {aiConfigured && worker && !aiReady && (
        <section className="ai-health-warning" role="alert">
          <Sparkles size={17} />
          <div>
            <strong>AI suggestions are not ready</strong>
            <p>
              {!worker.online
                ? "The background worker is offline, so queued categorization cannot run."
                : worker.ai_configured === false
                  ? "The backend has AI configured, but the worker does not. Add the same LLM settings to both containers and restart the worker."
                  : "The backend and worker are using different AI settings. Make their LLM URL and model identical, then restart both containers."}
            </p>
          </div>
          <a className="ghost-button" href="/settings">
            Open settings
          </a>
        </section>
      )}

      {aiProgress &&
        (aiProgress.state === "done" || aiProgress.state === "failed") && (
          <section
            className={`ai-run-result ${aiProgress.state === "failed" ? "failed" : ""}`}
          >
            <span className="ai-run-icon">
              <Sparkles size={18} />
            </span>
            <div>
              <strong>
                {aiProgress.state === "failed"
                  ? "The categorization run needs attention"
                  : aiProgress.suggested > 0
                    ? `${aiProgress.suggested} new suggestion${aiProgress.suggested === 1 ? "" : "s"} from this run`
                    : aiSuggestions > 0
                      // The run added nothing, but earlier suggestions are
                      // still waiting. Saying "0 ready for review" next to a
                      // stat card reading 62 looked like a bug; both numbers
                      // were right and neither said which it meant.
                      ? "Nothing new — your earlier suggestions are still waiting"
                      : "Nothing new to suggest"}
              </strong>
              <p>
                {aiProgress.state === "failed"
                  ? aiProgress.error || "The worker could not complete this run."
                  : [
                      aiProgress.abstained > 0 &&
                        `${aiProgress.abstained} the model was not sure about`,
                      aiProgress.invalid > 0 &&
                        `${aiProgress.invalid} rejected as unsafe`,
                      aiProgress.remaining > 0 &&
                        `${aiProgress.remaining} left unanswered`,
                      aiSuggestions > 0 &&
                        `${aiSuggestions} waiting for you to confirm`,
                    ]
                      .filter(Boolean)
                      .join(" · ") || "Every transaction already has a category."}
              </p>
            </div>
            {aiSuggestions > 0 && (
              <button
                className="primary-button"
                onClick={() => {
                  setReview("needs-review");
                  setSource("ai");
                }}
                type="button"
              >
                Review suggestions <ChevronRight size={14} />
              </button>
            )}
            <button
              aria-label="Dismiss categorization result"
              className="row-edit-button"
              onClick={() => setAiProgress(null)}
              type="button"
            >
              <X size={14} />
            </button>
          </section>
        )}

      {canEdit && focusedId && quickCategories.length > 0 && (
        <div className="keyboard-legend" role="status">
          <span className="keyboard-legend-title">
            <Keyboard size={13} /> Quick keys
          </span>
          <ul>
            {quickCategories.map((item, index) => (
              <li key={item.id}>
                <kbd>{index + 1}</kbd>
                <em style={{ color: item.color }}>{item.name}</em>
              </li>
            ))}
          </ul>
          <span className="keyboard-legend-more">
            <kbd>a</kbd> approve · <kbd>s</kbd> split · <kbd>x</kbd> select ·{" "}
            <kbd>?</kbd> all keys
          </span>
        </div>
      )}

      {showShortcuts && (
        <div className="dialog-layer" onClick={() => setShowShortcuts(false)}>
          <button
            aria-label="Close dialog"
            className="dialog-backdrop"
            onClick={() => setShowShortcuts(false)}
          />
          <section
            aria-label="Keyboard shortcuts"
            aria-modal="true"
            className="account-dialog shortcut-sheet"
            role="dialog"
          >
            <div className="dialog-header">
              <div>
                <p className="eyebrow">
                  <Keyboard size={12} /> Keyboard
                </p>
                <h2>Review without the mouse</h2>
                <p>
                  Move down the queue, assign a category, approve, repeat. The
                  number keys follow the categories this household uses most.
                </p>
              </div>
              <button
                aria-label="Close"
                className="dialog-close"
                onClick={() => setShowShortcuts(false)}
              >
                <X size={18} />
              </button>
            </div>
            <ul className="shortcut-list">
              {[
                ["j / ↓", "Move to the next transaction"],
                ["k / ↑", "Move to the previous one"],
                ["1 – 9", "Assign one of your most-used categories"],
                ["a", "Approve, then move on"],
                ["s", "Split across categories"],
                ["x", "Add to the selection for a bulk action"],
                ["?", "Show or hide this sheet"],
                ["Esc", "Clear the focus"],
              ].map(([key, meaning]) => (
                <li key={key}>
                  <kbd>{key}</kbd>
                  <span>{meaning}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}

      {needsReview === 0 && justCleared && (
        <section className="panel inbox-zero" role="status">
          <CheckCheck size={26} />
          <strong>That is everything reviewed.</strong>
          <small>
            {charges.length} transaction{charges.length === 1 ? "" : "s"} in
            view, nothing waiting on you. Every category you confirmed is
            remembered, so the same merchants will not come back to ask again.
          </small>
        </section>
      )}

      {needsReview > 0 && canEdit && (
        <section className="review-bar">
          <div>
            <strong>
              {needsReview} transaction{needsReview === 1 ? "" : "s"} to review
            </strong>
            <p>
              {aiSuggestions
                ? `${aiSuggestions} came from AI. Confirm, correct, or reject each suggestion before approval.`
                : /* "Choose a category on each" was not true of a transfer,
                     which is most of what sits here — and telling somebody to
                     do the one thing that cannot be done is how eighteen rows
                     came to look permanent. */
                  "Give each transaction a category, or dismiss the transfers."}
            </p>
          </div>
          {aiProgress && aiProgress.state !== "idle" && (
            <div className="ai-progress">
              <div className="ai-progress-track">
                <span
                  className={
                    aiProgress.state === "running" &&
                    aiProgress.merchants_done === 0
                      ? "indeterminate"
                      : undefined
                  }
                  style={{
                    width: `${
                      aiProgress.merchants
                        ? Math.round(
                            (aiProgress.merchants_done / aiProgress.merchants) *
                              100,
                          )
                        : 0
                    }%`,
                  }}
                />
              </div>
              <small>
                {aiProgress.state === "queued"
                  ? `Queued ${aiProgress.total} transactions — waiting for the worker…`
                    : aiProgress.state === "running"
                    ? `Asking your model about merchant ${Math.min(aiProgress.merchants_done + 1, aiProgress.merchants)} of ${aiProgress.merchants} · ${aiProgress.suggested} suggestions so far`
                    : aiProgress.state === "done"
                      ? `Done — ${aiProgress.suggested} newly suggested${aiProgress.abstained ? `, ${aiProgress.abstained} uncertain` : ""}${aiProgress.remaining ? `, ${aiProgress.remaining} unanswered` : ""}`
                      : aiProgress.error || "Failed"}
              </small>
            </div>
          )}
          <div className="review-bar-actions">
            {review !== "needs-review" && (
              <button
                className="ghost-button"
                onClick={() => setReview("needs-review")}
                type="button"
              >
                Show them
              </button>
            )}
            {aiSuggestions > 0 && source !== "ai" && (
              <button
                className="ghost-button"
                onClick={() => {
                  setReview("needs-review");
                  setSource("ai");
                }}
                type="button"
              >
                <Sparkles size={14} /> Review AI suggestions
              </button>
            )}
            {aiConfigured && (
              <button
                className="ghost-button"
                disabled={aiBusy || !aiReady}
                onClick={() => void askAi()}
                title={
                  aiReady
                    ? "Ask the configured model to suggest categories"
                    : "The worker must be online with matching AI settings"
                }
                type="button"
              >
                <Sparkles size={14} />
                {aiBusy ? "Suggesting…" : "Suggest categories with AI"}
              </button>
            )}
            <button
              className="primary-button"
              disabled={bulkBusy || !approvableVisible.length}
              onClick={() =>
                void markAllReviewed(
                  approvableVisible.map((item) => item.id),
                )
              }
              type="button"
            >
              <CheckCheck size={14} />
              {bulkBusy
                ? "Approving…"
                : `Approve visible (${approvableVisible.length})`}
            </button>
          </div>
        </section>
      )}

      <section className="transaction-view-bar" aria-label="Transaction views">
        <div className="transaction-presets">
          <button onClick={resetFilters} type="button">
            All activity
          </button>
          <button
            onClick={() =>
              applyView({
                account: "",
                category: "",
                review: "needs-review",
                source: "",
              })
            }
            type="button"
          >
            Needs review <em>{needsReview}</em>
          </button>
          <button
            onClick={() =>
              applyView({
                account: "",
                category: "",
                review: "needs-review",
                source: "ai",
              })
            }
            type="button"
          >
            <Sparkles size={13} /> AI suggestions <em>{aiSuggestions}</em>
          </button>
          <button
            onClick={() =>
              applyView({
                account: "",
                category: "",
                review: "all",
                source: "uncategorized",
              })
            }
            type="button"
          >
            Uncategorized
          </button>
          {savedView && (
            <button
              className="saved"
              onClick={() => applyView(savedView)}
              type="button"
            >
              <Bookmark size={13} /> My view
            </button>
          )}
        </div>
        <div className="transaction-view-actions">
          <button className="text-button" onClick={saveCurrentView} type="button">
            <Bookmark size={13} /> Save current view
          </button>
          <button
            aria-label="Clear transaction filters"
            className="icon-button"
            onClick={resetFilters}
            title="Clear filters"
            type="button"
          >
            <RotateCcw size={14} />
          </button>
        </div>
      </section>

      <div
        className={`toolbar transaction-toolbar${filtersOpen ? " filters-open" : ""}`}
        id="transaction-filters"
      >
        <label className="search-field">
          <Search size={16} />
          <input
            aria-label="Search transactions"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search merchant or description"
            value={query}
          />
        </label>
        <button
          aria-controls="transaction-filters"
          aria-expanded={filtersOpen}
          className={`filters-toggle${activeFilters ? " has-filters" : ""}`}
          onClick={() => setFiltersOpen((current) => !current)}
          type="button"
        >
          <SlidersHorizontal size={14} />
          Filters
          {activeFilters > 0 && <em>{activeFilters}</em>}
        </button>
        <select
          aria-label="Filter by account"
          className="filter-select"
          onChange={(event) => setAccount(event.target.value)}
          value={account}
        >
          <option value="">All accounts</option>
          {accounts.map((item) => (
            <option key={item.id} value={item.id}>
              {accountLabel(item, accounts)}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by category"
          className="filter-select"
          onChange={(event) => setCategory(event.target.value)}
          value={category}
        >
          <option value="">All categories</option>
          {categories.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by review status"
          className="filter-select"
          onChange={(event) =>
            setReview(event.target.value as typeof review)
          }
          value={review}
        >
          <option value="all">All review states</option>
          <option value="needs-review">Needs review</option>
          <option value="reviewed">Reviewed</option>
        </select>
        <select
          aria-label="Filter by categorization source"
          className="filter-select"
          onChange={(event) => setSource(event.target.value)}
          value={source}
        >
          <option value="">All category sources</option>
          <option value="ai">AI suggestions</option>
          <option value="merchant_memory">Learned choices</option>
          <option value="household_rule">Rules</option>
          <option value="provider_category">Bank categories</option>
          <option value="uncategorized">Uncategorized</option>
        </select>
      </div>

      <section className="transaction-advanced-filters" aria-label="Advanced transaction filters">
        <label className="field">
          <span>From</span>
          <input max={end || undefined} onChange={(event) => setStart(event.target.value)} type="date" value={start} />
        </label>
        <label className="field">
          <span>Through</span>
          <input min={start || undefined} onChange={(event) => setEnd(event.target.value)} type="date" value={end} />
        </label>
        <div className="field">
          <span>Money direction</span>
          <div className="segmented-control transaction-direction-filter">
            {(["all", "outflow", "inflow"] as const).map((value) => (
              <button className={direction === value ? `active ${value === "outflow" ? "spending" : value === "inflow" ? "income" : ""}` : ""} key={value} onClick={() => setDirection(value)} type="button">
                {value === "all" ? "Both" : value === "outflow" ? "Money out" : "Money in"}
              </button>
            ))}
          </div>
        </div>
        <label className="field">
          <span>Tag</span>
          <select aria-label="Filter by tag" onChange={(event) => setTag(event.target.value)} value={tag}>
            <option value="">All tags</option>
            {tags.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Sort</span>
          <select aria-label="Sort transactions" onChange={(event) => setSort(event.target.value as typeof sort)} value={sort}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="amount-high">Largest amount</option>
            <option value="amount-low">Smallest amount</option>
          </select>
        </label>
      </section>

      <section
        className="filtered-financial-summary"
        aria-label="Visible transaction totals"
      >
        <span>
          <small>Showing</small>
          <strong>
            {filtered.length} of {charges.length}
          </strong>
        </span>
        <span className="wealth">
          <small>Money in</small>
          <strong>+{currency(visibleTotals.income)}</strong>
        </span>
        <span className="obligation">
          <small>Money out</small>
          <strong>-{currency(visibleTotals.spending)}</strong>
        </span>
        <span
          className={
            visibleTotals.income - visibleTotals.spending >= 0
              ? "wealth"
              : "obligation"
          }
        >
          <small>Visible net</small>
          <strong>
            {currency(visibleTotals.income - visibleTotals.spending)}
          </strong>
        </span>
        {/* Says why the total is smaller than the rows suggest. A figure that
            quietly omits things is how these bugs stay hidden. */}
        {visibleTotals.notCounted > 0 && (
          <span className="summary-note">
            <small>Not counted</small>
            <strong>
              {visibleTotals.notCounted} transfer
              {visibleTotals.notCounted === 1 ? "" : "s"} or excluded
            </strong>
          </span>
        )}
      </section>

      {error && <div className="page-error">{error}</div>}
      {selectedIds.length > 0 && canEdit && (
        <section className="transaction-bulk-bar" aria-label="Bulk transaction actions">
          <div>
            <strong>{selectedIds.length} selected</strong>
            <small>Actions only affect transactions in this household.</small>
          </div>
          <select aria-label="Bulk category" onChange={(event) => setBulkCategory(event.target.value)} value={bulkCategory}>
            <option value="">Choose category…</option>
            {categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <button className="ghost-button" disabled={bulkBusy || !bulkCategory} onClick={() => void runBulkAction("categorize")} type="button">Apply category</button>
          <button className="ghost-button" disabled={bulkBusy} onClick={() => void markAllReviewed(selectedIds)} type="button"><CheckCheck size={13} /> Approve</button>
          <button className="ghost-button" disabled={bulkBusy} onClick={() => void runBulkAction("exclude")} type="button">Exclude</button>
          <button className="ghost-button" disabled={bulkBusy} onClick={() => void runBulkAction("include")} type="button">Include</button>
          <button aria-label="Clear selection" className="icon-button" onClick={() => setSelectedIds([])} type="button"><X size={14} /></button>
        </section>
      )}
      {loading ? (
        <div className="account-loading">
          <LoaderCircle className="spin" size={21} />
          Loading transactions…
        </div>
      ) : (
        <section className="data-panel transaction-panel">
          {filtered.length ? (
            <table className="data-table transaction-table">
              <thead>
                <tr>
                  {canEdit && (
                    <th className="selection-column">
                      <input
                        aria-label="Select all visible transactions"
                        checked={allVisibleSelected}
                        onChange={(event) =>
                          setSelectedIds((current) =>
                            event.target.checked
                              ? Array.from(new Set([...current, ...visibleIds]))
                              : current.filter((id) => !visibleIds.includes(id)),
                          )
                        }
                        type="checkbox"
                      />
                    </th>
                  )}
                  <th>Status</th>
                  <th>Date</th>
                  <th>Merchant</th>
                  <th>Category</th>
                  <th>Account</th>
                  <th>Amount</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((transaction) => {
                  const amount = Number(transaction.amount);
                  const merchant =
                    transaction.merchant_name ||
                    transaction.original_description;
                  const transactionCategory = transaction.category_id
                    ? categoryMap.get(transaction.category_id)
                    : null;
                  return (
                    <tr
                      className={[
                        "clickable-row",
                        selectedIds.includes(transaction.id) ? "selected-row" : "",
                        focusedId === transaction.id ? "focused-row" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      data-row-id={transaction.id}
                      key={transaction.id}
                      onClick={() => {
                        setFocusedId(transaction.id);
                        setEditing(transaction);
                      }}
                    >
                      {canEdit && (
                        <td className="selection-column" data-label="Select" onClick={(event) => event.stopPropagation()}>
                          <input
                            aria-label={`Select ${merchant}`}
                            checked={selectedIds.includes(transaction.id)}
                            onChange={(event) =>
                              setSelectedIds((current) =>
                                event.target.checked
                                  ? [...current, transaction.id]
                                  : current.filter((id) => id !== transaction.id),
                              )
                            }
                            type="checkbox"
                          />
                        </td>
                      )}
                      <td data-label="Status">
                        <span
                          className={`review-dot ${
                            transaction.reviewed ? "reviewed" : ""
                          }`}
                          title={
                            transaction.reviewed ? "Reviewed" : "Needs review"
                          }
                        />
                      </td>
                      <td data-label="Date">
                        {new Intl.DateTimeFormat("en-US", {
                          month: "short",
                          day: "numeric",
                          year: "numeric",
                        }).format(
                          new Date(`${transaction.posted_date}T12:00:00`),
                        )}
                                              {/* On a phone the account has no column of its own,
                            so it rides here rather than disappearing. */}
                        <span className="row-account-inline">
                          {" · "}
                          {accountName(transaction.account_id)}
                        </span>
                      </td>
                      <td data-label="Merchant">
                        <strong>{merchant}</strong>
                        {transaction.pending && <small>Pending</small>}
                        {!!(transaction.tags ?? []).length && (
                          <span className="transaction-row-tags">
                            {(transaction.tags ?? []).slice(0, 3).map((item) => (
                              <em key={item.id} style={{ "--tag-color": item.color } as React.CSSProperties}><i />{item.name}</em>
                            ))}
                          </span>
                        )}
                      </td>
                      <td data-label="Category">
                        {transaction.is_split ? (
                          // A split parent has no single category. Showing the
                          // dropdown here would invite an edit the API refuses.
                          <button
                            className="split-chip"
                            disabled={!canEdit}
                            onClick={(event) => {
                              event.stopPropagation();
                              setSplitting(transaction);
                            }}
                            title={transaction.splits
                              .map(
                                (line) =>
                                  `${
                                    categories.find(
                                      (item) => item.id === line.category_id,
                                    )?.name ?? "Uncategorized"
                                  } ${currency(Number(line.amount))}`,
                              )
                              .join(" · ")}
                            type="button"
                          >
                            <Scissors size={11} /> Split ·{" "}
                            {transaction.splits.length} lines
                          </button>
                        ) : !transaction.reviewed && canEdit ? (
                          <span
                            className="inline-category"
                            onClick={(event) => event.stopPropagation()}
                            role="presentation"
                          >
                            <SelectField
                              ariaLabel={`Category for ${merchant}`}
                              className="inline-category-select"
                              disabled={rowBusy === transaction.id}
                              onChange={(next) =>
                                void quickCategorize(transaction, next)
                              }
                              options={[
                                { value: "", label: "Uncategorized" },
                                ...categories.map((item) => ({
                                  value: item.id,
                                  label: item.name,
                                  group: item.group_name,
                                  color: item.color,
                                })),
                              ]}
                              value={transaction.category_id ?? ""}
                            />
                            {sourceChip(transaction.categorization_source)}
                          </span>
                        ) : (
                          <span
                            className="category-chip"
                            style={
                              transactionCategory
                                ? {
                                    backgroundColor: `${transactionCategory.color}18`,
                                    color: transactionCategory.color,
                                  }
                                : undefined
                            }
                          >
                            {transactionCategory?.name || "Uncategorized"}
                          </span>
                        )}
                      </td>
                      <td data-label="Account">
                        {accountName(transaction.account_id)}
                      </td>
                      <td
                        className={
                          notCountedNote(transaction)
                            ? "uncounted"
                            : amount > 0
                              ? "positive"
                              : "negative"
                        }
                        data-label="Amount"
                      >
                        {amount > 0 ? "+" : ""}
                        {currency(amount)}
                        {/* A card payment posts a positive amount, and a green
                            "+$265.98" with nothing beside it reads as income
                            however carefully the totals exclude it. Say what
                            it is on the row where the number is. */}
                        {notCountedNote(transaction) && (
                          <small className="row-not-counted">
                            {notCountedNote(transaction)}
                          </small>
                        )}
                      </td>
                      <td data-label="Actions">
                        {!transaction.reviewed && canEdit && (
                          <>
                            {transaction.categorization_source === "ai" &&
                              transaction.category_id && (
                                <button
                                  aria-label={`Reject AI category for ${merchant}`}
                                  className="row-reject-button"
                                  disabled={rowBusy === transaction.id}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void quickCategorize(transaction, "");
                                  }}
                                  title="Reject AI suggestion"
                                  type="button"
                                >
                                  <X size={14} />
                                </button>
                              )}
                            <button
                              aria-label={`Approve ${merchant}`}
                              className="row-approve-button"
                              /* Greyed out with "choose a category first" is
                                 what Alex was actually pressing on eighteen
                                 card payments — a transfer has no category to
                                 choose, so the tick was dead and the rows sat
                                 in the queue forever. The API-level drill
                                 passed this release; only clicking the button
                                 found it. */
                              disabled={
                                rowBusy === transaction.id ||
                                (!transaction.category_id &&
                                  needsACategory(transaction))
                              }
                              onClick={(event) => {
                                event.stopPropagation();
                                void quickApprove(transaction);
                              }}
                              title={
                                transaction.category_id
                                  ? "Approve category"
                                  : needsACategory(transaction)
                                    ? "Choose a category first"
                                    : "Dismiss from review"
                              }
                              type="button"
                            >
                              <Check size={14} />
                            </button>
                          </>
                        )}
                        {canEdit && !transaction.is_split && (
                          <button
                            aria-label={`Split ${merchant} across categories`}
                            className="row-edit-button wide-only"
                            onClick={(event) => {
                              event.stopPropagation();
                              setSplitting(transaction);
                            }}
                            title="Split across categories"
                            type="button"
                          >
                            <Scissors size={13} />
                          </button>
                        )}
                        {/* On a phone tapping the row already opens the editor,
                            so this is a fifth thing competing for 375px that
                            does nothing new. */}
                        <button
                          aria-label={`Edit ${merchant} transaction`}
                          className="row-edit-button wide-only"
                          onClick={(event) => {
                            event.stopPropagation();
                            setEditing(transaction);
                          }}
                          type="button"
                        >
                          <ChevronRight size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div className="transaction-empty">
              <Search size={20} />
              <strong>Nothing here matches</strong>
              <small>
                {charges.length > 0
                  ? "There are transactions loaded — the filters above just do not fit any of them. Clear one and they will come back."
                  : "No transactions yet. Connect a bank in Settings, or add one by hand to get started."}
              </small>
            </div>
          )}
        </section>
      )}

      {splitting && (
        <SplitDialog
          categories={categories}
          onClose={() => setSplitting(null)}
          onSaved={(message) => {
            setSplitting(null);
            saved(message);
          }}
          transaction={splitting}
        />
      )}
      {(adding || editing) && (
        <TransactionDialog
          accounts={accounts}
          categories={categories}
          tags={tags}
          onClose={() => {
            setAdding(false);
            setEditing(null);
          }}
          onSaved={saved}
          onSplit={(item) => {
            setEditing(null);
            setSplitting(item);
          }}
          presetAccountId={presetAccountId}
          transaction={editing ?? undefined}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}
