"use client";

import {
  AlertTriangle,
  Bookmark,
  Check,
  Download,
  LoaderCircle,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { CashFlowChart, SpendingDonut } from "@/components/financial-charts";
import { CashFlowSankey } from "@/components/cash-flow-sankey";
import { apiFetch } from "@/lib/api";
import { currency, monthLabel as formatMonthLabel, percent } from "@/lib/format";

type CashFlowRow = {
  month: string;
  income: string | number;
  spending: string | number;
};

type SpendingRow = {
  name: string;
  color: string;
  amount: string | number;
};

type Trend = {
  name: string;
  current: string | number;
  previous: string | number;
  change_percent: string | number | null;
};

type Anomaly = {
  type: "amount_spike" | "possible_duplicate";
  transaction_id: string;
  merchant: string;
  amount: string | number;
  message: string;
};

type ReportPreset = "1m" | "3m" | "6m" | "ytd" | "1y";
type ReportPeriod = ReportPreset | "custom";

const REPORT_PRESETS: ReportPreset[] = ["1m", "3m", "6m", "ytd", "1y"];
const REPORT_DEFAULT_KEY = "raven-report-default-period";
const reportDefaultListeners = new Set<() => void>();

function dateParam(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function presetLabel(value: ReportPreset) {
  return value === "ytd" ? "YTD" : value.toUpperCase();
}

function presetRange(value: ReportPreset, today = new Date()) {
  const presetStart =
    value === "1m"
      ? new Date(today.getFullYear(), today.getMonth(), 1)
      : value === "3m"
        ? new Date(today.getFullYear(), today.getMonth() - 2, 1)
        : value === "6m"
          ? new Date(today.getFullYear(), today.getMonth() - 5, 1)
          : value === "ytd"
            ? new Date(today.getFullYear(), 0, 1)
            : new Date(today.getFullYear(), today.getMonth() - 11, 1);
  return { start: dateParam(presetStart), end: dateParam(today) };
}

function savedReportDefault(): ReportPreset {
  try {
    const saved = window.localStorage.getItem(REPORT_DEFAULT_KEY);
    if (REPORT_PRESETS.some((value) => value === saved)) {
      return saved as ReportPreset;
    }
  } catch {
    // Private browsing or a locked-down browser can refuse storage. The
    // report remains useful; it simply opens at Raven's 1-month default.
  }
  return "1m";
}

function serverReportDefault(): ReportPreset {
  return "1m";
}

function subscribeReportDefault(listener: () => void) {
  const handleStorage = (event: StorageEvent) => {
    if (event.key === REPORT_DEFAULT_KEY) listener();
  };
  reportDefaultListeners.add(listener);
  window.addEventListener("storage", handleStorage);
  return () => {
    reportDefaultListeners.delete(listener);
    window.removeEventListener("storage", handleStorage);
  };
}

function saveReportDefault(value: ReportPreset) {
  try {
    window.localStorage.setItem(REPORT_DEFAULT_KEY, value);
  } catch {
    // The control still reflects this session. A browser that blocks local
    // storage will fall back to 1M the next time the page opens.
  }
  for (const listener of reportDefaultListeners) listener();
}

export function ReportsManager() {
  const defaultPreset = useSyncExternalStore(
    subscribeReportDefault,
    savedReportDefault,
    serverReportDefault,
  );
  // `null` means "follow this device's default". A deliberate selection
  // overrides it for this visit without silently rewriting the preference.
  const [periodOverride, setPeriodOverride] = useState<ReportPeriod | null>(
    null,
  );
  const [customRange, setCustomRange] = useState(() => presetRange("1m"));
  const preset = periodOverride ?? defaultPreset;
  const range = preset === "custom" ? customRange : presetRange(preset);
  const { start, end } = range;
  const [cashFlow, setCashFlow] = useState<CashFlowRow[]>([]);
  const [spending, setSpending] = useState<SpendingRow[]>([]);
  const [trends, setTrends] = useState<Trend[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiFetch<CashFlowRow[]>(`/reports/cash-flow?start=${start}&end=${end}`),
      apiFetch<SpendingRow[]>(`/reports/spending?start=${start}&end=${end}`),
      apiFetch<Trend[]>(`/reports/trends?start=${start}&end=${end}`),
      apiFetch<Anomaly[]>(`/reports/anomalies?start=${start}&end=${end}`),
    ])
      .then(([cashFlowResult, spendingResult, trendResult, anomalyResult]) => {
        if (cancelled) return;
        setCashFlow(cashFlowResult);
        setSpending(spendingResult);
        setTrends(trendResult);
        setAnomalies(anomalyResult);
        setError("");
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error ? reason.message : "Could not load reports",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [end, start]);

  const totals = useMemo(
    () =>
      cashFlow.reduce(
        (result, item) => ({
          income: result.income + Number(item.income),
          spending: result.spending + Number(item.spending),
        }),
        { income: 0, spending: 0 },
      ),
    [cashFlow],
  );
  const savings = totals.income - totals.spending;
  const savingsRate = totals.income ? savings / totals.income : 0;
  const chartData = cashFlow.map((item) => ({
    month: formatMonthLabel(item.month),
    income: Number(item.income),
    spending: Number(item.spending),
  }));
  const donutData = spending.map((item) => ({
    name: item.name,
    value: Number(item.amount),
    color: item.color,
  }));
  const topCategory = spending.reduce<SpendingRow | null>(
    (largest, item) =>
      !largest || Number(item.amount) > Number(largest.amount) ? item : largest,
    null,
  );
  const averageMonthlySavings = cashFlow.length ? savings / cashFlow.length : 0;

  function applyPreset(value: ReportPreset) {
    const nextRange = presetRange(value);
    setPeriodOverride(value);
    if (nextRange.start !== start || nextRange.end !== end) {
      setLoading(true);
    }
  }

  function makeCurrentPresetDefault() {
    if (preset === "custom") return;
    saveReportDefault(preset);
    setPeriodOverride(null);
  }

  return (
    <>
      <div className="page-heading reports-heading">
        <div>
          <p className="eyebrow">Reports</p>
          <h1>See the pattern behind the purchase.</h1>
          <p className="subtle">
            Live cash flow, category movement, savings rate, and unusual
            activity.
          </p>
        </div>
        {/* Secondary, and styled like it. As a primary button it was the
            single loudest thing on the page — a full-width gradient slab above
            every figure the page exists to show. */}
        <a
          className="ghost-button"
          href="/api/v1/households/export?format=csv"
        >
          <Download size={15} /> Export CSV
        </a>
      </div>

      <nav aria-label="Report sections" className="report-navigation">
        <a aria-current="page" className="active" href="#cash-flow-report">
          Cash flow
        </a>
        <a href="#spending-report">Spending</a>
        <a href="#trends-report">Trends</a>
        <a href="#anomalies-report">Review</a>
      </nav>

      <div className="toolbar report-toolbar">
        <div className="report-period-controls">
          <div className="report-presets" aria-label="Report period presets">
            {REPORT_PRESETS.map((value) => (
              <button
                aria-pressed={preset === value}
                className={preset === value ? "active" : ""}
                key={value}
                onClick={() => applyPreset(value)}
                type="button"
              >
                {presetLabel(value)}
              </button>
            ))}
          </div>
          <button
            aria-label={
              preset === "custom"
                ? `Default report period is ${presetLabel(defaultPreset)}`
                : preset === defaultPreset
                  ? `${presetLabel(defaultPreset)} is the default report period on this device`
                  : `Make ${presetLabel(preset)} the default report period on this device`
            }
            aria-pressed={preset !== "custom" && preset === defaultPreset}
            className={`report-default-button ${preset !== "custom" && preset === defaultPreset ? "active" : ""}`}
            disabled={preset === "custom"}
            onClick={makeCurrentPresetDefault}
            title="Saved on this device"
            type="button"
          >
            {preset !== "custom" && preset === defaultPreset ? (
              <Check aria-hidden size={13} />
            ) : (
              <Bookmark aria-hidden size={13} />
            )}
            {preset === "custom"
              ? `Default: ${presetLabel(defaultPreset)}`
              : preset === defaultPreset
                ? `Default: ${presetLabel(defaultPreset)}`
                : `Make ${presetLabel(preset)} default`}
          </button>
        </div>
        <label className="field">
          <span>From</span>
          <input
            max={end}
            onChange={(event) => {
              setLoading(true);
              setCustomRange({ start: event.target.value, end });
              setPeriodOverride("custom");
            }}
            type="date"
            value={start}
          />
        </label>
        <label className="field">
          <span>Through</span>
          <input
            min={start}
            onChange={(event) => {
              setLoading(true);
              setCustomRange({ start, end: event.target.value });
              setPeriodOverride("custom");
            }}
            type="date"
            value={end}
          />
        </label>
      </div>

      {error && <div className="page-error">{error}</div>}
      {loading ? (
        <div className="account-loading">
          <LoaderCircle className="spin" size={21} />
          Calculating household reports…
        </div>
      ) : (
        <>
          <section aria-label="Cash flow totals" className="report-summary">
            <div className="income">
              <span>Income</span>
              <strong className="positive">{currency(totals.income)}</strong>
            </div>
            <div className="spending">
              <span>Spending</span>
              <strong className="negative">{currency(totals.spending)}</strong>
            </div>
            <div className="savings">
              <span>Net savings</span>
              <strong className={savings >= 0 ? "positive" : "negative"}>
                {currency(savings)}
              </strong>
            </div>
            <div className="rate">
              <span>Savings rate</span>
              <strong>{percent(savingsRate)}</strong>
            </div>
          </section>

          <div className="report-primary-flow" id="cash-flow-report">
            <CashFlowSankey end={end} start={start} />
          </div>

          <section className="report-highlights" aria-label="Report highlights">
            <article>
              <small>Largest spending area</small>
              <strong>{topCategory?.name ?? "No spending yet"}</strong>
              <span>
                {topCategory
                  ? currency(Number(topCategory.amount))
                  : "Add transactions to begin"}
              </span>
            </article>
            <article className={averageMonthlySavings >= 0 ? "wealth" : "obligation"}>
              <small>Average monthly savings</small>
              <strong>{currency(averageMonthlySavings)}</strong>
              <span>Across {cashFlow.length || 0} reported month{cashFlow.length === 1 ? "" : "s"}</span>
            </article>
            <article className={anomalies.length ? "obligation" : "wealth"}>
              <small>Items worth a look</small>
              <strong>{anomalies.length}</strong>
              <span>{anomalies.length ? "Unusual transactions detected" : "No anomalies detected"}</span>
            </article>
          </section>

          <section className="report-grid">
            <article className="panel report-card" id="trends-report">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Selected period</p>
                  <h2>Cash flow</h2>
                </div>
                <span
                  className={`status-pill ${
                    savingsRate >= 0 ? "positive" : "negative"
                  }`}
                >
                  {percent(savingsRate)} saved
                </span>
              </div>
              <CashFlowChart data={chartData} />
            </article>

            <article className="panel report-card" id="spending-report">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Selected period</p>
                  <h2>Spending mix</h2>
                </div>
                <strong>{currency(totals.spending)}</strong>
              </div>
              <SpendingDonut data={donutData} />
              <div className="spending-legend">
                {donutData.slice(0, 6).map((item) => (
                  <span key={item.name}>
                    <i style={{ background: item.color }} />
                    {item.name}
                    <strong>{currency(item.value)}</strong>
                  </span>
                ))}
              </div>
            </article>

            <article className="panel report-movement-card">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Compared with prior period</p>
                  <h2>Category movement</h2>
                </div>
                <TrendingUp className="positive" size={19} />
              </div>
              {trends.length ? (
                <div className="report-stat-list">
                  {trends.slice(0, 7).map((trend) => {
                    const change =
                      trend.change_percent === null
                        ? null
                        : Number(trend.change_percent);
                    return (
                      <div className="report-stat" key={trend.name}>
                        <div>
                          <strong>{trend.name}</strong>
                          <small>
                            {currency(Number(trend.current))} vs{" "}
                            {currency(Number(trend.previous))}
                          </small>
                        </div>
                        <strong
                          className={
                            change === null
                              ? ""
                              : change > 0
                                ? "negative"
                                : "positive"
                          }
                        >
                          {change === null
                            ? "New"
                            : `${change > 0 ? "+" : ""}${change.toFixed(0)}%`}
                        </strong>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="report-empty">No category trends yet.</div>
              )}
            </article>

            <article className="panel" id="anomalies-report">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Review assistant</p>
                  <h2>Spending anomalies</h2>
                </div>
                <AlertTriangle className="negative" size={19} />
              </div>
              {anomalies.length ? (
                anomalies.slice(0, 6).map((anomaly) => (
                  <a
                    className="anomaly"
                    href={`/transactions?transaction=${anomaly.transaction_id}`}
                    key={`${anomaly.type}-${anomaly.transaction_id}`}
                  >
                    {anomaly.type === "amount_spike" ? (
                      <TrendingUp className="negative" size={18} />
                    ) : (
                      <TrendingDown className="negative" size={18} />
                    )}
                    <div>
                      <strong>
                        {anomaly.type === "amount_spike"
                          ? `Unusual amount at ${anomaly.merchant}`
                          : `Possible duplicate at ${anomaly.merchant}`}
                      </strong>
                      <p>
                        {currency(Number(anomaly.amount))} · {anomaly.message}
                      </p>
                    </div>
                  </a>
                ))
              ) : (
                <div className="report-empty">
                  No unusual spending detected for this period.
                </div>
              )}
            </article>
          </section>
        </>
      )}
    </>
  );
}
