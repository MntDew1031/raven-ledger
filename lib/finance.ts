export type Category = {
  id: string;
  group_id: string;
  group_name: string;
  group_is_income: boolean;
  name: string;
  color: string;
  icon: string | null;
  flex_bucket: "fixed" | "flex" | "non_monthly" | "goal";
  excluded_from_budget: boolean;
  // -1 means this category counts against the previous month's plan.
  budget_month_offset: number;
};

export type Tag = {
  id: string;
  name: string;
  color: string;
};

export type Transaction = {
  id: string;
  account_id: string;
  category_id: string | null;
  merchant_name: string | null;
  original_description: string;
  amount: string;
  posted_date: string;
  // Which month's plan this counts against, when that is not the month it
  // posted in. Null for almost every row.
  budget_month: string | null;
  pending: boolean;
  is_manual: boolean;
  excluded_from_budget: boolean;
  is_transfer: boolean;
  notes: string | null;
  reviewed: boolean;
  categorization_source: string | null;
  tags: Tag[];
  // A split parent is a container, not an amount. Never add it to a total
  // alongside its own lines — that is the same money counted twice.
  is_split: boolean;
  parent_transaction_id: string | null;
  splits: SplitLine[];
};

export type SplitLine = {
  id: string | null;
  category_id: string | null;
  amount: string;
  notes: string | null;
  excluded_from_budget: boolean;
  tags: Tag[];
};

export type BudgetLine = {
  id?: string;
  category_id: string;
  planned_amount: string | number;
  rollover_enabled: boolean;
  rollover_amount?: string | number;
  non_monthly_target: string | number | null;
  non_monthly_due_date: string | null;
};

export type Budget = {
  id: string;
  month: string;
  mode: "category" | "flex";
  expected_income: string | number;
  flex_amount: string | number;
  // null lets the pay dates decide how many cheques this month holds; true
  // and false override that for this month alone.
  extra_paycheque: boolean | null;
  lines: BudgetLine[];
};
