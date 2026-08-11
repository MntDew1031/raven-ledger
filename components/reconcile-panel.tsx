"use client";

import { CircleAlert, CircleCheck, CircleHelp, Scale } from "lucide-react";
import { useEffect, useState } from "react";
import { accountLabel } from "@/lib/accounts";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";

type Check = {
  account_id: string;
  name: string;
  owner_name: string | null;
  mask: string | null;
  status: "balanced" | "drifted" | "empty" | "not_checkable";
  reason: string;
  stated_balance: string;
  transaction_total: string;
  difference?: string;
  likely?: string;
  transactions: number;
};

type Report = {
  accounts: Check[];
  drifted: number;
  balanced: number;
  not_checkable: number;
};

/**
 * Does each account add up?
 *
 * Five separate classes of bug have corrupted numbers in this ledger and every
 * one was invisible until a figure happened to look odd to a person. They
 * share a shape — the transactions stop agreeing with the balance — so this is
 * the panel that says so before anybody notices by accident.
 */
export function ReconcilePanel() {
  const [report, setReport] = useState<Report | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<Report>("/accounts/reconcile")
      .then((result) => {
        if (!cancelled) setReport(result);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!report) return null;
  const checkable = report.accounts.filter((a) => a.status !== "not_checkable");
  if (!checkable.length) return null;

  // The same disambiguation the account list uses. Without it this panel names
  // two cards "Discover it Card" and asks you to go and check one of them.
  const named = report.accounts.map((a) => ({ ...a, id: a.account_id }));
  const label = (check: Check) =>
    accountLabel({ ...check, id: check.account_id }, named);

  return (
    <article className="panel reconcile-panel">
      <div className="settings-card-heading reconcile-heading">
        <div>
          <h2>
            <Scale size={16} /> Does it add up?
          </h2>
          <p className="subtle">
            The transactions you have recorded against the balance each account
            claims. Raven never adjusts anything here — a check that quietly
            corrects a balance to match its own arithmetic can never find
            anything again.
          </p>
        </div>
        <span className={report.drifted ? "negative" : "positive"}>
          {report.drifted
            ? `${report.drifted} to look at`
            : `${report.balanced} balanced`}
        </span>
      </div>

      <ul className="reconcile-list">
        {checkable.map((account) => (
          <li className={account.status} key={account.account_id}>
            <span className="reconcile-icon">
              {account.status === "drifted" ? (
                <CircleAlert size={16} />
              ) : account.status === "empty" ? (
                <CircleHelp size={16} />
              ) : (
                <CircleCheck size={16} />
              )}
            </span>
            <div>
              <strong>{label(account)}</strong>
              <p>{account.reason}</p>
              {account.status === "drifted" && (
                <small>
                  {account.transactions} transactions totalling{" "}
                  {currency(Number(account.transaction_total))}, against a
                  balance of {currency(Number(account.stated_balance))}.
                </small>
              )}
            </div>
            {account.difference && (
              <span className="reconcile-gap negative">
                {currency(Math.abs(Number(account.difference)))}
              </span>
            )}
          </li>
        ))}
      </ul>

      {report.not_checkable > 0 && (
        <p className="subtle reconcile-note">
          {report.not_checkable} connected account
          {report.not_checkable === 1 ? " is" : "s are"} not checked: a bank
          feed starts wherever its history began, so those transactions are not
          expected to add up to the balance.
        </p>
      )}
    </article>
  );
}
