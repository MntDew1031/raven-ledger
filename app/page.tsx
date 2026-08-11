"use client";

import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Eye,
  EyeOff,
  LoaderCircle,
  PencilLine,
  Plus,
  RotateCcw,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { CashFlowChart, NetWorthChart } from "@/components/financial-charts";
import { OnboardingCard } from "@/components/onboarding-card";
import { Account, accountBalance } from "@/lib/accounts";
import { AnimatedCurrency } from "@/components/animated-number";
import { CashForecast } from "@/components/cash-forecast";
import { QuickTransactionDialog } from "@/components/quick-transaction";
import { apiFetch } from "@/lib/api";
import { Category } from "@/lib/finance";
import { currency, monthLabel as formatMonthLabel, percent } from "@/lib/format";

type DashboardSummary = {
  assets: string;
  liabilities: string;
  net_worth: string;
  month_income: string;
  month_spending: string;
  savings_rate: string;
  reserved: string;
  needs_review: number;
};

type NetWorthSnapshot = {
  snapshot_date: string;
  net_worth: string;
};

type CashFlowRow = {
  month: string;
  income: string;
  spending: string;
};

type SpendingRow = {
  name: string;
  amount: string;
};

type Transaction = {
  id: string;
  account_id: string;
  merchant_name: string | null;
  original_description: string;
  amount: string;
  posted_date: string;
  pending: boolean;
  is_transfer: boolean;
  excluded_from_budget: boolean;
};

type BudgetLine = {
  category_id: string;
  planned_amount: string;
};

type Budget = {
  expected_income: string;
  lines: BudgetLine[];
};

type RecurringItem = {
  id: string;
  display_name: string;
  direction: "inflow" | "outflow";
  cadence: string;
  average_amount: string;
  next_due: string;
  is_active: boolean;
};

const dashboardWidgets = [
  { key: "overview", label: "Financial overview", detail: "Net worth, monthly progress, and available cash" },
  { key: "trend", label: "Net worth trend", detail: "Your historical household value" },
  { key: "accounts", label: "Account balances", detail: "Cash, investments, and debts" },
  { key: "cashflow", label: "Monthly cash flow", detail: "Income, spending, and savings" },
  { key: "upcoming", label: "Upcoming bills", detail: "Recurring payments and monthly planning" },
  { key: "budget", label: "Budget progress", detail: "Category spending against your plan" },
  { key: "activity", label: "Latest activity", detail: "Your most recent transactions" },
  { key: "insight", label: "Monthly insight", detail: "A quick household savings signal" },
] as const;

type DashboardWidgetKey = (typeof dashboardWidgets)[number]["key"];
type DashboardVisibility = Record<DashboardWidgetKey, boolean>;

const defaultVisibility = Object.fromEntries(
  dashboardWidgets.map((widget) => [widget.key, true]),
) as DashboardVisibility;

function dateParam(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

// Long enough that a quiet fortnight is genuinely unusual rather than just a
// slow week, short enough that a manual account cannot drift a whole month.
const QUIET_ACCOUNT_DAYS = 14;

// Accounts nobody keeps a ledger for. You update a loan or a retirement
// account by writing down what it is worth now; there is no stream of
// transactions to fall behind on, so asking for one is pure noise.
const BALANCE_ONLY_TYPES = new Set([
  "loan",
  "mortgage",
  "debt",
  "investment",
  "retirement",
  "brokerage",
]);

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [netWorth, setNetWorth] = useState<NetWorthSnapshot[]>([]);
  const [cashFlow, setCashFlow] = useState<CashFlowRow[]>([]);
  const [spending, setSpending] = useState<SpendingRow[]>([]);
  const [recurring, setRecurring] = useState<RecurringItem[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  // Captured once per mount so list filtering stays pure during render.
  const [nowMs] = useState(() => Date.now());
  const [quickAdd, setQuickAdd] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [customizing, setCustomizing] = useState(false);
  const [widgetVisibility, setWidgetVisibility] =
    useState<DashboardVisibility>(defaultVisibility);
  const [widgetOrder, setWidgetOrder] = useState<DashboardWidgetKey[]>(
    dashboardWidgets.map((widget) => widget.key),
  );

  useEffect(() => {
    let frame: number | undefined;
    try {
      const stored = window.localStorage.getItem("raven-dashboard-widgets");
      const savedVisibility = stored
        ? (JSON.parse(stored) as Partial<DashboardVisibility>)
        : null;
      const storedOrder = window.localStorage.getItem("raven-dashboard-order");
      let nextOrder: DashboardWidgetKey[] | null = null;
      if (storedOrder) {
        const savedOrder = JSON.parse(storedOrder) as DashboardWidgetKey[];
        const valid = savedOrder.filter((key) =>
          dashboardWidgets.some((widget) => widget.key === key),
        );
        const missing = dashboardWidgets
          .map((widget) => widget.key)
          .filter((key) => !valid.includes(key));
        nextOrder = [...valid, ...missing];
      }
      if (savedVisibility || nextOrder) {
        frame = window.requestAnimationFrame(() => {
          if (savedVisibility) {
            setWidgetVisibility({ ...defaultVisibility, ...savedVisibility });
          }
          if (nextOrder) setWidgetOrder(nextOrder);
        });
      }
    } catch {
      // A private browser or malformed old preference should not break the dashboard.
    }
    return () => {
      if (frame !== undefined) window.cancelAnimationFrame(frame);
    };
  }, []);

  function updateWidget(key: DashboardWidgetKey) {
    setWidgetVisibility((current) => {
      const next = { ...current, [key]: !current[key] };
      window.localStorage.setItem(
        "raven-dashboard-widgets",
        JSON.stringify(next),
      );
      return next;
    });
  }

  function resetWidgets() {
    setWidgetVisibility(defaultVisibility);
    setWidgetOrder(dashboardWidgets.map((widget) => widget.key));
    window.localStorage.removeItem("raven-dashboard-widgets");
    window.localStorage.removeItem("raven-dashboard-order");
  }

  function moveWidget(key: DashboardWidgetKey, direction: -1 | 1) {
    setWidgetOrder((current) => {
      const index = current.indexOf(key);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      window.localStorage.setItem("raven-dashboard-order", JSON.stringify(next));
      return next;
    });
  }

  useEffect(() => {
    let cancelled = false;
    const now = new Date();
    const reportStart = new Date(now.getFullYear(), now.getMonth() - 5, 1);
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
    const queryStart = dateParam(reportStart);
    const currentStart = dateParam(monthStart);
    const end = dateParam(now);

    Promise.all([
      apiFetch<DashboardSummary>("/dashboard/summary"),
      apiFetch<Account[]>("/accounts"),
      apiFetch<Transaction[]>("/transactions?limit=5"),
      apiFetch<NetWorthSnapshot[]>("/dashboard/net-worth"),
      apiFetch<CashFlowRow[]>(
        `/reports/cash-flow?start=${queryStart}&end=${end}`,
      ),
      apiFetch<SpendingRow[]>(
        `/reports/spending?start=${currentStart}&end=${end}`,
      ),
      apiFetch<RecurringItem[]>("/recurring").catch(
        (): RecurringItem[] => [],
      ),
      // A household with no budget for this month is normal, not an error.
      apiFetch<Budget>(`/budgets/${currentStart}`).catch((): Budget | null =>
        null,
      ),
      apiFetch<Category[]>("/categories").catch((): Category[] => []),
    ])
      .then(
        ([
          summaryResult,
          accountResult,
          transactionResult,
          netWorthResult,
          cashFlowResult,
          spendingResult,
          recurringResult,
          budgetResult,
          categoryResult,
        ]) => {
          if (cancelled) return;
          setRecurring(recurringResult);
          setBudget(budgetResult);
          setCategories(categoryResult);
          setSummary(summaryResult);
          setAccounts(accountResult);
          setTransactions(transactionResult);
          setNetWorth(netWorthResult);
          setCashFlow(cashFlowResult);
          setSpending(spendingResult);
          setError("");
        },
      )
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error ? reason.message : "Could not load dashboard",
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

  const accountMap = useMemo(
    () => new Map(accounts.map((account) => [account.id, account])),
    [accounts],
  );
  const liquidCash = accounts
    .filter(
      (account) =>
        account.kind === "asset" &&
        ["checking", "savings", "cash"].includes(account.type),
    )
    .reduce((total, account) => total + accountBalance(account), 0);
  const netWorthChart = netWorth.slice(-24).map((item) => ({
    month: new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: netWorth.length <= 12 ? "numeric" : undefined,
    }).format(new Date(`${item.snapshot_date}T12:00:00`)),
    value: Number(item.net_worth),
  }));
  const cashFlowChart = cashFlow.map((item) => ({
    month: formatMonthLabel(item.month),
    income: Number(item.income),
    spending: Number(item.spending),
  }));
  const monthlyIncome = Number(summary?.month_income ?? 0);
  const monthlySpending = Number(summary?.month_spending ?? 0);
  const monthlySaved = monthlyIncome - monthlySpending;
  const monthLabel = new Intl.DateTimeFormat("en-US", {
    month: "long",
  }).format(new Date());

  const netWorthValue = Number(summary?.net_worth ?? 0);
  const pendingReview = summary?.needs_review ?? null;
  const previousReview = useRef<number | null>(null);
  const [justCleared, setJustCleared] = useState(false);

  useEffect(() => {
    if (pendingReview === null) return;
    const before = previousReview.current;
    previousReview.current = pendingReview;
    // Fires only on the edge from "work outstanding" to "none".
    if (before === null || before === 0 || pendingReview !== 0) return;
    setJustCleared(true);
    const timer = setTimeout(() => setJustCleared(false), 4000);
    return () => clearTimeout(timer);
  }, [pendingReview]);

  const totalAssets = Number(summary?.assets ?? 0);
  const totalLiabilities = Math.abs(Number(summary?.liabilities ?? 0));
  // Change since roughly a month ago, using the oldest snapshot within the
  // window so a household with sparse history still gets a real comparison.
  const monthAgoSnapshot = netWorth
    .filter((item) => {
      const age =
        nowMs - new Date(`${item.snapshot_date}T12:00:00`).getTime();
      // Old enough to be a real comparison, recent enough to mean "a month".
      return age >= 5 * 86_400_000 && age <= 45 * 86_400_000;
    })
    .at(0);
  const netWorthChange = monthAgoSnapshot
    ? netWorthValue - Number(monthAgoSnapshot.net_worth)
    : null;
  const assetShare = totalAssets + totalLiabilities
    ? (totalAssets / (totalAssets + totalLiabilities)) * 100
    : 100;

  const accountsByKind = useMemo(() => {
    const groups = new Map<string, Account[]>();
    for (const account of accounts) {
      const label =
        account.kind === "liability"
          ? "What you owe"
          : ["checking", "savings", "cash"].includes(account.type)
            ? "Cash"
            : "Investments and other";
      groups.set(label, [...(groups.get(label) ?? []), account]);
    }
    return [...groups.entries()];
  }, [accounts]);

  const categoryByName = useMemo(
    () => new Map(categories.map((item) => [item.name, item])),
    [categories],
  );

  // Budget progress joins planned amounts to this month's actual spending.
  const budgetProgress = useMemo(() => {
    if (!budget?.lines?.length) return [];
    const plannedByCategory = new Map(
      budget.lines.map((line) => [line.category_id, Number(line.planned_amount)]),
    );
    return spending
      .map((row) => {
        const category = categoryByName.get(row.name);
        const planned = category
          ? (plannedByCategory.get(category.id) ?? 0)
          : 0;
        return {
          name: row.name,
          color: category?.color ?? "#7f8b81",
          spent: Number(row.amount),
          planned,
        };
      })
      .filter((row) => row.planned > 0 || row.spent > 0)
      .sort((a, b) => b.spent - a.spent)
      .slice(0, 5);
  }, [budget, spending, categoryByName]);

  const spendingMix = useMemo(
    () =>
      spending.slice(0, 6).map((row) => ({
        name: row.name,
        value: Number(row.amount),
        color: categoryByName.get(row.name)?.color ?? "#7f8b81",
      })),
    [spending, categoryByName],
  );
  const upcomingBills = recurring
    .filter((item) => {
      if (!item.is_active || item.direction !== "outflow") return false;
      const due = new Date(`${item.next_due}T12:00:00`).getTime();
      const horizon = nowMs + 30 * 86_400_000;
      return due <= horizon;
    })
    .slice(0, 4);
  const nextBill = upcomingBills[0];

  // A manual account receives nothing on its own. Left alone it silently drifts
  // out of date and its balance quietly stops meaning anything, which is worse
  // than an obviously empty account because it still looks like a number.
  // Connected accounts are deliberately excluded: when their sync breaks the
  // fix is to reconnect, and telling somebody to type in transactions Plaid is
  // about to deliver would create duplicates.
  const staleManualAccounts = useMemo(() => {
    const cutoff = new Date(nowMs - QUIET_ACCOUNT_DAYS * 86400000)
      .toISOString()
      .slice(0, 10);
    const latestByAccount = new Map<string, string>();
    for (const item of transactions) {
      const seen = latestByAccount.get(item.account_id);
      if (!seen || item.posted_date > seen) {
        latestByAccount.set(item.account_id, item.posted_date);
      }
    }
    return accounts
      .filter((account) => account.is_manual)
      .filter((account) => !BALANCE_ONLY_TYPES.has(account.type))
      .map((account) => ({
        account,
        lastSeen: latestByAccount.get(account.id) ?? null,
      }))
      // **It has to have gone quiet, which means it once made a noise.** An
      // account with no transactions at all was never being tracked that way:
      // a 401k or a student loan is a balance you update, not a ledger you
      // keep. Treating "never" as "very stale" put fifteen permanent
      // un-dismissable nags on Alex's dashboard — eight student loans, two
      // car loans, four retirement accounts and the Apple Card — each asking
      // him to type in transactions that are never going to exist.
      .filter(({ lastSeen }) => lastSeen !== null && lastSeen < cutoff);
  }, [accounts, nowMs, transactions]);
  const daysUntilNextBill = nextBill
    ? Math.ceil(
        (new Date(`${nextBill.next_due}T12:00:00`).getTime() - nowMs) /
          86_400_000,
      )
    : null;

  if (loading) {
    return (
      <AppShell active="Dashboard">
        <div className="account-loading dashboard-loading">
          <LoaderCircle className="spin" size={22} />
          Building your household overview…
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell active="Dashboard">
      <div className="page-heading dashboard-heading">
        <div>
          <p className="eyebrow">{monthLabel} overview</p>
          <h1>Your money, in one calm place.</h1>
          <p className="subtle">
            A live household view built from your accounts and transactions.
          </p>
        </div>
        <div className="heading-actions dashboard-heading-actions">
          <button
            className="ghost-button"
            onClick={() => setCustomizing(true)}
            type="button"
          >
            <SlidersHorizontal size={15} /> Customize
          </button>
          <a
            className="primary-button"
            href={
              summary?.needs_review
                ? "/transactions?review=needs-review"
                : "/transactions"
            }
          >
            {summary?.needs_review
              ? `Review ${summary.needs_review} transaction${summary.needs_review === 1 ? "" : "s"}`
              : "Review transactions"}
            <ChevronRight size={15} />
          </a>
        </div>
      </div>

      {error && <div className="page-error">{error}</div>}

      {staleManualAccounts.length > 0 && (
        <section className="manual-nudge" aria-label="Accounts waiting on you">
          <span className="manual-nudge-icon">
            <PencilLine size={18} />
          </span>
          <div>
            <strong>
              {staleManualAccounts.length === 1
                ? `${staleManualAccounts[0].account.name} has been quiet`
                : `${staleManualAccounts.length} accounts have been quiet`}
            </strong>
            <p>
              {staleManualAccounts.length === 1 && !staleManualAccounts[0].lastSeen
                ? "Nothing has been recorded here yet. Accounts you keep by hand only show what you enter."
                : `Nothing in the last ${QUIET_ACCOUNT_DAYS} days. Accounts you keep by hand do not sync themselves, so their balances drift until you add what has happened.`}
            </p>
          </div>
          <div className="manual-nudge-actions">
            {staleManualAccounts.slice(0, 3).map(({ account }) => (
              <button
                className="ghost-button"
                key={account.id}
                onClick={() => setQuickAdd(account.id)}
                type="button"
              >
                <Plus size={13} /> {account.name}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="financial-pulse" aria-label="Financial pulse">
        <div
          className={[
            summary?.needs_review ? "attention" : "healthy",
            // Only celebrates the transition, not the steady state. Landing on
            // an already-empty queue every morning should feel calm, not like
            // a trophy for doing nothing.
            justCleared ? "queue-cleared" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {summary?.needs_review ? <Clock3 size={17} /> : <CheckCircle2 size={17} />}
          <span>
            <small>Review queue</small>
            <strong>
              {summary?.needs_review
                ? `${summary.needs_review} waiting`
                : justCleared
                  ? "Queue cleared"
                  : "All caught up"}
            </strong>
          </span>
        </div>
        <div className={monthlySaved >= 0 ? "wealth" : "attention"}>
          <ArrowUpRight size={17} />
          <span><small>Monthly pace</small><strong>{monthlySaved >= 0 ? `${currency(monthlySaved)} kept` : `${currency(Math.abs(monthlySaved))} over`}</strong></span>
        </div>
        <div className={nextBill ? "obligation" : "healthy"}>
          <CalendarDays size={17} />
          <span><small>Next obligation</small><strong>{nextBill ? `${nextBill.display_name} · ${daysUntilNextBill! <= 0 ? "due" : `${daysUntilNextBill}d`}` : "Nothing due soon"}</strong></span>
        </div>
      </section>

      <OnboardingCard />

      <section
        className={`hero-grid ${widgetVisibility.overview ? "" : "dashboard-widget-hidden"}`}
      >
        <article className="panel hero-card net-worth-card">
          <p className="eyebrow">Net worth</p>
          {/* A negative net worth does not get the brand treatment. The
              gradient is for the figure you want somebody to look at; owing
              money is a different message and red says it. */}
          <AnimatedCurrency
            className={`hero-value ${netWorthValue < 0 ? "negative" : ""}`}
            value={netWorthValue}
          />
          {netWorthChange !== null ? (
            <p
              className={`hero-change ${netWorthChange >= 0 ? "positive" : "negative"}`}
            >
              {netWorthChange >= 0 ? "▲" : "▼"}{" "}
              {currency(Math.abs(netWorthChange))} over the last month
            </p>
          ) : (
            <p className="hero-change subtle">
              Tracking begins as soon as balances change
            </p>
          )}
          <div className="hero-split" role="img" aria-label={`Assets ${currency(totalAssets)}, debts ${currency(totalLiabilities)}`}>
            <span className="hero-split-assets" style={{ width: `${assetShare}%` }} />
            <span className="hero-split-debts" style={{ width: `${100 - assetShare}%` }} />
          </div>
          <div className="hero-legend">
            <span>
              <em className="dot assets" /> Assets
              <strong>{currency(totalAssets)}</strong>
            </span>
            <span>
              <em className="dot debts" /> Debts
              <strong>{currency(totalLiabilities)}</strong>
            </span>
          </div>
        </article>

        <article className="panel month-card monthly-story-card">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{monthLabel}</p>
              <h2>This month</h2>
            </div>
            <span className="subtle">{percent(Number(summary?.savings_rate ?? 0))} saved</span>
          </div>
          <div className="month-rows">
            <div className="month-row">
              <span>Income</span>
              <strong className="positive">{currency(monthlyIncome)}</strong>
            </div>
            <div className="month-row">
              <span>Spending</span>
              <strong className="negative">{currency(monthlySpending)}</strong>
            </div>
            <div className="month-row total">
              <span>{monthlySaved >= 0 ? "Kept" : "Over budget"}</span>
              <strong className={monthlySaved >= 0 ? "positive" : "negative"}>
                {currency(Math.abs(monthlySaved))}
              </strong>
            </div>
          </div>
          <div className="month-bar">
            <span
              style={{
                width: `${monthlyIncome > 0 ? Math.min(100, (monthlySpending / monthlyIncome) * 100) : 0}%`,
              }}
            />
          </div>
          <small className="subtle">
            {monthlyIncome > 0
              ? `${Math.round((monthlySpending / monthlyIncome) * 100)}% of income spent`
              : "No income recorded this month"}
          </small>
        </article>

        <article className="panel cash-card liquid-cash-card">
          <p className="eyebrow">Cash available</p>
          <AnimatedCurrency className="cash-value" value={liquidCash} />
          <small className="subtle">Checking, savings, and cash</small>
          {summary?.needs_review ? (
            <a className="cash-review" href="/transactions?review=needs-review">
              {summary.needs_review} to review <ChevronRight size={13} />
            </a>
          ) : (
            <span className="cash-review done">Everything reviewed</span>
          )}
        </article>
      </section>

      {/* Above the grid deliberately: "what can I spend right now" is the
          question the dashboard exists to answer, and it is not answerable
          from a monthly figure. */}
      <CashForecast />

      <section className="dashboard-grid">
        <article
          className={`panel chart-panel span-2 ${widgetVisibility.trend ? "" : "dashboard-widget-hidden"}`}
          style={{ order: widgetOrder.indexOf("trend") }}
        >
          <div className="panel-heading">
            <div>
              <p className="eyebrow">All accounts</p>
              <h2>Net worth trend</h2>
            </div>
            <span className="subtle">Recorded automatically</span>
          </div>
          <NetWorthChart data={netWorthChart} />
        </article>

        <article
          className={`panel account-panel ${widgetVisibility.accounts ? "" : "dashboard-widget-hidden"}`}
          style={{ order: widgetOrder.indexOf("accounts") }}
        >
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Balances</p>
              <h2>Accounts</h2>
            </div>
            <a className="text-link" href="/accounts">
              Manage <ChevronRight size={15} />
            </a>
          </div>
          {accounts.length ? (
            <div className="account-groups">
              {accountsByKind.map(([label, group]) => {
                const subtotal = group.reduce(
                  (sum, account) => sum + accountBalance(account),
                  0,
                );
                return (
                  <div className="account-group" key={label}>
                    <div className="account-group-heading">
                      <span>{label}</span>
                      <strong className={subtotal < 0 ? "negative" : ""}>
                        {currency(subtotal)}
                      </strong>
                    </div>
                    {group.slice(0, 4).map((account) => (
                      <a
                        className="account-line"
                        href={`/accounts?account=${account.id}`}
                        key={account.id}
                      >
                        <span>
                          {account.name}
                          {account.mask && <small>••{account.mask}</small>}
                        </span>
                        <strong
                          className={
                            accountBalance(account) < 0 ? "negative" : ""
                          }
                        >
                          {currency(accountBalance(account))}
                        </strong>
                      </a>
                    ))}
                    {group.length > 4 && (
                      <a className="account-more" href="/accounts">
                        {group.length - 4} more
                      </a>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="dashboard-empty compact">
              <WalletCardsIcon />
              <strong>No accounts yet</strong>
              <small>Add one or connect a bank to see balances.</small>
            </div>
          )}
        </article>

        <article
          className={`panel span-2 ${widgetVisibility.cashflow ? "" : "dashboard-widget-hidden"}`}
          style={{ order: widgetOrder.indexOf("cashflow") }}
        >
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Income minus spending</p>
              <h2>Monthly cash flow</h2>
            </div>
            <span
              className={`status-pill ${monthlySaved >= 0 ? "positive" : "negative"}`}
            >
              {monthlySaved >= 0 ? "+" : "-"}
              {currency(Math.abs(monthlySaved))}
            </span>
          </div>
          <CashFlowChart data={cashFlowChart} />
          <div className="cashflow-summary">
            <div>
              <span className="legend-dot income" />
              <small>Income</small>
              <strong>{currency(monthlyIncome)}</strong>
            </div>
            <div>
              <span className="legend-dot spending" />
              <small>Spending</small>
              <strong>{currency(monthlySpending)}</strong>
            </div>
            <div>
              <span className="legend-dot savings" />
              <small>Saved</small>
              <strong>{currency(monthlySaved)}</strong>
            </div>
          </div>
        </article>

        {upcomingBills.length ? (
          <article
            className={`panel ${widgetVisibility.upcoming ? "" : "dashboard-widget-hidden"}`}
            style={{ order: widgetOrder.indexOf("upcoming") }}
          >
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Next 30 days</p>
                <h2>Upcoming bills</h2>
              </div>
              <a className="text-link" href="/automation">
                View all <ChevronRight size={15} />
              </a>
            </div>
            <div className="upcoming-bills-list">
              {upcomingBills.map((item) => {
                const due = new Date(`${item.next_due}T12:00:00`);
                const overdue = due.getTime() < nowMs - 86_400_000;
                return (
                  <div className="upcoming-bill-row" key={item.id}>
                    <div>
                      <strong>{item.display_name}</strong>
                      <small className={overdue ? "negative" : undefined}>
                        {overdue ? "Overdue — " : ""}
                        {new Intl.DateTimeFormat("en-US", {
                          month: "short",
                          day: "numeric",
                        }).format(due)}
                      </small>
                    </div>
                    <em className="negative">
                      {currency(-Number(item.average_amount))}
                    </em>
                  </div>
                );
              })}
            </div>
          </article>
        ) : (
          <article
            className={`panel dashboard-plan-card ${widgetVisibility.upcoming ? "" : "dashboard-widget-hidden"}`}
            style={{ order: widgetOrder.indexOf("upcoming") }}
          >
            <div>
              <p className="eyebrow">Monthly plan</p>
              <h2>Make every dollar intentional.</h2>
              <p>
                Use category budgeting or one flexible spending number, with
                rollovers and non-monthly goals.
              </p>
            </div>
            <a className="primary-button" href="/budgets">
              Open budget <ChevronRight size={15} />
            </a>
          </article>
        )}

        <article
          className={`panel span-2 ${widgetVisibility.budget ? "" : "dashboard-widget-hidden"}`}
          style={{ order: widgetOrder.indexOf("budget") }}
        >
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Budget</p>
              <h2>Where {monthLabel} is going</h2>
            </div>
            <a className="text-link" href="/budgets">
              Open budget <ChevronRight size={15} />
            </a>
          </div>
          {budgetProgress.length ? (
            <div className="budget-progress">
              {budgetProgress.map((row) => {
                const pct = row.planned
                  ? Math.min(100, (row.spent / row.planned) * 100)
                  : 100;
                const over = row.planned > 0 && row.spent > row.planned;
                return (
                  <div className="budget-row" key={row.name}>
                    <div className="budget-row-label">
                      <em
                        aria-hidden="true"
                        className="category-dot"
                        style={{ backgroundColor: row.color }}
                      />
                      <span>{row.name}</span>
                      <strong className={over ? "negative" : ""}>
                        {currency(row.spent)}
                        {row.planned > 0 && (
                          <small> of {currency(row.planned)}</small>
                        )}
                      </strong>
                    </div>
                    <div className="budget-row-track">
                      <span
                        className={over ? "over" : ""}
                        style={{
                          width: `${pct}%`,
                          backgroundColor: over ? undefined : row.color,
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : spendingMix.length ? (
            <div className="budget-progress">
              {spendingMix.map((row) => {
                const largest = spendingMix[0]?.value || 1;
                return (
                  <div className="budget-row" key={row.name}>
                    <div className="budget-row-label">
                      <em
                        aria-hidden="true"
                        className="category-dot"
                        style={{ backgroundColor: row.color }}
                      />
                      <span>{row.name}</span>
                      <strong>{currency(row.value)}</strong>
                    </div>
                    <div className="budget-row-track">
                      <span
                        style={{
                          width: `${(row.value / largest) * 100}%`,
                          backgroundColor: row.color,
                        }}
                      />
                    </div>
                  </div>
                );
              })}
              <p className="subtle budget-hint">
                Set a monthly plan to see these as progress against a target.
              </p>
            </div>
          ) : (
            <div className="dashboard-empty compact">
              <strong>Nothing categorized yet</strong>
              <small>
                Categorize this month&apos;s spending to see where it goes.
              </small>
            </div>
          )}
        </article>

        <article
          className={`panel ${widgetVisibility.activity ? "" : "dashboard-widget-hidden"}`}
          style={{ order: widgetOrder.indexOf("activity") }}
        >
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Latest activity</p>
              <h2>Transactions</h2>
            </div>
            <a className="text-link" href="/transactions">
              View all <ChevronRight size={15} />
            </a>
          </div>
          {transactions.length ? (
            <div className="transaction-list">
              {transactions.map((transaction) => {
                const merchant =
                  transaction.merchant_name || transaction.original_description;
                const amount = Number(transaction.amount);
                // Paying a card posts a *positive* amount, so this list drew a
                // green "+$265.98" for it — the transactions page learned to
                // say otherwise in 1.53.3 and this one had not. The totals
                // above already exclude it; the row has to say so too, or the
                // dashboard still reads as money arriving.
                const notCounted =
                  transaction.is_transfer ||
                  transaction.excluded_from_budget ||
                  (amount > 0 &&
                    accountMap.get(transaction.account_id)?.kind ===
                      "liability");
                const arriving = amount > 0 && !notCounted;
                return (
                  <div className="transaction-row" key={transaction.id}>
                    <span
                      className={`merchant-icon ${arriving ? "green" : "red"}`}
                    >
                      {merchant.slice(0, 1).toUpperCase()}
                    </span>
                    <div>
                      <strong>{merchant}</strong>
                      <small>
                        {accountMap.get(transaction.account_id)?.name ||
                          "Unknown account"}
                      </small>
                    </div>
                    <div className="transaction-amount">
                      <strong
                        className={
                          notCounted
                            ? "uncounted"
                            : arriving
                              ? "positive"
                              : "negative"
                        }
                      >
                        {amount > 0 ? "+" : ""}
                        {currency(amount)}
                      </strong>
                      <small>
                        {new Intl.DateTimeFormat("en-US", {
                          month: "short",
                          day: "numeric",
                        }).format(
                          new Date(`${transaction.posted_date}T12:00:00`),
                        )}
                      </small>
                      {notCounted && (
                        <small className="row-not-counted">
                          {transaction.is_transfer
                            ? "transfer · not counted"
                            : transaction.excluded_from_budget
                              ? "not counted"
                              : "paid onto a card · not income"}
                        </small>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="dashboard-empty compact">
              <strong>No transactions yet</strong>
              <small>Connect Plaid to import recent activity.</small>
            </div>
          )}
        </article>
      </section>

      <section
        className={`insight-banner ${monthlySaved >= 0 ? "positive" : "negative"} ${widgetVisibility.insight ? "" : "dashboard-widget-hidden"}`}
      >
        <div className="insight-icon">
          <ArrowUpRight size={20} />
        </div>
        <div>
          <strong>
            {monthlySaved >= 0
              ? `You have kept ${currency(monthlySaved)} of this month’s income.`
              : `Spending is ${currency(Math.abs(monthlySaved))} above recorded income.`}
          </strong>
          <p>
            Review uncategorized activity regularly to keep this household view
            accurate.
          </p>
        </div>
        <a className="ghost-button" href="/transactions">
          <CalendarDays size={15} /> Review activity
        </a>
      </section>

      {customizing && (
        <div
          aria-label="Customize dashboard"
          aria-modal="true"
          className="dialog-layer"
          onMouseDown={() => setCustomizing(false)}
          role="dialog"
        >
          <section
            className="dashboard-customizer"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="dashboard-customizer-heading">
              <div>
                <p className="eyebrow">Your dashboard</p>
                <h2>Choose what you see</h2>
                <p className="subtle">
                  Keep the parts you use most. This layout is saved on this
                  device.
                </p>
              </div>
              <button
                aria-label="Close dashboard customization"
                className="icon-button"
                onClick={() => setCustomizing(false)}
                type="button"
              >
                <X size={17} />
              </button>
            </div>
            <div className="dashboard-widget-list">
              {widgetOrder.map((key, index) => {
                const widget = dashboardWidgets.find((item) => item.key === key)!;
                const visible = widgetVisibility[widget.key];
                return (
                  <div className={`dashboard-widget-item ${visible ? "visible" : ""}`} key={widget.key}>
                    <button
                      aria-pressed={visible}
                      className="dashboard-widget-toggle"
                      onClick={() => updateWidget(widget.key)}
                      type="button"
                    >
                      <span className="dashboard-widget-icon">
                        {visible ? <Eye size={16} /> : <EyeOff size={16} />}
                      </span>
                      <span>
                        <strong>{widget.label}</strong>
                        <small>{widget.detail}</small>
                      </span>
                    </button>
                    {widget.key === "overview" || widget.key === "insight" ? (
                      <span className="dashboard-widget-pinned">Pinned</span>
                    ) : (
                      <div className="dashboard-widget-move" aria-label={`Move ${widget.label}`}>
                        <button aria-label={`Move ${widget.label} up`} disabled={index <= 1} onClick={() => moveWidget(widget.key, -1)} type="button"><ArrowUp size={13} /></button>
                        <button aria-label={`Move ${widget.label} down`} disabled={index >= widgetOrder.length - 2} onClick={() => moveWidget(widget.key, 1)} type="button"><ArrowDown size={13} /></button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="dashboard-customizer-actions">
              <button className="text-button" onClick={resetWidgets} type="button">
                <RotateCcw size={14} /> Reset
              </button>
              <button
                className="primary-button"
                onClick={() => setCustomizing(false)}
                type="button"
              >
                Done
              </button>
            </div>
          </section>
        </div>
      )}
      {quickAdd !== null && (
        <QuickTransactionDialog
          accounts={accounts}
          categories={categories}
          initialAccountId={quickAdd}
          onClose={() => setQuickAdd(null)}
          onSaved={() => {
            setQuickAdd(null);
            // Net worth, cash, the month figures and the quiet-account list are
            // all derived from this page's data, so re-read rather than trying
            // to patch six things by hand.
            window.location.reload();
          }}
        />
      )}
    </AppShell>
  );
}

function WalletCardsIcon() {
  return (
    <span className="dashboard-empty-icon" aria-hidden="true">
      <Plus size={18} />
    </span>
  );
}
