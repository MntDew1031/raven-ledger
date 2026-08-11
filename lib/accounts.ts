export type AccountKind = "asset" | "liability";

export type AccountType =
  | "checking"
  | "savings"
  | "credit"
  | "investment"
  | "retirement"
  | "brokerage"
  | "mortgage"
  | "loan"
  | "debt"
  | "cash"
  | "other";

export type Account = {
  id: string;
  connection_id: string | null;
  name: string;
  official_name: string | null;
  institution_name: string | null;
  mask: string | null;
  type: AccountType;
  subtype: string | null;
  kind: AccountKind;
  current_balance: string;
  available_balance: string | null;
  credit_limit: string | null;
  currency: string;
  is_on_budget: boolean;
  is_manual: boolean;
  // Whose account this is. Null means shared, which is the right default for a
  // joint checking account. Set automatically to whoever linked the bank.
  owner_user_id: string | null;
  owner_name: string | null;
  // APR as a percentage: 6.25 means 6.25%. Null means interest is not
  // modelled, which is the default — a guessed rate gives a confidently wrong
  // balance, and that is worse than an obviously stale one.
  interest_rate: string | null;
  minimum_payment: string | null;
  // Day of the month a card's statement closes. Null keeps the card out of the
  // Budget page's obligations panel rather than guessing at a due date.
  statement_day: number | null;
  payment_category_id: string | null;
  last_synced_at: string | null;
};

/** A household member, as far as the account owner picker is concerned. */
export type AccountOwner = { id: string; display_name: string };

export type AccountPayload = {
  name: string;
  institution_name: string | null;
  type: AccountType;
  kind: AccountKind;
  current_balance: number;
  is_on_budget: boolean;
  credit_limit: number | null;
  interest_rate?: number | null;
  minimum_payment?: number | null;
  statement_day?: number | null;
};

export const accountTypeOptions: { value: AccountType; label: string }[] = [
  { value: "checking", label: "Checking" },
  { value: "savings", label: "Savings" },
  { value: "credit", label: "Credit card" },
  { value: "brokerage", label: "Brokerage" },
  // Kept apart from a brokerage: the tax treatment differs, and so does what
  // the money can be used for before retirement.
  { value: "retirement", label: "Retirement (401k, IRA)" },
  { value: "investment", label: "Other investment" },
  { value: "mortgage", label: "Mortgage" },
  { value: "loan", label: "Loan" },
  { value: "debt", label: "Other debt" },
  { value: "cash", label: "Cash" },
  { value: "other", label: "Other" },
];

export function kindForType(
  type: AccountType,
  fallback: AccountKind = "asset",
): AccountKind {
  if (["credit", "mortgage", "loan", "debt"].includes(type)) return "liability";
  if (type === "other") return fallback;
  return "asset";
}

export function accountTypeLabel(type: AccountType) {
  return accountTypeOptions.find((option) => option.value === type)?.label ?? type;
}

export function accountBalance(account: Account) {
  return Number(account.current_balance);
}

export type LabelableAccount = Pick<Account, "id" | "name"> &
  Partial<Pick<Account, "mask" | "owner_name" | "statement_day">>;

function ordinalDay(day: number): string {
  const mod100 = day % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${day}th`;
  if (day % 10 === 1) return `${day}st`;
  if (day % 10 === 2) return `${day}nd`;
  if (day % 10 === 3) return `${day}rd`;
  return `${day}th`;
}

/**
 * A name that identifies one account among several with the same name.
 *
 * Two people in this household hold the same two cards — a Chase Prime and a
 * Discover it each — so four accounts arrive from Plaid carrying two names
 * between them. A list showing "Discover it Card" twice is not a list.
 *
 * The owner is added **only when it disambiguates**: the whole set is checked,
 * and a uniquely-named account keeps its plain name. Labelling everything
 * "Checking (Alex)" would be noise on the accounts that never needed it, and
 * the point is to make the ambiguous pair readable, not to caption the ledger.
 *
 * Falls back to the last four digits when both accounts share an owner or
 * neither has one, since that is what a person would use to tell two of their
 * own cards apart. Manual cards often have no mask, so a unique statement
 * close day is the final useful discriminator before preserving the plain
 * name.
 */
export function accountLabel(
  account: LabelableAccount,
  among: LabelableAccount[],
): string {
  const twins = among.filter(
    (other) => other.id !== account.id && other.name === account.name,
  );
  if (twins.length === 0) return account.name;
  if (account.owner_name && twins.every((t) => t.owner_name !== account.owner_name)) {
    return `${account.name} (${account.owner_name})`;
  }
  if (account.mask) return `${account.name} ••${account.mask}`;
  if (
    account.statement_day &&
    twins.every((t) => t.statement_day !== account.statement_day)
  ) {
    return `${account.name} (closes ${ordinalDay(account.statement_day)})`;
  }
  return account.name;
}



/** Debts whose balance can be modelled forward from a rate and a payment. */
export const BORROWING_TYPES: AccountType[] = ["loan", "mortgage", "debt"];

export function isBorrowing(type: AccountType): boolean {
  return BORROWING_TYPES.includes(type);
}
