export const netWorthHistory = [
  { month: "Aug", value: -74400 },
  { month: "Sep", value: -72850 },
  { month: "Oct", value: -71420 },
  { month: "Nov", value: -70110 },
  { month: "Dec", value: -69380 },
  { month: "Jan", value: -68140 },
  { month: "Feb", value: -67480 },
  { month: "Mar", value: -66310 },
  { month: "Apr", value: -65190 },
  { month: "May", value: -64620 },
  { month: "Jun", value: -64220 },
  { month: "Jul", value: -64057.07 },
];

export const cashFlowData = [
  { month: "Feb", income: 6540, spending: 5010 },
  { month: "Mar", income: 6829, spending: 4720 },
  { month: "Apr", income: 6829, spending: 5180 },
  { month: "May", income: 7010, spending: 4590 },
  { month: "Jun", income: 6829, spending: 4860 },
  { month: "Jul", income: 6829, spending: 4195 },
];

export const accounts = [
  {
    name: "Emergency Savings",
    institution: "FCU",
    balance: 10128.15,
    kind: "asset" as const,
    type: "Savings",
  },
  {
    name: "SoFi Checking",
    institution: "SoFi",
    balance: 798,
    kind: "asset" as const,
    type: "Checking",
  },
  {
    name: "Vanguard 401K",
    institution: "Vanguard",
    balance: 5263.71,
    kind: "asset" as const,
    type: "Investment",
  },
  {
    name: "Fidelity Roth IRAs",
    institution: "Fidelity",
    balance: 1232.52,
    kind: "asset" as const,
    type: "Investment",
  },
  {
    name: "Credit Cards",
    institution: "4 institutions",
    balance: -626.72,
    kind: "liability" as const,
    type: "Credit",
  },
  {
    name: "Student Loans",
    institution: "NelNet + CRI",
    balance: -54790.17,
    kind: "liability" as const,
    type: "Debt",
  },
  {
    name: "Auto Loan",
    institution: "Auto Lender",
    balance: -25934.41,
    kind: "liability" as const,
    type: "Debt",
  },
];

export const budgetCategories = [
  { name: "Housing", plan: 1117, spent: 1117, tone: "required" },
  { name: "Transportation", plan: 1340.97, spent: 1032, tone: "required" },
  { name: "Food & household", plan: 533.25, spent: 402.18, tone: "required" },
  { name: "Utilities", plan: 445, spent: 362.44, tone: "required" },
  { name: "Subscriptions", plan: 129.72, spent: 106.22, tone: "flex" },
  { name: "Health & pet", plan: 87.5, spent: 50, tone: "required" },
  { name: "Debt payments", plan: 410.12, spent: 410.12, tone: "required" },
  { name: "Savings goals", plan: 500, spent: 500, tone: "saving" },
];

export const recentTransactions = [
  {
    merchant: "City Electric",
    category: "Utilities",
    amount: -184.32,
    date: "Today",
    tone: "red",
  },
  {
    merchant: "SoFi transfer",
    category: "Savings",
    amount: -500,
    date: "Yesterday",
    tone: "green",
  },
  {
    merchant: "Payroll",
    category: "Income",
    amount: 2050.25,
    date: "Jul 26",
    tone: "green",
  },
  {
    merchant: "Costco",
    category: "Groceries",
    amount: -142.18,
    date: "Jul 25",
    tone: "orange",
  },
];

export const transactionRows = [
  ...recentTransactions,
  {
    merchant: "BILT Rent",
    category: "Housing",
    amount: -1268.47,
    date: "Jul 24",
    tone: "red",
  },
  {
    merchant: "Shell",
    category: "Transportation",
    amount: -48.71,
    date: "Jul 23",
    tone: "red",
  },
  {
    merchant: "Apple",
    category: "Subscriptions",
    amount: -18.99,
    date: "Jul 22",
    tone: "orange",
  },
  {
    merchant: "Interest",
    category: "Income",
    amount: 39.12,
    date: "Jul 20",
    tone: "green",
  },
];

export const sankeyData = {
  nodes: [
    { name: "Income" },
    { name: "Required" },
    { name: "Flexible" },
    { name: "Goals" },
    { name: "Housing" },
    { name: "Transportation" },
    { name: "Utilities" },
    { name: "Food" },
    { name: "Subscriptions" },
    { name: "Savings" },
  ],
  links: [
    { source: 0, target: 1, value: 3350 },
    { source: 0, target: 2, value: 845 },
    { source: 0, target: 3, value: 1257 },
    { source: 1, target: 4, value: 1268 },
    { source: 1, target: 5, value: 1340 },
    { source: 1, target: 6, value: 742 },
    { source: 2, target: 7, value: 691 },
    { source: 2, target: 8, value: 154 },
    { source: 3, target: 9, value: 1257 },
  ],
};
