"use client";

import {
  CalendarRange,
  ChevronLeft,
  ChevronRight,
  Copy,
  LoaderCircle,
  PiggyBank,
  Save,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, apiFetch } from "@/lib/api";
import { Budget, BudgetLine, Category } from "@/lib/finance";
import { currency } from "@/lib/format";
import { GoalsManager } from "@/components/goals-manager";
import { IncomeSources } from "@/components/income-sources";
import { CollapsibleSection } from "@/components/collapsible-section";

type SpendingRow = {
  name: string;
  amount: string | number;
};

type IncomeRow = {
  id: string;
  name: string;
  amount: string | number;
  cadence: string;
  // null when no pay anchor is set, which means the figure beside it is the
  // yearly average rather than a count of this month's paydays.
  payments: number | null;
  baseline_payments: number;
  month_amount: string | number;
  monthly_average: string | number;
};

type CardRow = {
  account_id: string;
  name: string;
  // Null means shared — the third group in his spreadsheet, alongside his
  // cards and Jordan's.
  owner_name: string | null;
  // Null when no statement day is set: the card still owes what it owes, it
  // just has no cycle to report.
  statement_day: number | null;
  closes_on: string | null;
  covers_from: string | null;
  amount: string | number;
  paid: boolean;
  outstanding: string | number;
  // The slice of `outstanding` charged before this budget month, so still to
  // find cash for. The rest of the statement is already inside SPENT.
  unbudgeted: string | number;
  provisional: boolean;
  current_balance: string | number;
  balance_owed: string | number;
};

type MonthContext = {
  income: {
    month_total: string | number;
    average_total: string | number;
    sources: IncomeRow[];
    exact: boolean;
    has_extra_paycheque: boolean;
  };
  cards: {
    cards: CardRow[];
    due_total: string | number;
    unpaid_total: string | number;
    // The part of what is still to pay that this month's plan has *not*
    // already counted as spending. The only one of these totals that may be
    // subtracted from Remaining — see `afterCards`.
    unbudgeted_total: string | number;
    // What is owed across every card right now. Never added to the budget —
    // each charge is already counted as spending in the month it was made.
    balance_total: string | number;
    unconfigured: number;
  };
};

function dateParam(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function monthKey(date: Date) {
  return dateParam(new Date(date.getFullYear(), date.getMonth(), 1));
}

function emptyLine(categoryId: string): BudgetLine {
  return {
    category_id: categoryId,
    planned_amount: 0,
    rollover_enabled: false,
    rollover_amount: 0,
    non_monthly_target: null,
    non_monthly_due_date: null,
  };
}

export function BudgetManager() {
  const [month, setMonth] = useState(
    new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  );
  const [categories, setCategories] = useState<Category[]>([]);
  const [lines, setLines] = useState<Record<string, BudgetLine>>({});
  const [spending, setSpending] = useState<Record<string, number>>({});
  const [mode, setMode] = useState<"category" | "flex">("category");
  const [focus, setFocus] = useState<"all" | "funded" | "attention">("all");
  const [expectedIncome, setExpectedIncome] = useState("0");
  const [flexAmount, setFlexAmount] = useState("0");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // Tri-state, mirroring the column: null lets the pay dates decide.
  const [extraPaycheque, setExtraPaycheque] = useState<boolean | null>(null);
  const [context, setContext] = useState<MonthContext | null>(null);

  useEffect(() => {
    let cancelled = false;
    const start = monthKey(month);
    const end = dateParam(
      new Date(month.getFullYear(), month.getMonth() + 1, 0),
    );
    Promise.all([
      apiFetch<Category[]>("/categories"),
      /* `use_budget_month` is what makes rent land in the month that paid for
         it. The budget is the only page that asks this — every report stays
         on the posted date, because a report is history. */
      apiFetch<SpendingRow[]>(
        `/reports/spending?start=${start}&end=${end}&use_budget_month=true`,
      ),
      apiFetch<Budget>(`/budgets/${start}`).catch((reason: unknown) => {
        if (reason instanceof ApiError && reason.status === 404) return null;
        throw reason;
      }),
      // Separately, because a month with no budget saved yet still has pay
      // dates and card statements — and that is exactly the month you most
      // want to see them.
      apiFetch<MonthContext>(`/budgets/${start}/context`).catch(() => null),
    ])
      .then(([categoryResult, spendingResult, budgetResult, contextResult]) => {
        if (cancelled) return;
        // Income categories have nothing to plan, and an excluded category by
        // definition contributes nothing — planning against either produces a
        // row whose Spent can only ever be zero.
        const expenseCategories = categoryResult.filter(
          (category) =>
            !category.group_is_income && !category.excluded_from_budget,
        );
        setCategories(expenseCategories);
        setSpending(
          Object.fromEntries(
            spendingResult.map((item) => [item.name, Number(item.amount)]),
          ),
        );
        setMode(budgetResult?.mode ?? "category");
        setExtraPaycheque(budgetResult?.extra_paycheque ?? null);
        // `/budgets/{month}` embeds the same two blocks when a budget exists;
        // the standalone context endpoint covers the month before one is saved.
        setContext(contextResult);
        setExpectedIncome(String(budgetResult?.expected_income ?? 0));
        setFlexAmount(String(budgetResult?.flex_amount ?? 0));
        const savedLines = new Map(
          (budgetResult?.lines ?? []).map((line) => [line.category_id, line]),
        );
        setLines(
          Object.fromEntries(
            expenseCategories.map((category) => [
              category.id,
              savedLines.get(category.id) ?? emptyLine(category.id),
            ]),
          ),
        );
        setError("");
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error ? reason.message : "Could not load budget",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [month]);

  // The override changes the answer, so the answer has to be re-asked. Kept out
  // of the main load effect so flipping the toggle does not refetch categories
  // and spending as well.
  useEffect(() => {
    if (loading) return;
    let cancelled = false;
    const query =
      extraPaycheque === null ? "" : `?extra_paycheque=${extraPaycheque}`;
    apiFetch<MonthContext>(`/budgets/${monthKey(month)}/context${query}`)
      .then((result) => {
        if (!cancelled) setContext(result);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [extraPaycheque, month, loading]);

  const planned = useMemo(
    () =>
      Object.values(lines).reduce(
        (total, line) => total + Number(line.planned_amount || 0),
        0,
      ),
    [lines],
  );
  // Summed over the categories actually on screen, not over every row the
  // endpoint returned. Those two used to be different sets — anything the
  // table could not render still landed in this figure — so the headline and
  // the rows beneath it disagreed with nothing on screen to explain the gap.
  const spent = categories.reduce(
    (total, category) => total + (spending[category.name] ?? 0),
    0,
  );
  /**
   * **Spending that no plan reserved money for.**
   *
   * Measured per category and clamped at zero, because underspending Food does
   * not pay for overspending Fun Money — a plan is a set of promises, not one
   * pot. Rollover counts as cover, since that is money carried in rather than
   * earned this month.
   *
   * August 2026 for Alex: Fun Money $1,014.94 against no plan, General Needs
   * $97.75, Dining $57.76 — $1,170.45 of the month nobody budgeted for.
   */
  const unplannedSpend = categories.reduce((total, category) => {
    const line = lines[category.id];
    const cover =
      Number(line?.planned_amount || 0) + Number(line?.rollover_amount || 0);
    return total + Math.max(0, (spending[category.name] ?? 0) - cover);
  }, 0);
  const rollover = Object.values(lines).reduce(
    (total, line) => total + Number(line.rollover_amount || 0),
    0,
  );
  // **What arrives this month, not one twelfth of the year.** Being paid every
  // two weeks means ten months hold two cheques and two hold three; showing
  // the average in a two-cheque month plans money that will not turn up. The
  // stored `expected_income` stays as a manual override for anyone who wants
  // one, but the counted figure leads when the pay dates are known.
  const countedIncome = context ? Number(context.income.month_total) : null;
  const income =
    countedIncome !== null && context?.income.exact
      ? countedIncome
      : Number(expectedIncome || 0);
  /* The card panel and the category plan answer different questions and were
     stacked on one page, so reading either meant scrolling past the other.
     Tabs rather than a second page: it is still the budget, and the month
     picker and totals above belong to both. */
  const [tab, setTab] = useState<"plan" | "cards">("plan");

  const cards = context?.cards;
  const cardsUnpaid = Number(cards?.unpaid_total ?? 0);
  const cardsUnbudgeted = Number(cards?.unbudgeted_total ?? 0);
  const cardsOwed = Number(cards?.balance_total ?? 0);

  /**
   * Cards grouped the way his spreadsheet grouped them: his, hers, shared.
   *
   * Shared last and always present when it has cards, because "whose is this"
   * is the question the grouping exists to answer — two of these are called
   * "Chase Prime" and two "Discover", and the name alone cannot tell them
   * apart. Owner order follows the data rather than a hardcoded pair, so a
   * third person joining does not need code.
   */
  const cardGroups = useMemo(() => {
    const rows = cards?.cards ?? [];
    const byOwner = new Map<string, CardRow[]>();
    for (const card of rows) {
      const key = card.owner_name ?? "";
      const bucket = byOwner.get(key);
      if (bucket) bucket.push(card);
      else byOwner.set(key, [card]);
    }
    return [...byOwner.entries()]
      .sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)))
      .map(([owner, items]) => ({
        owner: owner || "Shared",
        cards: items,
        owed: items.reduce((sum, item) => sum + Number(item.balance_owed), 0),
      }));
  }, [cards]);
  const remaining =
    mode === "flex" ? Number(flexAmount || 0) - spent : planned + rollover - spent;
  const spendingTarget =
    mode === "flex" ? Number(flexAmount || 0) : planned + rollover;
  // Nothing planned at all is its own state, not 100% of nothing. It used to
  // fall through to "100% used" beside "Plan needs attention" in red, which
  // accused you of overspending a budget you had not written yet — and did it
  // on day one of the month, when the honest message is "let's set one".
  // Beside Remaining, never inside it. Every one of those charges is already
  // counted as spending in the month it was made — folding the statement into
  // `spent` would count the same money twice. This is the *cash* question:
  // what still has to leave the account before the month is out.
  //
  // **And it subtracts `unbudgeted_total`, not `unpaid_total`.** Subtracting
  // the whole statement made exactly the double-count the line above warns
  // about, from the other side: a statement spans two budget months, and the
  // half that falls in *this* one is already inside `spent`. Alex caught it —
  // "$102.35 after card payments" on a month he knew had about $1,655 left.
  // What remains after cards is what is left of the plan, less only the card
  // money this month has not already planned for.
  const afterCards = remaining - cardsUnbudgeted;
  /**
   * **How much money is left, which is not what Remaining answers.**
   *
   * Remaining is how much of the plan is unspent: `planned − spent`. It never
   * looks at income, so on a month where the plan is smaller than the pay it
   * cannot tell you what is genuinely spare. Alex asked for both, in his own
   * arithmetic:
   *
   *   "we roughly have $2,670 left over each month" — income less the plan
   *   "we had to spend roughly $1,014.95 of unplanned money"
   *   "that number should be closer to $1,655"
   *
   * So: what came in, less what the plan has already claimed, less what got
   * spent that the plan never claimed. Money inside a category's plan is not
   * subtracted twice — the plan reserved it the moment it was written.
   *
   * August 2026: $6,860.92 − $4,240.42 − $1,170.45 = $1,450.05.
   */
  const leftOver =
    income -
    (mode === "flex" ? Number(flexAmount || 0) : planned) -
    unplannedSpend;
  // "2 of Alex's paydays land in August" reads as an answer; "biweekly x 26 /
  // 12" reads as a formula somebody has to check.
  const payLine = (() => {
    const counted = context?.income.sources.filter(
      (row) => row.payments !== null,
    );
    if (!counted?.length) return "Editable monthly estimate";
    return counted
      .map((row) => `${row.payments} × ${row.name}`)
      .join(" · ");
  })();
  // Only offer the override where the question exists. Twice a month is twice
  // in every month; there is nothing to toggle.
  const hasExtraCadence = Boolean(
    context?.income.sources.some(
      (row) =>
        row.payments !== null &&
        (row.cadence === "biweekly" || row.cadence === "weekly"),
    ),
  );
  const unplanned = spendingTarget <= 0;
  const budgetUsed = unplanned ? 0 : (spent / spendingTarget) * 100;
  const monthProgress = (() => {
    const now = new Date();
    if (
      now.getFullYear() !== month.getFullYear() ||
      now.getMonth() !== month.getMonth()
    ) return null;
    return (now.getDate() / new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()) * 100;
  })();
  const visibleCategories = useMemo(
    () =>
      categories.filter((category) => {
        if (focus === "all") return true;
        const line = lines[category.id] ?? emptyLine(category.id);
        const categorySpent = spending[category.name] ?? 0;
        const available =
          Number(line.planned_amount || 0) +
          Number(line.rollover_amount || 0) -
          categorySpent;
        if (focus === "attention") {
          return available < 0 || (categorySpent > 0 && !line.planned_amount);
        }
        return (
          Number(line.planned_amount || 0) > 0 ||
          Number(line.rollover_amount || 0) > 0 ||
          categorySpent > 0
        );
      }),
    [categories, focus, lines, spending],
  );

  // Whatever the earners add up to becomes the month's expected income. Kept
  // in state rather than derived so an existing budget saved before income
  // sources existed still shows its stored figure until they are set up.
  const handleIncomeTotal = useCallback((total: number) => {
    if (total > 0) setExpectedIncome(String(total));
  }, []);

  function updateLine(categoryId: string, patch: Partial<BudgetLine>) {
    setLines((current) => ({
      ...current,
      [categoryId]: { ...current[categoryId], ...patch },
    }));
  }

  function moveMonth(offset: number) {
    setNotice("");
    setLoading(true);
    setMonth(
      (current) =>
        new Date(current.getFullYear(), current.getMonth() + offset, 1),
    );
  }

  async function save() {
    setSaving(true);
    setError("");
    setNotice("");
    const monthValue = monthKey(month);
    try {
      await apiFetch(`/budgets/${monthValue}`, {
        method: "PUT",
        body: JSON.stringify({
          month: monthValue,
          mode,
          expected_income: Number(expectedIncome || 0),
          extra_paycheque: extraPaycheque,
          flex_amount: Number(flexAmount || 0),
          lines: categories.map((category) => {
            const line = lines[category.id] ?? emptyLine(category.id);
            return {
              category_id: category.id,
              planned_amount: Number(line.planned_amount || 0),
              rollover_enabled: line.rollover_enabled,
              non_monthly_target:
                line.non_monthly_target === null ||
                line.non_monthly_target === ""
                  ? null
                  : Number(line.non_monthly_target),
              non_monthly_due_date: line.non_monthly_due_date || null,
            };
          }),
        }),
      });
      setNotice("Monthly budget saved.");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not save budget",
      );
    } finally {
      setSaving(false);
    }
  }

  async function copyPreviousMonth() {
    setSaving(true);
    setError("");
    setNotice("");
    const previous = new Date(month.getFullYear(), month.getMonth() - 1, 1);
    try {
      const previousBudget = await apiFetch<Budget>(`/budgets/${monthKey(previous)}`);
      const previousLines = new Map(
        previousBudget.lines.map((line) => [line.category_id, line]),
      );
      setMode(previousBudget.mode);
      setExpectedIncome(String(previousBudget.expected_income ?? 0));
      setFlexAmount(String(previousBudget.flex_amount ?? 0));
      setLines(
        Object.fromEntries(
          categories.map((category) => {
            const source = previousLines.get(category.id);
            return [
              category.id,
              source
                ? {
                    ...source,
                    id: undefined,
                    category_id: category.id,
                    rollover_amount: 0,
                  }
                : emptyLine(category.id),
            ];
          }),
        ),
      );
      setFocus("funded");
      setNotice(
        `${new Intl.DateTimeFormat("en-US", { month: "long" }).format(previous)} plan copied. Review it, then save this month.`,
      );
    } catch (reason) {
      setError(
        reason instanceof ApiError && reason.status === 404
          ? "The previous month does not have a saved budget yet."
          : reason instanceof Error
            ? reason.message
            : "Could not copy the previous month",
      );
    } finally {
      setSaving(false);
    }
  }

  const monthLabel = new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
  }).format(month);

  return (
    <>
      <div className="page-heading budget-heading">
        <div>
          <p className="eyebrow">{monthLabel} plan</p>
          <h1>A budget that bends without breaking.</h1>
          <p className="subtle">
            Plan by category or use a single flexible spending target.
          </p>
        </div>
        <div className="heading-actions">
          <button className="ghost-button" disabled={saving} onClick={() => void copyPreviousMonth()} type="button">
            <Copy size={15} /> Copy previous month
          </button>
          <button className="primary-button" disabled={saving} onClick={save}>
            {saving ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <Save size={16} />
            )}
            Save month
          </button>
        </div>
      </div>

      <div className="toolbar budget-toolbar">
        <div className="budget-mode" aria-label="Budget mode">
          <button
            aria-pressed={mode === "category"}
            className={mode === "category" ? "active" : ""}
            onClick={() => setMode("category")}
            type="button"
          >
            Category budget
          </button>
          <button
            aria-pressed={mode === "flex"}
            className={mode === "flex" ? "active" : ""}
            onClick={() => setMode("flex")}
            type="button"
          >
            Flex budget
          </button>
        </div>
        <div className="month-switcher">
          <button aria-label="Previous month" onClick={() => moveMonth(-1)}>
            <ChevronLeft size={15} />
          </button>
          <span>
            <CalendarRange size={14} /> {monthLabel}
          </span>
          <button aria-label="Next month" onClick={() => moveMonth(1)}>
            <ChevronRight size={15} />
          </button>
        </div>
      </div>

      {error && <div className="page-error">{error}</div>}
      {notice && (
        <div className="settings-notice">
          <Save size={14} /> {notice}
        </div>
      )}

      {loading ? (
        <div className="account-loading">
          <LoaderCircle className="spin" size={21} />
          Loading monthly plan…
        </div>
      ) : (
        <>
          <section aria-label="Monthly budget fundamentals" className="metric-grid budget-metrics">
            <article className="metric-card neutral budget-metric income">
              <span>Expected income</span>
              <strong>{currency(income)}</strong>
              {context?.income.exact ? (
                <small>
                  {payLine}
                  {countedIncome !== null &&
                    Math.abs(countedIncome - Number(context.income.average_total)) >
                      0.5 && (
                      <em className="budget-average-note">
                        {" "}
                        · {currency(Number(context.income.average_total))} averaged
                        over the year
                      </em>
                    )}
                </small>
              ) : (
                <small>Editable monthly estimate</small>
              )}
            </article>
            <article className="metric-card red budget-metric planned">
              <span>{mode === "flex" ? "Flex target" : "Planned"}</span>
              <strong>
                {currency(
                  mode === "flex" ? Number(flexAmount || 0) : planned,
                )}
              </strong>
              <small>
                {income
                  ? `${Math.round(((mode === "flex" ? Number(flexAmount || 0) : planned) / income) * 100)}% of income`
                  : "Add expected income"}
              </small>
            </article>
            <article className="metric-card orange budget-metric spent">
              <span>Spent</span>
              <strong>{currency(spent)}</strong>
              <small>Eligible categorized spending</small>
            </article>
            {/* The tone follows the number. A negative figure in a green card
                says "fine" and "not fine" at the same time. */}
            <article className={`metric-card budget-metric remaining ${remaining < 0 ? "red" : "green"}`}>
              <span>Remaining</span>
              <strong>{currency(remaining)}</strong>
              {/* Only when there is something to say. A statement whose
                  charges all fall in this month is fully budgeted for, and
                  repeating Remaining underneath itself with a different label
                  invites the reader to look for a difference that is not
                  there. */}
              {cardsUnbudgeted > 0 ? (
                <small>
                  <b className={afterCards < 0 ? "negative" : ""}>
                    {currency(afterCards)}
                  </b>{" "}
                  after last month&rsquo;s card charges
                </small>
              ) : (
                <small>{currency(rollover)} of the plan carried forward</small>
              )}
            </article>
            {/* **Deliberately the second green card**, sitting beside
                Remaining rather than replacing it. They are different
                questions and Alex asked to see both: Remaining is how much of
                the plan is unspent, this is how much money is actually spare.
                Labelling one of them "Remaining" and hiding the other is what
                made the page unreadable — he could not get it to agree with
                his own arithmetic because it was never answering him. */}
            <article
              className={`metric-card budget-metric leftover ${!income ? "neutral" : leftOver < 0 ? "red" : "green"}`}
            >
              <span>Left over</span>
              {/* No income figure means no answer, not an answer of minus the
                  whole plan. Showing −$1,500 in red because nobody has entered
                  a paycheck yet is a false alarm about a month that may be
                  perfectly funded. */}
              <strong>{income ? currency(leftOver) : "—"}</strong>
              <small>
                {income
                  ? unplannedSpend > 0
                    ? `Expected income minus the plan minus ${currency(unplannedSpend)} in unplanned spending`
                    : "Expected income minus the plan; no unplanned spending"
                  : "Add expected income to see this"}
              </small>
            </article>
          </section>

          {context?.income.exact && hasExtraCadence && (
            <CollapsibleSection
              storageKey="paycheques"
              summary={
                context.income.has_extra_paycheque
                  ? "three this month"
                  : "two this month"
              }
              title="Paychecks"
            >
            <section className="paycheque-toggle">
              <div>
                <strong>
                  {context.income.has_extra_paycheque
                    ? `${monthLabel} is a three-paycheck month`
                    : `${monthLabel} is an ordinary two-paycheck month`}
                </strong>
                <p>
                  Worked out from the paydays on file. Override it for this
                  month if a check lands a day on either side of the boundary and
                  the bank disagrees with the calendar.
                </p>
              </div>
              <div className="paycheque-options" role="group" aria-label="Paycheck count">
                {[
                  { value: null, label: "Auto" },
                  { value: false, label: "Two" },
                  { value: true, label: "Three" },
                ].map((option) => (
                  <button
                    aria-pressed={extraPaycheque === option.value}
                    className={extraPaycheque === option.value ? "selected" : ""}
                    key={String(option.value)}
                    onClick={() => setExtraPaycheque(option.value)}
                    type="button"
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </section>
            </CollapsibleSection>
          )}

          {cards && cards.cards.length > 0 && (
            <nav className="budget-tabs" aria-label="Budget sections">
              <button
                aria-current={tab === "plan"}
                className={tab === "plan" ? "active" : ""}
                onClick={() => setTab("plan")}
                type="button"
              >
                Plan
              </button>
              <button
                aria-current={tab === "cards"}
                className={tab === "cards" ? "active" : ""}
                onClick={() => setTab("cards")}
                type="button"
              >
                Credit cards
                <span>{currency(cardsOwed)}</span>
              </button>
            </nav>
          )}

          {tab === "cards" && cards && cards.cards.length > 0 && (
            /* Shown, never added in. Each of these charges is already counted
               as spending in the month it happened; the panel answers a
               different question — what still has to leave the account. */
            <section className="card-obligations">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Statements this month</p>
                  <h2>Credit cards</h2>
                </div>
                {/* The headline is what is owed across every card — the
                    figure his spreadsheet totalled and then added to rent.
                    What is still to pay this month rides underneath it,
                    because that is a different question and conflating the two
                    is how you end up paying the wrong number. */}
                <span className="card-obligations-total">
                  <small>Owed across {cards.cards.length} card{cards.cards.length === 1 ? "" : "s"}</small>
                  <strong className={cardsOwed > 0 ? "negative" : "positive"}>
                    {currency(cardsOwed)}
                  </strong>
                  {/* Not "of it". The statement total and the balance are
                      different quantities — a month of charges can exceed what
                      is currently owed, because payments have been made
                      against it — and "$1,655.86 of $630.98" reads as an
                      arithmetic error. */}
                  <em>
                    {/* "billed" was wrong once `unpaid_total` started being
                        clamped by the real balance: a card can be billed
                        $1,300 and still owe $300 because the rest was paid
                        mid-cycle. This is what is left to pay, and it now says
                        so. The per-card rows still show what was billed. */}
                    {cardsUnpaid > 0
                      ? `${currency(cardsUnpaid)} still to pay`
                      : "statements all settled"}
                  </em>
                </span>
              </div>
              {cardGroups.map((group) => (
                <div className="card-owner-group" key={group.owner}>
                  <p className="card-owner-heading">
                    <span>{group.owner}</span>
                    <strong>{currency(group.owed)}</strong>
                  </p>
                  <ul>
                    {group.cards.map((card) => (
                      <li className={card.paid ? "settled" : ""} key={card.account_id}>
                        <div>
                          <strong>{card.name}</strong>
                          <small>
                            {card.closes_on ? (
                              <>
                                Closes {new Intl.DateTimeFormat("en-US", {
                                  month: "short",
                                  day: "numeric",
                                }).format(new Date(`${card.closes_on}T12:00:00`))}
                                {" · covers "}
                                {new Intl.DateTimeFormat("en-US", {
                                  month: "short",
                                  day: "numeric",
                                }).format(new Date(`${card.covers_from}T12:00:00`))}
                                {" onward"}
                                {/* "Still open" and "paid" together reads as a
                                    contradiction. Once they have paid it, the
                                    cycle being technically unfinished is not
                                    the story. */}
                                {card.provisional && !card.paid && " · still open"}
                              </>
                            ) : (
                              "No statement day set — balance counts, timing unknown"
                            )}
                          </small>
                        </div>
                        <span className="card-obligation-amount">
                          <strong>{currency(Number(card.balance_owed))}</strong>
                          {/* The figure above is always the balance, so the
                              caption only earns its place when the statement
                              says something different. "$0.00 due" beside
                              "$4.32" is a riddle, not information. */}
                          <small>
                            {card.paid
                              ? "paid"
                              : Number(card.amount) > 0
                                ? `${currency(Number(card.amount))} billed`
                                : "balance"}
                          </small>
                          {/* Where the Remaining caption's number comes from.
                              Without this the budget says "$X after last
                              month's card charges" and no row on the page adds
                              up to X. */}
                          {!card.paid && Number(card.unbudgeted) > 0 && (
                            <small className="card-obligation-carried">
                              {currency(Number(card.unbudgeted))} from last month
                            </small>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
              <p className="card-obligations-note">
                Not added to Spent — every charge above is already counted in
                the month it was made. This is what you owe, not extra spending.
                {cards.unconfigured > 0 &&
                  ` ${cards.unconfigured} card${cards.unconfigured === 1 ? "" : "s"} ${cards.unconfigured === 1 ? "has" : "have"} no statement day, so ${cards.unconfigured === 1 ? "its" : "their"} balance is counted but not dated.`}
              </p>
            </section>
          )}

          {tab === "plan" && (
          <>
          <section
            className={`budget-pacing-card ${unplanned ? "unplanned" : remaining < 0 ? "over" : ""}`}
          >
            <span className="budget-pacing-icon"><PiggyBank size={21} /></span>
            <div className="budget-pacing-copy">
              {unplanned ? (
                <>
                  <small>No plan for {monthLabel} yet</small>
                  <strong>{currency(spent)} spent so far</strong>
                  <p className="budget-pacing-hint">
                    Give a category an amount below and this starts tracking
                    against it — or copy last month&apos;s plan to begin.
                  </p>
                </>
              ) : (
                <>
                  <small>{remaining >= 0 ? "Safe to spend" : "Plan needs attention"}</small>
                  <strong>{currency(Math.abs(remaining))}{remaining < 0 ? " over target" : " remaining"}</strong>
                  <div className="budget-pacing-track" aria-label={`${Math.round(budgetUsed)} percent of budget used`}>
                    <span style={{ width: `${Math.min(100, budgetUsed)}%` }} />
                    {monthProgress !== null && <i style={{ left: `${monthProgress}%` }} title={`${Math.round(monthProgress)}% through the month`} />}
                  </div>
                </>
              )}
            </div>
            {!unplanned && (
              <div className="budget-pacing-stats">
                <span><small>Budget used</small><strong>{Math.round(budgetUsed)}%</strong></span>
                <span><small>Month elapsed</small><strong>{monthProgress === null ? "—" : `${Math.round(monthProgress)}%`}</strong></span>
              </div>
            )}
          </section>

          {/* On the Budget page rather than a page of its own: a goal is a
              plan, and it belongs beside the rest of the month's plan. */}
          <CollapsibleSection
            defaultOpen={false}
            storageKey="goals"
            title="Saving for"
          >
            <GoalsManager />
          </CollapsibleSection>

          <article className="panel budget-live-panel">
            <div className="budget-controls">
              {/* Named earners rather than one box. Two people paid different
                  amounts on different schedules cannot be described by a
                  single number — and working that number out by hand is how
                  the bi-weekly mistake gets made. */}
              <CollapsibleSection
                defaultOpen={false}
                storageKey="earners"
                summary={income ? `${currency(income)} this month` : undefined}
                title="Who earns what"
              >
                <IncomeSources onTotalChange={handleIncomeTotal} />
              </CollapsibleSection>
              {mode === "flex" && (
                <label className="field">
                  <span>Flexible spending target</span>
                  <div className="money-input">
                    <span>$</span>
                    <input
                      min="0"
                      onChange={(event) => setFlexAmount(event.target.value)}
                      step="0.01"
                      type="number"
                      value={flexAmount}
                    />
                  </div>
                </label>
              )}
            </div>

            <p className="budget-carry-note">
              <strong>Carry</strong> keeps whatever is left in a category at
              the end of the month and adds it to next month&apos;s amount. It
              does not copy the figure you typed, and overspending carries
              nothing.
            </p>

            <div className="budget-focus-bar">
              <div>
                <small>Category focus</small>
                <strong>
                  {visibleCategories.length} of {categories.length} visible
                </strong>
              </div>
              <div className="segmented-control" aria-label="Budget category focus">
                <button
                  className={focus === "all" ? "active" : ""}
                  onClick={() => setFocus("all")}
                  type="button"
                >
                  All
                </button>
                <button
                  className={focus === "funded" ? "active" : ""}
                  onClick={() => setFocus("funded")}
                  type="button"
                >
                  Funded & active
                </button>
                <button
                  className={focus === "attention" ? "active spending" : ""}
                  onClick={() => setFocus("attention")}
                  type="button"
                >
                  Needs attention
                </button>
              </div>
            </div>

            <div className="budget-editor">
              <div className="budget-editor-row live header">
                <span>Category</span>
                <span>Planned</span>
                <span>Spent</span>
                <span>Remaining</span>
                <span>Rollover</span>
              </div>
              {visibleCategories.map((category) => {
                const line = lines[category.id] ?? emptyLine(category.id);
                const categorySpent = spending[category.name] ?? 0;
                const categoryBudget =
                  Number(line.planned_amount || 0) +
                  Number(line.rollover_amount || 0);
                const categoryAvailable = categoryBudget - categorySpent;
                // Share of this category's own plan that is gone. Unplanned
                // categories have no denominator, so they get no bar rather
                // than a full one — spending $40 against no plan is not "100%
                // used", it is a category nobody has budgeted yet.
                const used =
                  categoryBudget > 0
                    ? Math.min((categorySpent / categoryBudget) * 100, 100)
                    : 0;
                const overspent = categoryAvailable < 0;
                return (
                  <div
                    className={`budget-editor-row live ${category.flex_bucket}`}
                    key={category.id}
                  >
                    <span className="budget-category-name">
                      <i style={{ background: category.color }} />
                      <span>
                        <strong>{category.name}</strong>
                        <small>
                          {category.group_name} ·{" "}
                          {category.flex_bucket.replace("_", " ")}
                        </small>
                      </span>
                    </span>
                    {/* Each value carries its own label. On a phone the header
                        row is gone — it cannot survive a card layout — so a
                        figure that does not say what it is would be exactly
                        the unreadable column of numbers this replaces. */}
                    <div className="budget-cell plan" data-label="Planned">
                      <div className="money-input compact">
                        <span>$</span>
                        <input
                          aria-label={`${category.name} planned amount`}
                          min="0"
                          onChange={(event) =>
                            updateLine(category.id, {
                              planned_amount: event.target.value,
                            })
                          }
                          step="0.01"
                          type="number"
                          value={line.planned_amount}
                        />
                      </div>
                    </div>
                    <div className="budget-cell spent" data-label="Spent">
                      <span>{currency(categorySpent)}</span>
                    </div>
                    <div className="budget-cell left" data-label="Remaining">
                      <span className={overspent ? "negative" : ""}>
                        {currency(categoryAvailable)}
                      </span>
                    </div>
                    {/* "Carry" carries the *leftover*, not the amount you
                        typed — plan 500, spend 420, and next month's line
                        starts 80 ahead of whatever you plan for it.
                        Overspending carries nothing rather than a debt. That
                        is not what the word implies on its own, and he read it
                        as "copy this figure forward", so the title says which
                        it is. */}
                    <label
                      className="rollover-toggle"
                      title={`Anything left over in ${category.name} at the end of the month is added to next month's amount. Overspending carries nothing.`}
                    >
                      <input
                        aria-label={`Carry unspent ${category.name} into next month`}
                        checked={line.rollover_enabled}
                        onChange={(event) =>
                          updateLine(category.id, {
                            rollover_enabled: event.target.checked,
                          })
                        }
                        type="checkbox"
                      />
                      Carry
                    </label>
                    {/* Spans the whole row, so it reads as belonging to the
                        category rather than to any one column. Decorative:
                        every number it encodes is already written above it. */}
                    {categoryBudget > 0 && (
                      <div
                        aria-hidden="true"
                        className={`budget-line-track${overspent ? " over" : ""}`}
                      >
                        <span style={{ width: `${used}%` }} />
                      </div>
                    )}
                    {(category.flex_bucket === "non_monthly" ||
                      category.flex_bucket === "goal") && (
                      <div className="budget-target-row">
                        <label className="field">
                          <span>Target amount</span>
                          <input
                            aria-label={`${category.name} target amount`}
                            min="0"
                            onChange={(event) =>
                              updateLine(category.id, {
                                non_monthly_target: event.target.value,
                              })
                            }
                            placeholder="0.00"
                            step="0.01"
                            type="number"
                            value={line.non_monthly_target ?? ""}
                          />
                        </label>
                        <label className="field">
                          <span>Target date</span>
                          <input
                            aria-label={`${category.name} target date`}
                            onChange={(event) =>
                              updateLine(category.id, {
                                non_monthly_due_date:
                                  event.target.value || null,
                              })
                            }
                            type="date"
                            value={line.non_monthly_due_date ?? ""}
                          />
                        </label>
                      </div>
                    )}
                  </div>
                );
              })}
              {!visibleCategories.length && (
                <div className="budget-focus-empty">
                  <strong>No categories match this focus.</strong>
                  <small>
                    Try another view or add a plan amount to make a category
                    active.
                  </small>
                </div>
              )}
            </div>
          </article>
          </>
          )}
        </>
      )}
    </>
  );
}
