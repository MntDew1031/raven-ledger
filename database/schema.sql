CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
  CREATE TYPE household_role AS ENUM ('owner', 'member', 'viewer');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TYPE account_kind AS ENUM ('asset', 'liability');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TYPE account_type AS ENUM (
    'checking', 'savings', 'credit', 'investment',
    'retirement', 'brokerage', 'loan',
    'mortgage', 'debt', 'cash', 'other'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TYPE budget_mode AS ENUM ('category', 'flex');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TYPE flex_bucket AS ENUM ('fixed', 'flex', 'non_monthly', 'goal');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TYPE rule_match_type AS ENUM ('contains', 'exact', 'regex');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(320) NOT NULL UNIQUE,
  display_name VARCHAR(120) NOT NULL,
  password_hash TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  mfa_secret_encrypted TEXT,
  mfa_enabled_at TIMESTAMPTZ,
  mfa_recovery_codes JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_profiles (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  theme VARCHAR(16) NOT NULL DEFAULT 'system',
  accent VARCHAR(16) NOT NULL DEFAULT 'obsidian',
  density VARCHAR(16) NOT NULL DEFAULT 'comfortable',
  -- How buttons are drawn. A separate axis from `theme`: every treatment
  -- has to work under every colour scheme, light and dark alike.
  button_style VARCHAR(16) NOT NULL DEFAULT 'iris',
  start_page VARCHAR(32) NOT NULL DEFAULT '/',
  avatar_data BYTEA,
  avatar_mime VARCHAR(40),
  avatar_revision VARCHAR(36),
  avatar_size INTEGER,
  onboarding_dismissed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT user_profile_theme
    CHECK (theme IN (
      'system', 'light', 'parchment', 'dark', 'midnight', 'aurora'
    )),
  CONSTRAINT user_profile_accent
    CHECK (accent IN (
      'obsidian', 'green', 'orange', 'red', 'blue', 'plum'
    )),
  CONSTRAINT user_profile_density
    CHECK (density IN ('comfortable', 'compact')),
  CONSTRAINT user_profile_button_style
    CHECK (button_style IN ('iris', 'solid', 'flat', 'duotone', 'restrained')),
  CONSTRAINT user_profile_start_page
    CHECK (start_page IN (
      '/', '/accounts', '/transactions', '/budgets', '/reports'
    ))
);

CREATE TABLE IF NOT EXISTS households (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(120) NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'USD',
  timezone VARCHAR(64) NOT NULL DEFAULT 'America/Phoenix',
  is_sandbox BOOLEAN NOT NULL DEFAULT FALSE,
  cloned_from_id UUID REFERENCES households(id) ON DELETE SET NULL,
  cloned_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS household_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role household_role NOT NULL DEFAULT 'member',
  joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (household_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_household_members_user ON household_members(user_id);

CREATE TABLE IF NOT EXISTS household_invites (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  invited_email VARCHAR(320) NOT NULL,
  token_hash CHAR(64) NOT NULL UNIQUE,
  role household_role NOT NULL DEFAULT 'member',
  expires_at TIMESTAMPTZ NOT NULL,
  accepted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS institution_connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  provider VARCHAR(30) NOT NULL DEFAULT 'plaid',
  provider_item_id VARCHAR(255) NOT NULL UNIQUE,
  institution_id VARCHAR(255),
  institution_name VARCHAR(255),
  encrypted_access_token TEXT NOT NULL,
  -- Who was signed in when this was linked. Used to stamp an owner onto the
  -- accounts it creates, so two people holding the same card can tell theirs
  -- apart. NULL for connections made before this was recorded.
  linked_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  cursor TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'healthy',
  last_synced_at TIMESTAMPTZ,
  error_code VARCHAR(120),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  connection_id UUID REFERENCES institution_connections(id) ON DELETE SET NULL,
  provider_account_id VARCHAR(255),
  name VARCHAR(160) NOT NULL,
  official_name VARCHAR(255),
  institution_name VARCHAR(255),
  mask VARCHAR(8),
  type account_type NOT NULL,
  subtype VARCHAR(80),
  kind account_kind NOT NULL,
  is_on_budget BOOLEAN NOT NULL DEFAULT TRUE,
  is_manual BOOLEAN NOT NULL DEFAULT FALSE,
  is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
  -- Whose account this is. NULL means shared, which is right for a joint one.
  owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  -- APR as a percentage: 6.25 means 6.25%. NULL means do not model interest.
  -- What the account held before the first recorded transaction.
  opening_balance NUMERIC(18, 2),
  interest_rate NUMERIC(6, 3),
  minimum_payment NUMERIC(18, 2),
  interest_applied_through DATE,
  current_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
  available_balance NUMERIC(18,2),
  credit_limit NUMERIC(18,2),
  -- Day of the month this card's statement closes.
  statement_day SMALLINT,
  currency CHAR(3) NOT NULL DEFAULT 'USD',
  last_synced_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT account_statement_day
    CHECK (statement_day IS NULL OR (statement_day BETWEEN 1 AND 31)),
  CONSTRAINT uq_accounts_household_provider
    UNIQUE (household_id, provider_account_id)
);
CREATE INDEX IF NOT EXISTS ix_accounts_household ON accounts(household_id);

CREATE TABLE IF NOT EXISTS category_groups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  name VARCHAR(100) NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_income BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (household_id, name)
);

DO $$ BEGIN
  CREATE TYPE pay_cadence AS ENUM (
    'weekly', 'biweekly', 'semimonthly', 'monthly', 'annual'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE proposal_kind AS ENUM (
    'category', 'duplicate', 'transfer', 'exclusion', 'rule', 'budget'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE proposal_status AS ENUM (
    'pending', 'approved', 'rejected', 'stale'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS income_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  -- Whose pay this is. A name rather than a user id: an earner does not have
  -- to have an account here for their pay to be worth planning around.
  name VARCHAR(80) NOT NULL,
  amount NUMERIC(18, 2) NOT NULL DEFAULT 0,
  cadence pay_cadence NOT NULL DEFAULT 'monthly',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  -- Any one real pay date; which months carry a third cheque follows from it.
  first_paid_on DATE,
  notes VARCHAR(400),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (household_id, name)
);

CREATE INDEX IF NOT EXISTS income_sources_household_idx
  ON income_sources (household_id);

DO $$ BEGIN
  CREATE TYPE memory_source AS ENUM ('person', 'assistant', 'derived');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS app_settings (
  key VARCHAR(64) PRIMARY KEY,
  -- JSONB so a setting can grow a shape later without another migration.
  value JSONB NOT NULL,
  updated_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS activity_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  kind VARCHAR(40) NOT NULL,
  summary VARCHAR(300) NOT NULL,
  -- Everything needed to put it back: one entry per field changed, carrying
  -- the value it held before. Written at the time; after the fact it cannot
  -- be reconstructed.
  changes JSONB NOT NULL,
  undone_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS activity_log_recent_idx
  ON activity_log (household_id, created_at DESC);

CREATE TABLE IF NOT EXISTS security_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID REFERENCES households(id) ON DELETE SET NULL,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  event_type VARCHAR(80) NOT NULL,
  success BOOLEAN NOT NULL DEFAULT TRUE,
  ip_address VARCHAR(64),
  user_agent VARCHAR(240),
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS security_events_household_recent
  ON security_events (household_id, created_at DESC);
CREATE INDEX IF NOT EXISTS security_events_user_recent
  ON security_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_security_events_event_type
  ON security_events (event_type);

CREATE TABLE IF NOT EXISTS goals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  name VARCHAR(120) NOT NULL,
  target_amount NUMERIC(18, 2) NOT NULL,
  target_date DATE,
  -- Optional: most goals start being tracked before they have an account.
  account_id UUID REFERENCES accounts(id) ON DELETE SET NULL,
  -- Only consulted when no account is linked. With one, the balance is the
  -- truth; two sources of the same number disagree eventually.
  saved_amount NUMERIC(18, 2) NOT NULL DEFAULT 0,
  notes VARCHAR(400),
  is_achieved BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (household_id, name)
);

CREATE INDEX IF NOT EXISTS goals_household_idx
  ON goals (household_id, is_achieved);

CREATE TABLE IF NOT EXISTS assistant_threads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  -- A household shares a ledger but not its half-finished questions about
  -- money, so a thread belongs to a person.
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title VARCHAR(160) NOT NULL DEFAULT 'New conversation',
  last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS assistant_threads_recent_idx
  ON assistant_threads (user_id, last_message_at DESC);

CREATE TABLE IF NOT EXISTS assistant_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id UUID NOT NULL REFERENCES assistant_threads(id) ON DELETE CASCADE,
  role VARCHAR(16) NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS assistant_messages_thread_idx
  ON assistant_messages (thread_id, created_at);

CREATE TABLE IF NOT EXISTS assistant_memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  -- One plain sentence. A memory needing a paragraph is a note, and a wall of
  -- them cannot be skimmed to find the one that stopped being true.
  fact VARCHAR(400) NOT NULL,
  source memory_source NOT NULL DEFAULT 'person',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  -- Raven proposes; a person confirms. Unconfirmed never reaches the model.
  confirmed_at TIMESTAMPTZ,
  created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS assistant_memories_household_idx
  ON assistant_memories (household_id, is_active);

CREATE TABLE IF NOT EXISTS ai_proposals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  kind proposal_kind NOT NULL,
  status proposal_status NOT NULL DEFAULT 'pending',
  -- What the change would do. Edited in place when somebody changes a
  -- proposal before accepting it, so approving applies exactly what was shown.
  payload JSONB NOT NULL,
  rationale VARCHAR(400) NOT NULL DEFAULT '',
  confidence NUMERIC(4, 3) NOT NULL DEFAULT 0.5,
  decided_at TIMESTAMPTZ,
  decided_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ai_proposals_pending_idx
  ON ai_proposals (household_id, status, kind);

CREATE TABLE IF NOT EXISTS categories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  group_id UUID NOT NULL REFERENCES category_groups(id) ON DELETE CASCADE,
  name VARCHAR(100) NOT NULL,
  color CHAR(7) NOT NULL DEFAULT '#7f8b81',
  icon VARCHAR(40),
  flex_bucket flex_bucket NOT NULL DEFAULT 'flex',
  is_archived BOOLEAN NOT NULL DEFAULT FALSE,
  -- Kept out of every budget and spending total, permanently. For money that
  -- passes through the ledger without being yours to spend: reimbursed work
  -- expenses, a housemate's share, a category kept only for records.
  excluded_from_budget BOOLEAN NOT NULL DEFAULT FALSE,
  -- Months to shift this category's spending when the *budget* reads it.
  -- -1 means "counts against the previous month's plan", which is what rent
  -- due on the 1st and paid from last month's pay is. 0 changes nothing.
  budget_month_offset SMALLINT NOT NULL DEFAULT 0
    CONSTRAINT category_budget_offset CHECK (budget_month_offset BETWEEN -1 AND 1),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (household_id, name)
);

-- Added after `categories` exists rather than inside the `accounts`
-- definition two hundred lines above it: this file is applied in one pass, so
-- a column referencing a table declared later cannot work.
ALTER TABLE accounts
  ADD COLUMN IF NOT EXISTS payment_category_id UUID
  REFERENCES categories(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS tags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  name VARCHAR(80) NOT NULL,
  color CHAR(7) NOT NULL DEFAULT '#d8924d',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (household_id, name)
);

CREATE TABLE IF NOT EXISTS transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  category_id UUID REFERENCES categories(id) ON DELETE SET NULL,
  provider_transaction_id VARCHAR(255),
  pending_provider_transaction_id VARCHAR(255),
  merchant_name VARCHAR(255),
  original_description TEXT NOT NULL,
  normalized_merchant VARCHAR(255),
  amount NUMERIC(18,2) NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'USD',
  posted_date DATE NOT NULL,
  -- Which month's *plan* this counts against, when that is not the month it
  -- posted in. Rent due on the 1st is paid from the previous month's pay, so
  -- it belongs to that month's budget while posting in this one. NULL — the
  -- default and almost every row — means "the month it posted in".
  -- `posted_date` above is untouched: reports are history.
  budget_month DATE,
  authorized_date DATE,
  pending BOOLEAN NOT NULL DEFAULT FALSE,
  excluded_from_budget BOOLEAN NOT NULL DEFAULT FALSE,
  -- Overrides the account's owner for this one transaction.
  paid_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  is_transfer BOOLEAN NOT NULL DEFAULT FALSE,
  notes TEXT,
  reviewed BOOLEAN NOT NULL DEFAULT FALSE,
  categorization_source VARCHAR(40),
  provider_category VARCHAR(120),
  parent_transaction_id UUID REFERENCES transactions(id) ON DELETE CASCADE,
  is_split BOOLEAN NOT NULL DEFAULT FALSE,
  amount_overridden BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_transactions_account_provider
    UNIQUE (account_id, provider_transaction_id)
);
CREATE INDEX IF NOT EXISTS ix_transactions_household_date
  ON transactions(household_id, posted_date DESC);
CREATE INDEX IF NOT EXISTS ix_transactions_household_category
  ON transactions(household_id, category_id);
CREATE INDEX IF NOT EXISTS ix_transactions_parent
  ON transactions(parent_transaction_id) WHERE parent_transaction_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_transactions_merchant
  ON transactions(household_id, normalized_merchant);

CREATE TABLE IF NOT EXISTS transaction_tags (
  transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (transaction_id, tag_id)
);

CREATE TABLE IF NOT EXISTS categorization_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  name VARCHAR(120) NOT NULL,
  match_type rule_match_type NOT NULL,
  merchant_pattern VARCHAR(255) NOT NULL,
  min_amount NUMERIC(18,2),
  max_amount NUMERIC(18,2),
  category_id UUID NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  tag_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  priority INTEGER NOT NULL DEFAULT 100,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_rules_household_priority
  ON categorization_rules(household_id, priority);

CREATE TABLE IF NOT EXISTS api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  created_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name VARCHAR(80) NOT NULL,
  token_hash VARCHAR(64) NOT NULL UNIQUE,
  prefix VARCHAR(16) NOT NULL,
  can_write BOOLEAN NOT NULL DEFAULT FALSE,
  last_used_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_api_keys_household ON api_keys (household_id);

CREATE TABLE IF NOT EXISTS merchant_memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  merchant_key VARCHAR(255) NOT NULL,
  category_id UUID NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  sample_label VARCHAR(255),
  source VARCHAR(20) NOT NULL DEFAULT 'human',
  hits INTEGER NOT NULL DEFAULT 0,
  last_applied_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (household_id, merchant_key)
);

CREATE INDEX IF NOT EXISTS ix_merchant_memories_household
  ON merchant_memories (household_id);

CREATE TABLE IF NOT EXISTS recurring_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  merchant_key VARCHAR(255) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  direction VARCHAR(10) NOT NULL DEFAULT 'outflow',
  cadence VARCHAR(16) NOT NULL,
  average_amount NUMERIC(18,2) NOT NULL,
  last_amount NUMERIC(18,2) NOT NULL,
  occurrences INTEGER NOT NULL,
  last_seen DATE NOT NULL,
  next_due DATE NOT NULL,
  category_id UUID REFERENCES categories(id) ON DELETE SET NULL,
  account_id UUID REFERENCES accounts(id) ON DELETE SET NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (household_id, merchant_key, direction)
);

CREATE INDEX IF NOT EXISTS ix_recurring_household
  ON recurring_items (household_id);

CREATE TABLE IF NOT EXISTS budgets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  month DATE NOT NULL,
  mode budget_mode NOT NULL DEFAULT 'category',
  expected_income NUMERIC(18,2) NOT NULL DEFAULT 0,
  flex_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
  -- NULL means "work it out from the pay dates". True/False override one month.
  extra_paycheque BOOLEAN,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (household_id, month),
  CONSTRAINT month_is_first_day CHECK (
    date_trunc('month', month::timestamp)::date = month
  )
);

CREATE TABLE IF NOT EXISTS budget_lines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  budget_id UUID NOT NULL REFERENCES budgets(id) ON DELETE CASCADE,
  category_id UUID NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  planned_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
  rollover_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  rollover_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
  non_monthly_target NUMERIC(18,2),
  non_monthly_due_date DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (budget_id, category_id)
);

CREATE TABLE IF NOT EXISTS holdings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  security_id VARCHAR(255) NOT NULL,
  ticker_symbol VARCHAR(20),
  name VARCHAR(255) NOT NULL,
  quantity NUMERIC(24,8) NOT NULL,
  price NUMERIC(18,4) NOT NULL,
  value NUMERIC(18,2) NOT NULL,
  cost_basis NUMERIC(18,2),
  as_of TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (account_id, security_id)
);

CREATE TABLE IF NOT EXISTS net_worth_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  snapshot_date DATE NOT NULL,
  assets NUMERIC(18,2) NOT NULL,
  liabilities NUMERIC(18,2) NOT NULL,
  net_worth NUMERIC(18,2) NOT NULL,
  UNIQUE (household_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS dashboard_widgets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  widget_key VARCHAR(80) NOT NULL,
  position INTEGER NOT NULL,
  settings JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, household_id, widget_key)
);

-- A change the assistant would like to make, which it cannot make itself.
-- The payload names intent ("everything from Chipotle with no category"), not
-- transaction ids: rows are resolved from the ledger at approval time, so a
-- model cannot propose a change to a row that does not exist, and a proposal
-- cannot act on rows edited between suggesting and approving.
CREATE TABLE IF NOT EXISTS assistant_proposals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  thread_id UUID REFERENCES assistant_threads(id) ON DELETE SET NULL,
  created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  kind VARCHAR(32) NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary VARCHAR(400) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  applied_at TIMESTAMPTZ,
  result JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT assistant_proposal_kind
    CHECK (kind IN ('categorize', 'create_rule')),
  CONSTRAINT assistant_proposal_status
    CHECK (status IN ('pending', 'approved', 'rejected', 'failed'))
);

CREATE INDEX IF NOT EXISTS assistant_proposals_household_idx
  ON assistant_proposals (household_id, status);

-- Defense in depth: a financial child row cannot reference an object from a
-- different household even if a future API query forgets its tenant filter.
-- The single-column foreign keys above retain their existing delete behavior;
-- these composite keys add the household-consistency invariant.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_institution_connections_id_household') THEN
    ALTER TABLE institution_connections ADD CONSTRAINT uq_institution_connections_id_household UNIQUE (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_accounts_id_household') THEN
    ALTER TABLE accounts ADD CONSTRAINT uq_accounts_id_household UNIQUE (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_category_groups_id_household') THEN
    ALTER TABLE category_groups ADD CONSTRAINT uq_category_groups_id_household UNIQUE (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_categories_id_household') THEN
    ALTER TABLE categories ADD CONSTRAINT uq_categories_id_household UNIQUE (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_transactions_id_household') THEN
    ALTER TABLE transactions ADD CONSTRAINT uq_transactions_id_household UNIQUE (id, household_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_accounts_connection_household') THEN
    ALTER TABLE accounts ADD CONSTRAINT fk_accounts_connection_household FOREIGN KEY (connection_id, household_id) REFERENCES institution_connections (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_accounts_payment_category_household') THEN
    ALTER TABLE accounts ADD CONSTRAINT fk_accounts_payment_category_household FOREIGN KEY (payment_category_id, household_id) REFERENCES categories (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_categories_group_household') THEN
    ALTER TABLE categories ADD CONSTRAINT fk_categories_group_household FOREIGN KEY (group_id, household_id) REFERENCES category_groups (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_transactions_account_household') THEN
    ALTER TABLE transactions ADD CONSTRAINT fk_transactions_account_household FOREIGN KEY (account_id, household_id) REFERENCES accounts (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_transactions_category_household') THEN
    ALTER TABLE transactions ADD CONSTRAINT fk_transactions_category_household FOREIGN KEY (category_id, household_id) REFERENCES categories (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_transactions_parent_household') THEN
    ALTER TABLE transactions ADD CONSTRAINT fk_transactions_parent_household FOREIGN KEY (parent_transaction_id, household_id) REFERENCES transactions (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_goals_account_household') THEN
    ALTER TABLE goals ADD CONSTRAINT fk_goals_account_household FOREIGN KEY (account_id, household_id) REFERENCES accounts (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_rules_category_household') THEN
    ALTER TABLE categorization_rules ADD CONSTRAINT fk_rules_category_household FOREIGN KEY (category_id, household_id) REFERENCES categories (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_merchant_memories_category_household') THEN
    ALTER TABLE merchant_memories ADD CONSTRAINT fk_merchant_memories_category_household FOREIGN KEY (category_id, household_id) REFERENCES categories (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_recurring_category_household') THEN
    ALTER TABLE recurring_items ADD CONSTRAINT fk_recurring_category_household FOREIGN KEY (category_id, household_id) REFERENCES categories (id, household_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_recurring_account_household') THEN
    ALTER TABLE recurring_items ADD CONSTRAINT fk_recurring_account_household FOREIGN KEY (account_id, household_id) REFERENCES accounts (id, household_id);
  END IF;
END $$;
