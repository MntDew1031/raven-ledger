"use client";

import {
  ArrowDownLeft,
  ArrowUpRight,
  Check,
  LoaderCircle,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";
import type { Account } from "@/lib/accounts";
import type { Category } from "@/lib/finance";

type Step = "account" | "amount" | "direction" | "category";

const STEPS: Step[] = ["account", "amount", "direction", "category"];

/**
 * Recording a transaction on an account nobody syncs, one question at a time.
 *
 * The full transaction form asks for account, merchant, amount, date, category,
 * notes and tags at once. That is the right shape for editing something that
 * already exists, and the wrong shape for the thing this is actually for:
 * standing in a shop having just spent cash. So this asks four questions —
 * where, how much, which way, what for — and fills the rest in.
 *
 * Direction is its own question rather than a minus sign because the sign
 * convention is the single most common way a hand-entered transaction goes in
 * backwards, and "money out" cannot be typed wrong.
 */
export function QuickTransactionDialog({
  accounts,
  categories,
  initialAccountId = "",
  onClose,
  onSaved,
}: {
  accounts: Account[];
  categories: Category[];
  initialAccountId?: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  // Accounts nobody syncs are the whole point, so they lead. Connected
  // accounts stay available — a cash withdrawal still has to go somewhere —
  // but they are not what this is for.
  const ordered = useMemo(
    () =>
      [...accounts].sort((left, right) =>
        left.is_manual === right.is_manual
          ? left.name.localeCompare(right.name)
          : left.is_manual
            ? -1
            : 1,
      ),
    [accounts],
  );

  const [step, setStep] = useState<Step>(
    initialAccountId ? "amount" : "account",
  );
  const [accountId, setAccountId] = useState(initialAccountId);
  const [amount, setAmount] = useState("");
  const [outgoing, setOutgoing] = useState<boolean | null>(null);
  const [merchant, setMerchant] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const account = ordered.find((item) => item.id === accountId);
  const cents = Math.round(Number.parseFloat(amount || "0") * 100);
  const amountValid = Number.isFinite(cents) && cents > 0;

  // Only categories that can hold money moving this way. Offering income
  // categories for a purchase is how a hand-entered row ends up inflating
  // earnings.
  const usable = useMemo(
    () =>
      categories.filter((item) =>
        outgoing ? !item.group_is_income : item.group_is_income,
      ),
    [categories, outgoing],
  );
  const shown = usable.length > 0 ? usable : categories;

  async function save(categoryId: string) {
    setSaving(true);
    setError("");
    try {
      await apiFetch("/transactions", {
        method: "POST",
        body: JSON.stringify({
          account_id: accountId,
          category_id: categoryId || null,
          merchant_name: merchant.trim() || (outgoing ? "Cash spending" : "Cash received"),
          amount: ((outgoing ? -cents : cents) / 100).toFixed(2),
          posted_date: new Date().toISOString().slice(0, 10),
          reviewed: true,
        }),
      });
      onSaved(
        `${currency(cents / 100)} ${outgoing ? "out of" : "into"} ${account?.name ?? "your account"}.`,
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "That could not be saved",
      );
      setSaving(false);
    }
  }

  const stepIndex = STEPS.indexOf(step);

  return (
    <div className="dialog-layer">
      <button
        aria-label="Close dialog"
        className="dialog-backdrop"
        onClick={onClose}
      />
      <section
        aria-label="Quick transaction"
        aria-modal="true"
        className="account-dialog quick-transaction"
        role="dialog"
      >
        <div className="dialog-header">
          <div>
            <p className="eyebrow">Quick add</p>
            <h2>
              {step === "account" && "Which account?"}
              {step === "amount" && "How much?"}
              {step === "direction" && "Which way did it go?"}
              {step === "category" && "What was it for?"}
            </h2>
            <p>
              {step === "account" &&
                "Accounts you keep by hand are listed first — those are the ones nothing else records for you."}
              {step === "amount" && account?.name}
              {step === "direction" &&
                `${currency(cents / 100)} on ${account?.name ?? "this account"}`}
              {step === "category" &&
                `${currency(cents / 100)} ${outgoing ? "out of" : "into"} ${account?.name ?? "this account"}`}
            </p>
          </div>
          <button aria-label="Close" className="dialog-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <ol className="quick-steps" aria-hidden="true">
          {STEPS.map((item, index) => (
            <li
              className={index <= stepIndex ? "done" : ""}
              key={item}
            />
          ))}
        </ol>

        <div className="quick-body">
          {step === "account" && (
            <ul className="quick-choices">
              {ordered.map((item) => (
                <li key={item.id}>
                  <button
                    onClick={() => {
                      setAccountId(item.id);
                      setStep("amount");
                    }}
                    type="button"
                  >
                    <strong>{item.name}</strong>
                    <small>
                      {item.is_manual ? "Kept by hand" : "Synced automatically"}
                      {" · "}
                      {currency(Number(item.current_balance))}
                    </small>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {step === "amount" && (
            <form
              className="quick-amount"
              onSubmit={(event) => {
                event.preventDefault();
                if (amountValid) setStep("direction");
              }}
            >
              <label>
                <span className="quick-currency">$</span>
                <input
                  aria-label="Amount"
                  autoFocus
                  inputMode="decimal"
                  min="0"
                  onChange={(event) => setAmount(event.target.value)}
                  placeholder="0.00"
                  step="0.01"
                  type="number"
                  value={amount}
                />
              </label>
              <input
                aria-label="What was it (optional)"
                className="quick-merchant"
                maxLength={120}
                onChange={(event) => setMerchant(event.target.value)}
                placeholder="Where was it? (optional)"
                type="text"
                value={merchant}
              />
              <button
                className="primary-button"
                disabled={!amountValid}
                type="submit"
              >
                Continue
              </button>
            </form>
          )}

          {step === "direction" && (
            <div className="quick-direction">
              <button
                className="outgoing"
                onClick={() => {
                  setOutgoing(true);
                  setStep("category");
                }}
                type="button"
              >
                <ArrowUpRight size={22} />
                <strong>Money out</strong>
                <small>I spent this</small>
              </button>
              <button
                className="incoming"
                onClick={() => {
                  setOutgoing(false);
                  setStep("category");
                }}
                type="button"
              >
                <ArrowDownLeft size={22} />
                <strong>Money in</strong>
                <small>I received this</small>
              </button>
            </div>
          )}

          {step === "category" && (
            <>
              <ul className="quick-choices categories">
                {shown.map((item) => (
                  <li key={item.id}>
                    <button
                      disabled={saving}
                      onClick={() => void save(item.id)}
                      type="button"
                    >
                      <i style={{ background: item.color }} />
                      <strong>{item.name}</strong>
                      <small>{item.group_name}</small>
                    </button>
                  </li>
                ))}
              </ul>
              <button
                className="text-button"
                disabled={saving}
                onClick={() => void save("")}
                type="button"
              >
                Skip — decide later
              </button>
            </>
          )}
        </div>

        {error && <p className="dialog-error">{error}</p>}

        <div className="dialog-actions full">
          {stepIndex > 0 && !saving && (
            <button
              className="ghost-button"
              onClick={() => setStep(STEPS[stepIndex - 1])}
              type="button"
            >
              Back
            </button>
          )}
          {saving && (
            <span className="quick-saving">
              <LoaderCircle className="spin" size={14} /> Saving…
            </span>
          )}
          {!saving && step === "category" && (
            <span className="quick-hint">
              <Check size={13} /> Choosing a category saves it
            </span>
          )}
        </div>
      </section>
    </div>
  );
}
