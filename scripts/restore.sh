#!/usr/bin/env bash
#
# Restore a Raven Ledger backup over the live database.
#
# This is the destructive counterpart to the "Verify" button in Settings.
# Verification proves an archive *can* restore, into a scratch database, while
# the app keeps running. This script is what you run when you actually need the
# data back: it stops the application, replaces the database, and starts it
# again.
#
#   ./scripts/restore.sh raven-20260801T031000Z.dump
#
# The archive is whatever you downloaded from Settings -> Backups, or a file
# from the backup volume. Everything runs through `docker compose`, so no
# PostgreSQL client is needed on the machine you run this from.
#
# One thing this cannot restore is the encryption key. Plaid access tokens are
# encrypted with RAVEN_ENCRYPTION_KEY, which lives in .env and never in the
# dump. Restore into a stack with a different key and every bank connection
# will fail on its next sync while the rest of the app looks perfect. The
# fingerprint check below is there to catch exactly that.

set -euo pipefail

DUMP="${1:-}"
COMPOSE="${COMPOSE:-docker compose}"
APP_SERVICES=(frontend worker backend)

die() { printf '\nerror: %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

[ -n "$DUMP" ] || die "usage: $0 <backup.dump>

Available on the backup volume:
$($COMPOSE exec -T backend sh -c 'ls -1sh /backups/*.dump 2>/dev/null' || echo '  (none readable)')"

[ -f "$DUMP" ] || die "$DUMP does not exist."

cd "$(dirname "$0")/.."

# An explicit POSTGRES_DB/POSTGRES_USER in the environment wins; otherwise read
# .env, and fall back to the compose defaults.
from_env_file() {
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -1 | cut -d= -f2-
}
DB_NAME="${POSTGRES_DB:-$(from_env_file POSTGRES_DB)}"
DB_USER="${POSTGRES_USER:-$(from_env_file POSTGRES_USER)}"
DB_NAME="${DB_NAME:-raven}"
DB_USER="${DB_USER:-raven}"

# Every non-interactive compose exec reads from /dev/null. `exec -T` forwards
# stdin into the container, which would otherwise swallow the confirmation
# this script is about to ask for.
psql_admin() {
  $COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d postgres "$@" </dev/null
}

step "Checking the archive"
$COMPOSE ps postgres >/dev/null 2>&1 || die "the postgres service is not running."
$COMPOSE cp "$DUMP" postgres:/tmp/raven-restore.dump
$COMPOSE exec -T postgres pg_restore --list /tmp/raven-restore.dump >/dev/null </dev/null \
  || die "$DUMP is not a readable custom-format archive."
printf 'archive is readable\n'

MANIFEST="${DUMP}.json"
if [ -f "$MANIFEST" ]; then
  WANTED="$(grep -o '"encryption_fingerprint": *"[^"]*"' "$MANIFEST" | cut -d'"' -f4 || true)"
  CURRENT="$($COMPOSE exec -T backend python -c \
    'from app.services.backup import encryption_fingerprint; print(encryption_fingerprint())' \
    2>/dev/null </dev/null | tr -d '\r' || true)"
  if [ -n "$WANTED" ] && [ -n "$CURRENT" ] && [ "$WANTED" != "$CURRENT" ]; then
    printf '\n\033[31mEncryption key mismatch.\033[0m\n'
    printf '  archive was written under key %s\n  this stack is using key    %s\n' \
      "$WANTED" "$CURRENT"
    printf 'Bank connections in this archive will not decrypt. Restore the matching\n'
    printf 'RAVEN_ENCRYPTION_KEY into .env first, or continue knowing every\n'
    printf 'institution must be relinked.\n'
    read -r -p 'Continue anyway? [y/N] ' reply
    [ "$reply" = "y" ] || die "stopped."
  elif [ -n "$WANTED" ]; then
    printf 'encryption key matches (%s)\n' "$CURRENT"
  fi
fi

printf '\nThis replaces the "%s" database entirely. Current data is lost.\n' "$DB_NAME"
read -r -p 'Type the database name to confirm: ' reply
[ "$reply" = "$DB_NAME" ] || die "stopped."

step "Stopping the application"
# Everything holding a connection has to go, or DROP DATABASE cannot proceed.
$COMPOSE stop "${APP_SERVICES[@]}"

step "Replacing the database"
psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
               WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" >/dev/null
psql_admin -c "DROP DATABASE IF EXISTS \"$DB_NAME\" WITH (FORCE);"
psql_admin -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\";"
$COMPOSE exec -T postgres pg_restore \
  --dbname "$DB_NAME" --username "$DB_USER" \
  --no-owner --no-privileges --exit-on-error \
  /tmp/raven-restore.dump </dev/null
$COMPOSE exec -T postgres rm -f /tmp/raven-restore.dump </dev/null

step "What came back"
$COMPOSE exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT 'households' AS table, count(*) FROM households
   UNION ALL SELECT 'users', count(*) FROM users
   UNION ALL SELECT 'accounts', count(*) FROM accounts
   UNION ALL SELECT 'transactions', count(*) FROM transactions
   UNION ALL SELECT 'categories', count(*) FROM categories
   UNION ALL SELECT 'institution_connections', count(*) FROM institution_connections;" </dev/null

step "Starting the application"
# Reverse order: the backend runs migrations, so it must be healthy first.
$COMPOSE start backend
$COMPOSE start worker frontend

printf '\nRestored. Sign in and confirm balances, then run one Sync now to prove\n'
printf 'the provider tokens still decrypt.\n'
