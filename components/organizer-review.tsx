"use client";

import {
  ArrowLeftRight,
  Copy as CopyIcon,
  Check,
  LoaderCircle,
  PiggyBank,
  Receipt,
  Sparkles,
  Tag,
  Undo2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Category } from "@/lib/finance";
import { currency } from "@/lib/format";
import { prettyMerchant } from "@/lib/merchant";
import { SelectField } from "@/components/select-field";
import { UndoBar } from "@/components/undo-bar";

type Kind =
  | "duplicate"
  | "transfer"
  | "exclusion"
  | "category"
  | "rule"
  | "budget";

type Proposal = {
  id: string;
  kind: Kind;
  status: string;
  payload: Record<string, string | number | string[]>;
  rationale: string;
  confidence: string | number;
  created_at: string;
};

type RunResult = Record<Kind, number>;

// Ordered most certain first, which is also least-thought-first: the queue
// should open on the things that barely need reading.
const GROUPS: { kind: Kind; title: string; blurb: string; icon: typeof Tag }[] = [
  {
    kind: "duplicate",
    title: "The same charge, twice",
    blurb:
      "Providers sometimes post a charge again when it settles. The first is kept; only the repeat is excluded.",
    icon: CopyIcon,
  },
  {
    kind: "transfer",
    title: "Money moving between your accounts",
    blurb:
      "Counted twice today — once leaving, once arriving. Marking these stops them showing as income and spending.",
    icon: ArrowLeftRight,
  },
  {
    kind: "exclusion",
    title: "Refunds that cancel a charge",
    blurb:
      "The purchase was undone. Excluding both leaves the month showing what it actually cost.",
    icon: Undo2,
  },
  {
    kind: "category",
    title: "Categories",
    blurb: "Where these look like they belong, based on how you have filed them before.",
    icon: Tag,
  },
  {
    kind: "rule",
    title: "Rules worth writing",
    blurb:
      "Merchants settled enough to stop being asked about. A rule outranks every later guess.",
    icon: Receipt,
  },
  {
    kind: "budget",
    title: "Budget amounts",
    blurb:
      "From what you have actually spent, not what a rule of thumb says you should. Read these before accepting.",
    icon: PiggyBank,
  },
];

function describe(item: Proposal): string {
  const p = item.payload;
  switch (item.kind) {
    case "transfer":
      return `${prettyMerchant(String(p.from_label ?? "Outflow"))} → ${prettyMerchant(String(p.to_label ?? "inflow"))} · ${currency(Number(p.amount))}`;
    case "duplicate":
    case "exclusion":
      return `${prettyMerchant(String(p.merchant ?? "Refund"))} · ${currency(Number(p.amount))}`;
    case "category":
      return `${prettyMerchant(String(p.merchant ?? "Transaction"))} · ${currency(Number(p.amount))}`;
    case "rule":
      return `${prettyMerchant(String(p.sample_label ?? p.merchant_pattern))} · ${p.affects} transactions`;
    case "budget":
      return String(p.category_name ?? "");
    default:
      return "";
  }
}

export function OrganizerReview() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [lastRun, setLastRun] = useState<RunResult | null>(null);

  const load = useCallback(async () => {
    const [rows, cats] = await Promise.all([
      apiFetch<Proposal[]>("/organizer/proposals"),
      apiFetch<Category[]>("/categories"),
    ]);
    setProposals(rows);
    setCategories(cats);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiFetch<Proposal[]>("/organizer/proposals"),
      apiFetch<Category[]>("/categories"),
    ])
      .then(([rows, cats]) => {
        if (cancelled) return;
        setProposals(rows);
        setCategories(cats);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  async function run() {
    setRunning(true);
    setError("");
    setNotice("");
    try {
      const result = await apiFetch<RunResult>("/organizer/run", {
        method: "POST",
      });
      setLastRun(result);
      setSelected(new Set());
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That run did not finish");
    } finally {
      setRunning(false);
    }
  }

  async function decide(ids: string[], approve: boolean) {
    if (!ids.length) return;
    setBusy(true);
    setError("");
    try {
      const result = await apiFetch<{ applied?: number; skipped?: unknown[] }>(
        `/organizer/proposals/${approve ? "approve" : "reject"}`,
        { method: "POST", body: JSON.stringify({ proposal_ids: ids }) },
      );
      const skipped = result.skipped?.length ?? 0;
      setNotice(
        approve
          ? `Applied ${result.applied ?? 0}.${skipped ? ` ${skipped} had moved on and were left alone.` : ""}`
          : `Dismissed ${ids.length}.`,
      );
      setSelected(new Set());
      // Tells the undo bar something happened, rather than having it poll.
      window.dispatchEvent(new Event("raven:acted"));
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That did not work");
    } finally {
      setBusy(false);
    }
  }

  async function editCategory(item: Proposal, categoryId: string) {
    const category = categories.find((c) => c.id === categoryId);
    await apiFetch(`/organizer/proposals/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        payload: { category_id: categoryId, category_name: category?.name ?? "" },
      }),
    });
    await load();
  }

  async function editAmount(item: Proposal, amount: string) {
    await apiFetch(`/organizer/proposals/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ payload: { planned_amount: amount } }),
    });
    await load();
  }

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const categoryOptions = categories
    .filter((c) => !c.group_is_income)
    .map((c) => ({ value: c.id, label: c.name, hint: c.group_name }));

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Organizer</p>
          <h1>Let Raven tidy up, then say yes.</h1>
          <p className="subtle">
            It reads the whole ledger and writes down what it would change.
            Nothing happens until you agree to it, and you can edit anything
            first.
          </p>
        </div>
        <button
          className="primary-button"
          disabled={running}
          onClick={() => void run()}
          type="button"
        >
          {running ? (
            <LoaderCircle className="spin" size={15} />
          ) : (
            <Sparkles size={15} />
          )}
          {running ? "Looking…" : "Look over my ledger"}
        </button>
      </div>

      <UndoBar />

      {error && <div className="page-error">{error}</div>}
      {notice && <div className="settings-notice">{notice}</div>}

      {lastRun && !proposals.length && (
        <article className="panel organizer-empty">
          <Check className="positive" size={22} />
          <h2>Nothing to change.</h2>
          <p className="subtle">
            Raven read everything and did not find anything worth moving. That
            is the good outcome.
          </p>
        </article>
      )}

      {!lastRun && !proposals.length && (
        <article className="panel organizer-empty">
          <Sparkles className="positive" size={22} />
          <h2>Nothing waiting.</h2>
          <p className="subtle">
            Press <strong>Look over my ledger</strong> and Raven will go through
            your transactions, spot money moving between your own accounts,
            suggest categories, and propose rules and budget amounts — all as
            suggestions you approve one by one or all at once.
          </p>
        </article>
      )}

      {proposals.length > 0 && (
        <div className="organizer-bulk">
          <span>
            <strong>{selected.size}</strong> of {proposals.length} selected
          </span>
          <div>
            <button
              className="ghost-button"
              onClick={() =>
                setSelected(
                  selected.size === proposals.length
                    ? new Set()
                    : new Set(proposals.map((p) => p.id)),
                )
              }
              type="button"
            >
              {selected.size === proposals.length ? "Select none" : "Select all"}
            </button>
            <button
              className="ghost-button danger"
              disabled={busy || !selected.size}
              onClick={() => void decide([...selected], false)}
              type="button"
            >
              <X size={13} /> Dismiss
            </button>
            <button
              className="primary-button"
              disabled={busy || !selected.size}
              onClick={() => void decide([...selected], true)}
              type="button"
            >
              <Check size={14} /> Apply {selected.size || ""}
            </button>
          </div>
        </div>
      )}

      {GROUPS.map((group) => {
        const rows = proposals.filter((item) => item.kind === group.kind);
        if (!rows.length) return null;
        const Icon = group.icon;
        return (
          <article className="panel organizer-group" key={group.kind}>
            <div className="organizer-group-heading">
              <span className="organizer-group-icon">
                <Icon size={17} />
              </span>
              <div>
                <h2>{group.title}</h2>
                <p className="subtle">{group.blurb}</p>
              </div>
              <button
                className="ghost-button"
                onClick={() =>
                  setSelected((current) => {
                    const next = new Set(current);
                    rows.forEach((r) => next.add(r.id));
                    return next;
                  })
                }
                type="button"
              >
                Select {rows.length}
              </button>
            </div>

            <ul className="organizer-list">
              {rows.map((item) => (
                <li className={selected.has(item.id) ? "picked" : ""} key={item.id}>
                  <label className="organizer-pick">
                    <input
                      aria-label={`Select ${describe(item)}`}
                      checked={selected.has(item.id)}
                      onChange={() => toggle(item.id)}
                      type="checkbox"
                    />
                  </label>
                  <div className="organizer-body">
                    <strong>{describe(item)}</strong>
                    <p>{item.rationale}</p>

                    {item.kind === "category" && (
                      <div className="organizer-edit">
                        <span>File as</span>
                        <SelectField
                          ariaLabel="Category for this transaction"
                          onChange={(value) => void editCategory(item, value)}
                          options={categoryOptions}
                          value={String(item.payload.category_id ?? "")}
                        />
                      </div>
                    )}

                    {item.kind === "budget" && (
                      <div className="organizer-edit">
                        <span>Plan</span>
                        <div className="money-input compact">
                          <span>$</span>
                          <input
                            aria-label={`Planned amount for ${item.payload.category_name}`}
                            defaultValue={String(item.payload.planned_amount ?? "")}
                            min="0"
                            onBlur={(event) =>
                              void editAmount(item, event.target.value)
                            }
                            step="1"
                            type="number"
                          />
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="organizer-row-actions">
                    <button
                      aria-label="Dismiss this one"
                      className="ghost-button"
                      disabled={busy}
                      onClick={() => void decide([item.id], false)}
                      type="button"
                    >
                      <X size={13} />
                    </button>
                    <button
                      aria-label="Apply this one"
                      className="ghost-button positive"
                      disabled={busy}
                      onClick={() => void decide([item.id], true)}
                      type="button"
                    >
                      <Check size={13} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </article>
        );
      })}
    </>
  );
}
