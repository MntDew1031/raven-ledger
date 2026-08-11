"use client";

import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";
import { prettyMerchant } from "@/lib/merchant";

type Detail = {
  id: string;
  name: string;
  color: string;
  months: { month: string; amount: string }[];
  typical_month: string;
  merchants: { merchant: string; total: string; count: number }[];
  largest: { id: string; merchant: string; amount: string; posted_date: string }[];
};

function monthLabel(value: string): string {
  const d = new Date(`${value}T12:00:00`);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleDateString(undefined, { month: "short" });
}

/**
 * Why is this category's number what it is.
 *
 * Three things answer that between them, and the third is the one people
 * actually want: a category is usually either a habit or one big thing, and
 * the two call for completely different responses. A month-by-month shape
 * shows which, the merchants show where it goes, and the largest charges show
 * whether one evening explains the whole figure.
 */
export function CategoryDetail({
  categoryId,
  onClose,
}: {
  categoryId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiFetch<Detail>(`/reports/category/${categoryId}`)
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not load that");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [categoryId]);

  const chart = (detail?.months ?? []).map((m) => ({
    month: m.month,
    amount: Number(m.amount),
  }));
  const busiest = Math.max(...chart.map((c) => c.amount), 0);

  return (
    <div className="dialog-layer">
      <button aria-label="Close" className="dialog-backdrop" onClick={onClose} />
      <section aria-modal="true" className="account-dialog category-detail" role="dialog">
        <div className="dialog-header">
          <div>
            <p className="eyebrow">Category</p>
            <h2>{detail?.name ?? "Loading…"}</h2>
            {detail && (
              <p>
                A typical month is{" "}
                <strong>{currency(Number(detail.typical_month))}</strong> — the
                middle of the last few rather than the average, so one unusual
                month does not set the expectation.
              </p>
            )}
          </div>
          <button aria-label="Close" className="dialog-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {error && <p className="dialog-error">{error}</p>}

        {detail && (
          <>
            {chart.length > 1 && (
              <div className="category-trend">
                <ResponsiveContainer height={130} width="100%">
                  <AreaChart data={chart} margin={{ top: 6, right: 4, bottom: 0, left: 4 }}>
                    <defs>
                      <linearGradient id="catFill" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.38} />
                        <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <XAxis
                      axisLine={false}
                      dataKey="month"
                      tick={{ fontSize: 11 }}
                      tickFormatter={monthLabel}
                      tickLine={false}
                    />
                    <Tooltip
                      formatter={(v) => currency(Number(v))}
                      labelFormatter={(l) => monthLabel(String(l))}
                    />
                    <Area
                      dataKey="amount"
                      fill="url(#catFill)"
                      stroke="var(--accent)"
                      strokeWidth={2}
                      type="monotone"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}

            {detail.merchants.length > 0 && (
              <div className="category-block">
                <h3>Where it goes</h3>
                <ul className="category-merchants">
                  {detail.merchants.map((m) => (
                    <li key={m.merchant}>
                      <span>{prettyMerchant(m.merchant)}</span>
                      <small>
                        {m.count} time{m.count === 1 ? "" : "s"}
                      </small>
                      <strong>{currency(Number(m.total))}</strong>
                      <i>
                        <span
                          style={{
                            width: `${busiest ? Math.max((Number(m.total) / Number(detail.merchants[0].total)) * 100, 2) : 0}%`,
                          }}
                        />
                      </i>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail.largest.length > 0 && (
              <div className="category-block">
                <h3>The biggest ones</h3>
                <ul className="category-largest">
                  {detail.largest.map((t) => (
                    <li key={t.id}>
                      <span>{prettyMerchant(t.merchant)}</span>
                      <small>{t.posted_date}</small>
                      <strong className="negative">
                        {currency(Math.abs(Number(t.amount)))}
                      </strong>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {!detail.merchants.length && (
              <p className="subtle">
                Nothing recorded against this category yet.
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}
