"use client";

import { CalendarClock, TrendingDown, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";

type Event = { kind: "income" | "bill"; label: string; amount: string; date?: string };

type Forecast = {
  balance: string;
  safe_to_spend: string;
  next_payday: string | null;
  days_until_payday: number | null;
  committed_before_payday: string;
  bills_before_payday: Event[];
  low_point: { date: string; balance: string };
  timeline: { date: string; balance: string; events: Event[] }[];
  has_income_sources: boolean;
  has_bills: boolean;
};

function shortDate(value: string): string {
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/**
 * What is safe to spend, and where the next tight spot is.
 *
 * A monthly "remaining" figure says nothing about whether rent has gone out
 * yet or whether payday is tomorrow. These two numbers are what actually
 * decide whether a purchase is fine right now.
 */
export function CashForecast() {
  const [data, setData] = useState<Forecast | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiFetch<Forecast>("/forecast")
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(
            cause instanceof Error ? cause.message : "Could not load the forecast",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <p className="negative">{error}</p>;
  if (!data) return null;

  const safe = Number(data.safe_to_spend);
  const low = Number(data.low_point.balance);
  const chart = data.timeline.map((point) => ({
    date: point.date,
    balance: Number(point.balance),
  }));
  const lowIndex = data.timeline.findIndex(
    (point) => point.date === data.low_point.date,
  );

  // Without either half of the picture the numbers would be confidently wrong,
  // so say what is missing rather than showing a figure built on nothing.
  if (!data.has_income_sources && !data.has_bills) {
    return (
      <article className="panel forecast-panel">
        <div className="settings-card-heading">
          <h2>Safe to spend</h2>
          <p className="subtle">
            Add who earns what on the Budget page, and let Raven find your
            recurring bills. Then this can tell you what is genuinely yours
            between now and payday.
          </p>
        </div>
      </article>
    );
  }

  return (
    <article className="panel forecast-panel">
      <div className="forecast-headline">
        <span className={`forecast-icon${safe < 0 ? " over" : ""}`}>
          <Wallet size={20} />
        </span>
        <div>
          <small>
            Safe to spend
            {data.days_until_payday !== null
              ? ` for ${data.days_until_payday} more day${data.days_until_payday === 1 ? "" : "s"}`
              : ""}
          </small>
          <strong className={safe < 0 ? "negative" : ""}>
            {currency(safe)}
          </strong>
          <p className="subtle">
            {Number(data.balance) > 0 ? currency(Number(data.balance)) : "Nothing"}{" "}
            in cash
            {Number(data.committed_before_payday) < 0
              ? `, less ${currency(Math.abs(Number(data.committed_before_payday)))} of bills due`
              : ""}
            {data.next_payday ? ` before ${shortDate(data.next_payday)}` : ""}.
            {/* No incoming money is counted: being told you have less than you
                do is an annoyance, being told you have more is an overdraft. */}
            {data.next_payday ? " Your next pay is not counted in this." : ""}
          </p>
        </div>
      </div>

      {data.bills_before_payday.length > 0 && (
        <ul className="forecast-bills">
          {data.bills_before_payday.map((bill, index) => (
            <li key={`${bill.label}-${index}`}>
              <span>{bill.label}</span>
              <small>{bill.date ? shortDate(bill.date) : ""}</small>
              <strong>{currency(Number(bill.amount))}</strong>
            </li>
          ))}
        </ul>
      )}

      <div className="forecast-chart-heading">
        <span>
          <CalendarClock size={13} /> Next 60 days
        </span>
        <span className={low < 0 ? "negative" : ""}>
          <TrendingDown size={13} /> Lowest {currency(low)} on{" "}
          {shortDate(data.low_point.date)}
        </span>
      </div>

      <div className="forecast-chart">
        <ResponsiveContainer height={170} width="100%">
          <AreaChart data={chart} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="forecastFill" x1="0" x2="0" y1="0" y2="1">
                <stop
                  offset="0%"
                  stopColor="var(--accent)"
                  stopOpacity={0.35}
                />
                <stop
                  offset="100%"
                  stopColor="var(--accent)"
                  stopOpacity={0.02}
                />
              </linearGradient>
            </defs>
            <XAxis
              axisLine={false}
              dataKey="date"
              interval="preserveStartEnd"
              minTickGap={44}
              tick={{ fontSize: 9 }}
              tickFormatter={shortDate}
              tickLine={false}
            />
            <YAxis
              axisLine={false}
              tick={{ fontSize: 9 }}
              tickFormatter={(value: number) =>
                Math.abs(value) >= 1000
                  ? `$${Math.round(value / 1000)}k`
                  : `$${Math.round(value)}`
              }
              tickLine={false}
              width={40}
            />
            <Tooltip
              formatter={(value) => currency(Number(value))}
              labelFormatter={(label) => shortDate(String(label))}
            />
            <Area
              dataKey="balance"
              fill="url(#forecastFill)"
              stroke="var(--accent)"
              strokeWidth={2}
              type="monotone"
            />
            {lowIndex >= 0 && (
              // The number that actually answers "can we afford this" — almost
              // never today's balance.
              <ReferenceDot
                fill={low < 0 ? "var(--red)" : "var(--orange)"}
                r={4}
                stroke="var(--panel)"
                strokeWidth={2}
                x={data.low_point.date}
                y={low}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {!data.has_bills && (
        <p className="subtle forecast-note">
          No recurring bills detected yet, so this line only reflects your pay.
          Raven finds bills after it has seen each one a few times.
        </p>
      )}
    </article>
  );
}
