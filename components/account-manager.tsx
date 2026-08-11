"use client";

import {
  ArrowDownRight,
  ArrowUpRight,
  Building2,
  ChevronRight,
  CircleDollarSign,
  Landmark,
  Link2,
  LoaderCircle,
  FileUp,
  Pencil,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  WalletCards,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { PlaidLinkButton } from "@/components/plaid-link-button";
import {
  Account,
  AccountKind,
  AccountOwner,
  AccountPayload,
  AccountType,
  accountBalance,
  accountLabel,
  accountTypeLabel,
  accountTypeOptions,
  isBorrowing,
  kindForType,
} from "@/lib/accounts";
import { CsvImport } from "@/components/csv-import";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";

function accountIcon(type: AccountType) {
  if (type === "credit") return WalletCards;
  if (type === "cash") return CircleDollarSign;
  if (type === "checking" || type === "savings") return Landmark;
  return Building2;
}

function lastUpdated(account: Account) {
  if (account.is_manual) return "Updated manually";
  if (!account.last_synced_at) return "Waiting for first sync";
  return `Synced ${new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(account.last_synced_at))}`;
}

function syncHealth(account: Account, nowMs: number) {
  if (account.is_manual) return { label: "Manual", tone: "manual" };
  if (!account.last_synced_at) return { label: "First sync pending", tone: "attention" };
  const age = nowMs - new Date(account.last_synced_at).getTime();
  if (age > 72 * 60 * 60 * 1000) return { label: "Sync overdue", tone: "attention" };
  if (age > 24 * 60 * 60 * 1000) return { label: "Synced recently", tone: "recent" };
  return { label: "Up to date", tone: "healthy" };
}

function Dialog({
  children,
  label,
  onClose,
  size = "normal",
}: {
  children: React.ReactNode;
  label: string;
  onClose: () => void;
  size?: "normal" | "wide";
}) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    document.body.classList.add("dialog-open");
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.classList.remove("dialog-open");
    };
  }, [onClose]);

  return (
    <div className="dialog-layer">
      <button
        aria-label="Close dialog"
        className="dialog-backdrop"
        onClick={onClose}
      />
      <section
        aria-label={label}
        aria-modal="true"
        className={`account-dialog ${size === "wide" ? "wide" : ""}`}
        role="dialog"
      >
        {children}
      </section>
    </div>
  );
}

function AddAccountDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (message: string) => void;
}) {
  const [name, setName] = useState("");
  const [institution, setInstitution] = useState("");
  const [type, setType] = useState<AccountType>("checking");
  const [kind, setKind] = useState<AccountKind>("asset");
  const [balance, setBalance] = useState("");
  const [creditLimit, setCreditLimit] = useState("");
  const [interestRate, setInterestRate] = useState("");
  const [minimumPayment, setMinimumPayment] = useState("");
  const [onBudget, setOnBudget] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function createManualAccount(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const payload: AccountPayload = {
      name: name.trim(),
      institution_name: institution.trim() || null,
      type,
      kind,
      current_balance: Number(balance || 0),
      is_on_budget: onBudget,
      credit_limit:
        type === "credit" && creditLimit ? Number(creditLimit) : null,
      // Only meaningful on a debt; sent as null otherwise so switching an
      // account's type does not leave a stale rate behind it.
      interest_rate:
        isBorrowing(type) && interestRate ? Number(interestRate) : null,
      minimum_payment:
        isBorrowing(type) && minimumPayment ? Number(minimumPayment) : null,
    };
    try {
      await apiFetch<Account>("/accounts", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      onCreated(`${payload.name} was added.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not add account");
    } finally {
      setSaving(false);
    }
  }

  function changeType(nextType: AccountType) {
    setType(nextType);
    setKind((current) => kindForType(nextType, current));
  }

  return (
    <Dialog label="Add an account" onClose={onClose} size="wide">
      <div className="dialog-header">
        <div>
          <p className="eyebrow">Add account</p>
          <h2>Bring your whole financial life together.</h2>
          <p>
            Connect securely for automatic updates, or add any account by hand.
          </p>
        </div>
        <button aria-label="Close" className="dialog-close" onClick={onClose}>
          <X size={18} />
        </button>
      </div>

      <div className="connect-callout">
        <span className="connect-icon">
          <Link2 size={21} />
        </span>
        <div>
          <strong>Connect a financial institution</strong>
          <p>
            Plaid imports supported balances and transactions and keeps them in
            sync.
          </p>
          <span className="security-note">
            <ShieldCheck size={13} /> Raven Ledger never sees your bank password.
          </span>
        </div>
        <PlaidLinkButton
          onConnected={() =>
            onCreated("Institution connected. Accounts will appear after sync.")
          }
        />
      </div>

      <div className="dialog-divider">
        <span>or add it manually</span>
      </div>

      <form className="account-form" onSubmit={createManualAccount}>
        <label className="field full">
          <span>Account name</span>
          <input
            autoFocus
            maxLength={160}
            onChange={(event) => setName(event.target.value)}
            placeholder="Everyday checking"
            required
            value={name}
          />
        </label>
        <label className="field">
          <span>Account type</span>
          <select
            onChange={(event) => changeType(event.target.value as AccountType)}
            value={type}
          >
            {accountTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Institution (optional)</span>
          <input
            maxLength={255}
            onChange={(event) => setInstitution(event.target.value)}
            placeholder="Bank or provider"
            value={institution}
          />
        </label>
        {type === "other" && (
          <div className="field full">
            <span>How should this count?</span>
            <div className="segmented-control">
              <button
                className={kind === "asset" ? "active" : ""}
                onClick={() => setKind("asset")}
                type="button"
              >
                Money I own
              </button>
              <button
                className={kind === "liability" ? "active" : ""}
                onClick={() => setKind("liability")}
                type="button"
              >
                Money I owe
              </button>
            </div>
          </div>
        )}
        <label className="field">
          <span>{kind === "liability" ? "Amount owed" : "Current balance"}</span>
          <div className="money-input">
            <span>$</span>
            <input
              inputMode="decimal"
              min="0"
              onChange={(event) => setBalance(event.target.value)}
              placeholder="0.00"
              required
              step="0.01"
              type="number"
              value={balance}
            />
          </div>
        </label>
        {type === "credit" ? (
          <label className="field">
            <span>Credit limit (optional)</span>
            <div className="money-input">
              <span>$</span>
              <input
                inputMode="decimal"
                min="0"
                onChange={(event) => setCreditLimit(event.target.value)}
                placeholder="0.00"
                step="0.01"
                type="number"
                value={creditLimit}
              />
            </div>
          </label>
        ) : isBorrowing(type) ? (
          <>
            <label className="field">
              <span>Interest rate (optional)</span>
              <div className="money-input">
                <span>%</span>
                <input
                  inputMode="decimal"
                  max="100"
                  min="0"
                  onChange={(event) => setInterestRate(event.target.value)}
                  placeholder="6.25"
                  step="0.001"
                  type="number"
                  value={interestRate}
                />
              </div>
              <small className="field-hint">
                Leave empty and Raven will not model interest. With a rate it
                adds a month&apos;s interest each month, so the balance keeps
                roughly in step instead of drifting optimistic.
              </small>
            </label>
            <label className="field">
              <span>Usual payment (optional)</span>
              <div className="money-input">
                <span>$</span>
                <input
                  inputMode="decimal"
                  min="0"
                  onChange={(event) => setMinimumPayment(event.target.value)}
                  placeholder="350.00"
                  step="0.01"
                  type="number"
                  value={minimumPayment}
                />
              </div>
              <small className="field-hint">
                Used to work out when this is paid off — and to say so plainly
                if the payment does not cover the interest.
              </small>
            </label>
          </>
        ) : (
          <div />
        )}
        <label className="toggle-row full">
          <input
            checked={onBudget}
            onChange={(event) => setOnBudget(event.target.checked)}
            type="checkbox"
          />
          <span>
            <strong>Include in my budget</strong>
            <small>Use this account in spending and cash-flow calculations.</small>
          </span>
        </label>
        {error && <p className="form-error full">{error}</p>}
        <div className="dialog-actions full">
          <button className="ghost-button" onClick={onClose} type="button">
            Cancel
          </button>
          <button className="primary-button" disabled={saving} type="submit">
            {saving ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />}
            Add manual account
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function AccountDetailDialog({
  account,
  onClose,
  onDeleted,
  onUpdated,
}: {
  account: Account;
  onClose: () => void;
  onDeleted: (message: string) => void;
  onUpdated: (account: Account, message: string) => void;
}) {
  const [name, setName] = useState(account.name);
  const [institution, setInstitution] = useState(account.institution_name ?? "");
  const [type, setType] = useState<AccountType>(account.type);
  const [kind, setKind] = useState<AccountKind>(account.kind);
  const [balance, setBalance] = useState(
    String(Math.abs(accountBalance(account))),
  );
  const [creditLimit, setCreditLimit] = useState(account.credit_limit ?? "");
  const [importing, setImporting] = useState(false);
  const [interestRate, setInterestRate] = useState(account.interest_rate ?? "");
  const [minimumPayment, setMinimumPayment] = useState(
    account.minimum_payment ?? "",
  );
  const [statementDay, setStatementDay] = useState(
    account.statement_day ?? "",
  );
  const [onBudget, setOnBudget] = useState(account.is_on_budget);
  const [owner, setOwner] = useState(account.owner_user_id ?? "");
  const [members, setMembers] = useState<AccountOwner[]>([]);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState("");

  // A household of two, fetched when the dialog opens. Failure is silent and
  // leaves the picker holding only "Shared": not being able to reassign an
  // account is a smaller problem than a dialog that refuses to open.
  useEffect(() => {
    let live = true;
    apiFetch<AccountOwner[]>("/households/members")
      .then((rows) => {
        if (live) setMembers(rows);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  function changeType(nextType: AccountType) {
    setType(nextType);
    setKind((current) => kindForType(nextType, current));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const payload = {
      name: name.trim(),
      institution_name: institution.trim() || null,
      type,
      kind,
      is_on_budget: onBudget,
      owner_user_id: owner || null,
      credit_limit:
        type === "credit" && creditLimit ? Number(creditLimit) : null,
      // Only meaningful on a debt; sent as null otherwise so switching an
      // account's type does not leave a stale rate behind it.
      interest_rate:
        isBorrowing(type) && interestRate ? Number(interestRate) : null,
      statement_day:
        String(statementDay).trim() === "" ? null : Number(statementDay),
      minimum_payment:
        isBorrowing(type) && minimumPayment ? Number(minimumPayment) : null,
      ...(account.is_manual ? { current_balance: Number(balance || 0) } : {}),
    };
    try {
      const updated = await apiFetch<Account>(`/accounts/${account.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      onUpdated(updated, `${updated.name} was updated.`);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not update account",
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setSaving(true);
    setError("");
    try {
      await apiFetch<void>(`/accounts/${account.id}`, { method: "DELETE" });
      onDeleted(`${account.name} was removed.`);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not remove account",
      );
      setSaving(false);
    }
  }

  return (
    <Dialog label={`Edit ${account.name}`} onClose={onClose}>
      <div className="dialog-header compact">
        <div className={`detail-account-icon ${account.kind}`}>
          {account.kind === "asset" ? (
            <ArrowUpRight size={21} />
          ) : (
            <ArrowDownRight size={21} />
          )}
        </div>
        <div>
          <p className="eyebrow">
            {account.is_manual ? "Manual account" : "Plaid-connected"}
          </p>
          <h2>{account.name}</h2>
          <p>{lastUpdated(account)}</p>
        </div>
        <button aria-label="Close" className="dialog-close" onClick={onClose}>
          <X size={18} />
        </button>
      </div>

      <div className="account-balance-hero">
        <span>Current balance</span>
        <strong className={account.kind === "liability" ? "negative" : ""}>
          {currency(accountBalance(account))}
        </strong>
        {account.mask && <small>Account ending in {account.mask}</small>}
      </div>

      <form className="account-form" onSubmit={save}>
        <label className="field full">
          <span>Display name</span>
          <input
            maxLength={160}
            onChange={(event) => setName(event.target.value)}
            required
            value={name}
          />
        </label>
        <label className="field">
          <span>Account type</span>
          <select
            onChange={(event) => changeType(event.target.value as AccountType)}
            value={type}
          >
            {accountTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Institution</span>
          <input
            maxLength={255}
            onChange={(event) => setInstitution(event.target.value)}
            placeholder="Bank or provider"
            value={institution}
          />
        </label>
        {/* Set automatically to whoever linked the bank, because two people
            here hold the same two cards. Editable because that guess is only
            right for personal accounts — a joint account belongs to both, and
            "Shared" has to stay reachable. */}
        <label className="field">
          <span>Whose account</span>
          <select
            onChange={(event) => setOwner(event.target.value)}
            value={owner}
          >
            <option value="">Shared</option>
            {members.map((member) => (
              <option key={member.id} value={member.id}>
                {member.display_name}
              </option>
            ))}
          </select>
        </label>
        {type === "other" && (
          <div className="field full">
            <span>How should this count?</span>
            <div className="segmented-control">
              <button
                className={kind === "asset" ? "active" : ""}
                onClick={() => setKind("asset")}
                type="button"
              >
                Money I own
              </button>
              <button
                className={kind === "liability" ? "active" : ""}
                onClick={() => setKind("liability")}
                type="button"
              >
                Money I owe
              </button>
            </div>
          </div>
        )}
        <label className="field">
          <span>{kind === "liability" ? "Amount owed" : "Current balance"}</span>
          <div className={`money-input ${!account.is_manual ? "disabled" : ""}`}>
            <span>$</span>
            <input
              disabled={!account.is_manual}
              inputMode="decimal"
              min="0"
              onChange={(event) => setBalance(event.target.value)}
              step="0.01"
              type="number"
              value={balance}
            />
          </div>
          {!account.is_manual && (
            <small className="field-help">Balance is managed by Plaid.</small>
          )}
        </label>
        {type === "credit" ? (
          <>
            <label className="field">
              <span>Credit limit</span>
              <div className="money-input">
                <span>$</span>
                <input
                  inputMode="decimal"
                  min="0"
                  onChange={(event) => setCreditLimit(event.target.value)}
                  placeholder="0.00"
                  step="0.01"
                  type="number"
                  value={creditLimit}
                />
              </div>
            </label>
            <label className="field">
              <span>Statement closes on the</span>
              <input
                inputMode="numeric"
                max="31"
                min="1"
                onChange={(event) => setStatementDay(event.target.value)}
                placeholder="8"
                step="1"
                type="number"
                value={statementDay}
              />
              <small className="field-help">
                Day of the month. A card closing on the 8th bills July&apos;s
                spending in August, and that is when the money leaves — so the
                Budget page can tell you what is still to pay. Leave empty and
                the card is left out of that rather than guessed at.
              </small>
            </label>
          </>
        ) : isBorrowing(type) ? (
          <>
            <label className="field">
              <span>Interest rate</span>
              <div className="money-input">
                <span>%</span>
                <input
                  inputMode="decimal"
                  max="100"
                  min="0"
                  onChange={(event) => setInterestRate(event.target.value)}
                  placeholder="6.25"
                  step="0.001"
                  type="number"
                  value={interestRate}
                />
              </div>
              <small className="field-help">
                Empty means Raven does not model interest. With a rate it adds
                a month&apos;s worth each month, so the balance keeps roughly
                in step rather than drifting optimistic.
              </small>
            </label>
            <label className="field">
              <span>Usual payment</span>
              <div className="money-input">
                <span>$</span>
                <input
                  inputMode="decimal"
                  min="0"
                  onChange={(event) => setMinimumPayment(event.target.value)}
                  placeholder="350.00"
                  step="0.01"
                  type="number"
                  value={minimumPayment}
                />
              </div>
            </label>
          </>
        ) : (
          <div />
        )}
        <label className="toggle-row full">
          <input
            checked={onBudget}
            onChange={(event) => setOnBudget(event.target.checked)}
            type="checkbox"
          />
          <span>
            <strong>Include in my budget</strong>
            <small>Count activity from this account in your plan.</small>
          </span>
        </label>
        {error && <p className="form-error full">{error}</p>}
        <div className="account-danger-zone full">
          {confirmDelete ? (
            <div>
              <span>
                <strong>Remove this account?</strong>
                <small>
                  Its historical transactions stay in Raven Ledger, but the
                  account will no longer appear in totals.
                </small>
              </span>
              <button
                className="danger-button"
                disabled={saving}
                onClick={remove}
                type="button"
              >
                <Trash2 size={14} /> Yes, remove
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
              <Trash2 size={14} /> Remove account
            </button>
          )}
        </div>
        {account.is_manual && (
          /* Only for accounts Raven holds the whole history of. A connected
             account already receives its transactions, and importing a
             statement over the top would duplicate every one of them. */
          <button
            className="ghost-button import-launch"
            onClick={() => setImporting(true)}
            type="button"
          >
            <FileUp size={14} /> Import a CSV statement
          </button>
        )}
        <div className="dialog-actions full">
          <button className="ghost-button" onClick={onClose} type="button">
            Cancel
          </button>
          <button className="primary-button" disabled={saving} type="submit">
            {saving ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <Pencil size={14} />
            )}
            Save changes
          </button>
        </div>
      </form>
      {importing && (
        <CsvImport
          accountId={account.id}
          accountName={account.name}
          onClose={() => setImporting(false)}
          onImported={(count) => {
            setImporting(false);
            onUpdated(
              account,
              `Imported ${count} transaction${count === 1 ? "" : "s"} into ${account.name}.`,
            );
          }}
        />
      )}
    </Dialog>
  );
}

function AccountSection({
  accounts,
  allAccounts,
  kind,
  onSelect,
  filtered,
  nowMs,
}: {
  accounts: Account[];
  allAccounts: Account[];
  kind: AccountKind;
  onSelect: (account: Account) => void;
  filtered: boolean;
  nowMs: number;
}) {
  const total = accounts.reduce((sum, account) => {
    const balance = accountBalance(account);
    return sum + (kind === "liability" ? Math.abs(balance) : balance);
  }, 0);

  return (
    <article className="panel account-section">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">
            {kind === "asset" ? "What you own" : "What you owe"}
          </p>
          <h2>{kind === "asset" ? "Assets" : "Liabilities"}</h2>
        </div>
        <span className={`account-section-total ${kind}`}>{currency(total)}</span>
      </div>
      {accounts.length ? (
        <div className="account-group">
          {accounts.map((account) => {
            const Icon = accountIcon(account.type);
            const creditLimit = Number(account.credit_limit ?? 0);
            const utilization =
              account.type === "credit" && creditLimit > 0
                ? Math.min(
                    100,
                    (Math.abs(accountBalance(account)) / creditLimit) * 100,
                  )
                : null;
            const health = syncHealth(account, nowMs);
            return (
              <button
                className={`account-card ${kind}`}
                key={account.id}
                onClick={() => onSelect(account)}
                type="button"
              >
                <span className="account-icon">
                  <Icon size={18} />
                </span>
                <span className="account-copy">
                  <strong>{accountLabel(account, allAccounts)}</strong>
                  <small>
                    {account.institution_name || "Manual account"} ·{" "}
                    {accountTypeLabel(account.type)}
                    {account.mask ? ` • ${account.mask}` : ""}
                    {account.type === "credit" && account.statement_day
                      ? ` · closes ${account.statement_day}`
                      : ""}
                  </small>
                  <em className={`account-health ${health.tone}`}>{health.label}</em>
                </span>
                <span className="account-balance">
                  <strong className={kind === "liability" ? "negative" : ""}>
                    {currency(accountBalance(account))}
                  </strong>
                  <small>
                    {utilization !== null
                      ? `${Math.round(utilization)}% utilized`
                      : account.is_on_budget
                        ? "In budget"
                        : "Off budget"}
                  </small>
                  {utilization !== null && (
                    <i className={`credit-meter ${utilization >= 70 ? "high" : utilization >= 30 ? "medium" : "low"}`}>
                      <span style={{ width: `${utilization}%` }} />
                    </i>
                  )}
                </span>
                <ChevronRight className="account-chevron" size={16} />
              </button>
            );
          })}
        </div>
      ) : (
        <div className="account-empty">
          <span className={kind}>
            {kind === "asset" ? (
              <ArrowUpRight size={18} />
            ) : (
              <ArrowDownRight size={18} />
            )}
          </span>
          <strong>No {kind === "asset" ? "assets" : "liabilities"} yet</strong>
          <small>
            {filtered
              ? "No accounts in this section match the current filters."
              : "Add an account to include it in your financial picture."}
          </small>
        </div>
      )}
    </article>
  );
}

export function AccountManager() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [selected, setSelected] = useState<Account | null>(null);
  const [query, setQuery] = useState("");
  const [connectionFilter, setConnectionFilter] = useState<"all" | "connected" | "manual">("all");
  const [sort, setSort] = useState<"name" | "balance-high" | "balance-low">("name");
  const [nowMs] = useState(() => Date.now());

  const refresh = useCallback(async () => {
    try {
      const result = await apiFetch<Account[]>("/accounts");
      setAccounts(result);
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not load accounts",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    apiFetch<Account[]>("/accounts")
      .then((result) => {
        if (!cancelled) {
          setAccounts(result);
          setError("");
          const requestedAccount = new URLSearchParams(
            window.location.search,
          ).get("account");
          const requestedAction = new URLSearchParams(
            window.location.search,
          ).get("action");
          if (requestedAccount) {
            setSelected(
              result.find((account) => account.id === requestedAccount) ?? null,
            );
          }
          if (requestedAction === "add") setAddOpen(true);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error ? reason.message : "Could not load accounts",
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
    const timer = window.setTimeout(() => setToast(""), 4000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const visibleAccounts = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return accounts
      .filter((item) => {
        const matchesQuery = !normalized || `${item.name} ${item.institution_name ?? ""} ${accountTypeLabel(item.type)}`.toLowerCase().includes(normalized);
        const matchesConnection =
          connectionFilter === "all" ||
          (connectionFilter === "manual" ? item.is_manual : !item.is_manual);
        return matchesQuery && matchesConnection;
      })
      .sort((a, b) => {
        if (sort === "balance-high") return Math.abs(accountBalance(b)) - Math.abs(accountBalance(a));
        if (sort === "balance-low") return Math.abs(accountBalance(a)) - Math.abs(accountBalance(b));
        return a.name.localeCompare(b.name);
      });
  }, [accounts, connectionFilter, query, sort]);
  const assets = useMemo(
    () => visibleAccounts.filter((account) => account.kind === "asset"),
    [visibleAccounts],
  );
  const liabilities = useMemo(
    () => visibleAccounts.filter((account) => account.kind === "liability"),
    [visibleAccounts],
  );
  const allAssets = accounts.filter((account) => account.kind === "asset");
  const allLiabilities = accounts.filter((account) => account.kind === "liability");
  const assetTotal = allAssets.reduce(
    (sum, account) => sum + accountBalance(account),
    0,
  );
  const liabilityTotal = allLiabilities.reduce(
    (sum, account) => sum + Math.abs(accountBalance(account)),
    0,
  );

  function accountCreated(message: string) {
    setAddOpen(false);
    setToast(message);
    void refresh();
    window.setTimeout(() => void refresh(), 2500);
  }

  function accountUpdated(account: Account, message: string) {
    setAccounts((current) =>
      current.map((item) => (item.id === account.id ? account : item)),
    );
    setSelected(null);
    setToast(message);
  }

  function accountDeleted(message: string) {
    setSelected(null);
    setToast(message);
    void refresh();
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Accounts</p>
          <h1>Your complete financial picture.</h1>
          <p className="subtle">
            Add manual accounts or connect Plaid for automatic balances and
            transactions.
          </p>
        </div>
        <button className="primary-button" onClick={() => setAddOpen(true)}>
          <Plus size={16} /> Add account
        </button>
      </div>

      <section className="account-overview">
        <div>
          <span>Net worth</span>
          <strong>{currency(assetTotal - liabilityTotal)}</strong>
        </div>
        <div>
          <span>Total assets</span>
          <strong className="positive">{currency(assetTotal)}</strong>
        </div>
        <div>
          <span>Total debt</span>
          <strong className={liabilityTotal ? "negative" : ""}>
            {currency(liabilityTotal)}
          </strong>
        </div>
        <div>
          <span>Accounts</span>
          <strong>{accounts.length}</strong>
        </div>
      </section>

      <div className="toolbar account-toolbar">
        <label className="search-field">
          <Search size={16} />
          <input aria-label="Search accounts" onChange={(event) => setQuery(event.target.value)} placeholder="Search accounts or institutions" value={query} />
        </label>
        <div className="segmented-control account-source-filter" aria-label="Account source">
          {(["all", "connected", "manual"] as const).map((value) => (
            <button aria-pressed={connectionFilter === value} className={connectionFilter === value ? "active" : ""} key={value} onClick={() => setConnectionFilter(value)} type="button">
              {value === "all" ? "All" : value === "connected" ? "Connected" : "Manual"}
            </button>
          ))}
        </div>
        <select aria-label="Sort accounts" className="filter-select" onChange={(event) => setSort(event.target.value as typeof sort)} value={sort}>
          <option value="name">Name</option>
          <option value="balance-high">Largest balance</option>
          <option value="balance-low">Smallest balance</option>
        </select>
        <span className="toolbar-count">{visibleAccounts.length} of {accounts.length}</span>
      </div>

      {error && (
        <div className="page-error">
          <span>{error}</span>
          <button className="ghost-button" onClick={() => void refresh()}>
            Try again
          </button>
        </div>
      )}

      {loading ? (
        <div className="account-loading">
          <LoaderCircle className="spin" size={22} />
          Loading your accounts…
        </div>
      ) : (
        <section className="accounts-grid">
          <AccountSection
            allAccounts={visibleAccounts}
            accounts={assets}
            filtered={Boolean(query || connectionFilter !== "all")}
            kind="asset"
            nowMs={nowMs}
            onSelect={setSelected}
          />
          <AccountSection
            allAccounts={visibleAccounts}
            accounts={liabilities}
            filtered={Boolean(query || connectionFilter !== "all")}
            kind="liability"
            nowMs={nowMs}
            onSelect={setSelected}
          />
        </section>
      )}

      <section className="account-sync-note">
        <div className="sync-illustration">
          <ShieldCheck size={19} />
        </div>
        <div>
          <strong>Connected account data stays encrypted.</strong>
          <p>
            Plaid credentials never pass through Raven Ledger. Manual balances
            remain fully editable.
          </p>
        </div>
        <button className="ghost-button" onClick={() => setAddOpen(true)}>
          <Link2 size={15} /> Connect institution
        </button>
      </section>

      {addOpen && (
        <AddAccountDialog
          onClose={() => setAddOpen(false)}
          onCreated={accountCreated}
        />
      )}
      {selected && (
        <AccountDetailDialog
          account={selected}
          onClose={() => setSelected(null)}
          onDeleted={accountDeleted}
          onUpdated={accountUpdated}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}
