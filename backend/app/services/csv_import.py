"""
Bringing a CSV in.

Until now the only ways into this ledger were Plaid and typing one transaction
at a time. Alex keeps accounts Plaid cannot reach, and "type in a year of
them" is not a workflow.

Every bank exports a different shape, so the columns are **detected and then
shown for confirmation** rather than guessed silently. A misread column turns
$1,200 of rent into income; that has to be somebody's decision, not a heuristic
running unattended.

Three decisions worth stating:

**The sign is the dangerous part.** Some banks export one signed `Amount`
column, others two (`Debit`/`Credit`), and others a positive number with a
separate direction field. Getting it backwards inverts a whole statement, so
the preview shows what Raven concluded — "these 34 rows are money out" — and
the import is refused if every row would land on the same side of zero, which
is almost always a misread rather than a real statement.

**Nothing is written until the preview is accepted.** Parsing and importing are
separate calls with separate endpoints.

**Duplicates are found on the way in.** A CSV usually overlaps the last one, so
a row matching an existing transaction on account, date and amount is flagged
in the preview and skipped by default. Importing the same file twice should be
boring.
"""

import csv
import io
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction

MAX_ROWS = 5000
MAX_BYTES = 4 * 1024 * 1024

# Header names seen in the wild, lowercased. Order matters: the first match
# wins, so the more specific names come first.
HEADERS = {
    "date": ("date", "transaction date", "posted date", "post date", "posting date"),
    "amount": ("amount", "transaction amount", "value"),
    "debit": ("debit", "withdrawal", "money out", "paid out"),
    "credit": ("credit", "deposit", "money in", "paid in"),
    "merchant": ("description", "merchant", "name", "payee", "details", "memo"),
    "category": ("category", "type"),
}

DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m/%d/%y",
    "%d-%m-%Y",
    "%b %d, %Y",
    "%d %b %Y",
    "%Y/%m/%d",
)


class ImportError_(ValueError):
    """Something a person should be told about, in their own words."""


def _clean_amount(raw: str) -> Decimal | None:
    """
    A money column into a number.

    Handles `$1,234.56`, `(45.00)` for negatives — accountancy's own notation,
    and easy to read as a positive — and a trailing `CR`/`DR`.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if re.search(r"\bdr\b", text, re.I):
        negative = True
    text = re.sub(r"\b(cr|dr)\b", "", text, flags=re.I)
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text or text in {"-", "."}:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return -value if negative else value


def _clean_date(raw: str) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def detect_columns(headers: list[str]) -> dict[str, str | None]:
    """
    Match a file's headers to the fields Raven needs.

    Returned for confirmation rather than acted on: banks reuse words like
    "type" and "amount" for different things, and a wrong guess here inverts a
    statement.
    """
    lowered = {h.strip().lower(): h for h in headers if h}
    found: dict[str, str | None] = {}
    for field, candidates in HEADERS.items():
        found[field] = next(
            (lowered[c] for c in candidates if c in lowered), None
        )
    return found


def parse(content: bytes, mapping: dict[str, str | None] | None = None) -> dict:
    """
    Read a CSV into rows Raven could import, without importing anything.

    Returns the detected mapping, the parsed rows, and every row it could not
    read — the last of those matters most, because a silent skip is how half a
    statement goes missing without anybody noticing.
    """
    if len(content) > MAX_BYTES:
        raise ImportError_("That file is larger than 4MB.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise ImportError_("That file is not text Raven can read.") from exc

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ImportError_("That file has no header row.")

    columns = mapping or detect_columns(list(reader.fieldnames))
    if not columns.get("date"):
        raise ImportError_(
            "Raven could not find a date column. Say which one it is and try "
            "again."
        )
    has_amount = columns.get("amount")
    has_pair = columns.get("debit") or columns.get("credit")
    if not has_amount and not has_pair:
        raise ImportError_(
            "Raven could not find an amount column, or a debit/credit pair."
        )

    rows: list[dict] = []
    skipped: list[dict] = []
    for index, raw in enumerate(reader, start=2):  # row 1 is the header
        if len(rows) >= MAX_ROWS:
            skipped.append({"row": index, "reason": f"Past the {MAX_ROWS} row limit"})
            break
        when = _clean_date(raw.get(columns["date"], ""))
        if when is None:
            skipped.append({"row": index, "reason": "Could not read the date"})
            continue

        if has_amount:
            amount = _clean_amount(raw.get(columns["amount"], ""))
        else:
            debit = _clean_amount(raw.get(columns.get("debit") or "", "")) or Decimal(0)
            credit = _clean_amount(raw.get(columns.get("credit") or "", "")) or Decimal(0)
            # Debit columns are written positive and mean money out.
            amount = credit - abs(debit)
        if amount is None or amount == 0:
            skipped.append({"row": index, "reason": "Could not read the amount"})
            continue

        merchant = (raw.get(columns.get("merchant") or "", "") or "").strip()
        rows.append(
            {
                "row": index,
                "posted_date": when.isoformat(),
                "amount": str(amount),
                "merchant": merchant[:255] or "Imported transaction",
                "category_hint": (
                    raw.get(columns.get("category") or "", "") or ""
                ).strip()[:100],
            }
        )

    outflows = sum(1 for r in rows if Decimal(r["amount"]) < 0)
    inflows = len(rows) - outflows
    return {
        "columns": columns,
        "headers": list(reader.fieldnames),
        "rows": rows,
        "skipped": skipped,
        "outflows": outflows,
        "inflows": inflows,
        # Almost always a misread sign column rather than a real statement, so
        # it is surfaced as a question rather than imported and discovered
        # later.
        "all_one_direction": bool(rows) and (outflows == 0 or inflows == 0),
    }


async def find_duplicates(
    db: AsyncSession, account_id: uuid.UUID, rows: list[dict]
) -> set[int]:
    """
    Which rows already exist, by account, date and amount.

    A CSV almost always overlaps the previous one; importing the same file
    twice should be boring rather than a mess to unpick afterwards.
    """
    if not rows:
        return set()
    dates = {date.fromisoformat(r["posted_date"]) for r in rows}
    existing = (
        await db.execute(
            select(Transaction.posted_date, Transaction.amount).where(
                Transaction.account_id == account_id,
                Transaction.posted_date.in_(dates),
            )
        )
    ).all()
    seen = {(d, Decimal(a)) for d, a in existing}
    return {
        r["row"]
        for r in rows
        if (date.fromisoformat(r["posted_date"]), Decimal(r["amount"])) in seen
    }
