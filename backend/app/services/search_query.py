"""
Turning "costco over $100 last spring" into filters.

The filter panel is four dropdowns and two date fields, which is fine at a desk
and miserable on a phone. The command bar already exists; this lets it take a
sentence.

**The model never touches the database.** It returns a small JSON object, that
object is validated field by field against a closed schema, and anything it
does not recognise is dropped. A model that hallucinates a filter gets an
ignored filter, not a query. This is the same reason the assistant is handed a
snapshot rather than a connection.

Dates are resolved *here* rather than by the model, because models are
famously poor at "last spring" and a wrong date range returns a confidently
empty screen with nothing to indicate why.
"""

import json
import re
from datetime import date, timedelta

# What a filter may contain. Anything outside this is dropped rather than
# passed along, so a hallucinated key cannot reach the query builder.
ALLOWED = frozenset(
    {
        "text",
        "min_amount",
        "max_amount",
        "start",
        "end",
        "category",
        "direction",
        "account",
    }
)

DIRECTIONS = frozenset({"in", "out"})

SYSTEM_PROMPT = (
    "You convert a person's plain-English request into a JSON filter for "
    "their own transaction list. Reply with JSON only, no prose.\n"
    "Keys you may use, all optional:\n"
    '  "text": merchant or description words to match\n'
    '  "min_amount", "max_amount": positive numbers, in dollars\n'
    '  "direction": "in" for money received, "out" for money spent\n'
    '  "category": a category name if one is clearly named\n'
    '  "account": an account name if one is clearly named\n'
    '  "period": one of "this_month", "last_month", "this_year", '
    '"last_year", "last_30_days", "last_90_days", "spring", "summer", '
    '"autumn", "winter"\n'
    '  "year": a four-digit year, if one is stated\n'
    "Use only what the request actually says. Omit anything not stated — an "
    "absent key is far better than a guessed one.\n"
    'Example: "costco over $100 last spring" → '
    '{"text": "costco", "min_amount": 100, "period": "spring"}'
)

# Northern-hemisphere seasons, since that is where this household is. Kept
# explicit rather than computed so the boundaries are visible and arguable.
SEASONS = {
    "spring": (3, 5),
    "summer": (6, 8),
    "autumn": (9, 11),
    "fall": (9, 11),
    "winter": (12, 2),
}


def _clamp_month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def resolve_period(period: str | None, year: int | None, today: date):
    """
    A named period into real dates.

    Resolved here rather than by the model: models are unreliable at "last
    spring", and a wrong range returns a confidently empty screen with nothing
    to say why.
    """
    if not period:
        if year:
            return date(year, 1, 1), date(year, 12, 31)
        return None, None

    period = period.strip().lower()
    if period == "this_month":
        return today.replace(day=1), _clamp_month_end(today.year, today.month)
    if period == "last_month":
        first = today.replace(day=1)
        previous = first - timedelta(days=1)
        return previous.replace(day=1), previous
    if period == "this_year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if period == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if period == "last_30_days":
        return today - timedelta(days=30), today
    if period == "last_90_days":
        return today - timedelta(days=90), today

    if period in SEASONS:
        start_month, end_month = SEASONS[period]
        target = year or today.year
        if start_month > end_month:
            # Winter spans the new year. "Last winter" means the one that just
            # ended, so it starts in the previous December.
            return date(target - 1, start_month, 1), _clamp_month_end(target, end_month)
        first = date(target, start_month, 1)
        # Without an explicit year, a season still ahead of us means last
        # year's — nobody asks about spending they have not done yet.
        if year is None and first > today:
            target -= 1
            first = date(target, start_month, 1)
        return first, _clamp_month_end(target, end_month)

    return None, None


def parse(raw: str, today: date) -> dict:
    """
    Validate the model's reply into a filter, dropping anything unrecognised.

    Returns `{}` when nothing usable survives, which the caller shows as "I did
    not understand that" rather than as an empty result set — the two look
    identical on screen and mean opposite things.
    """
    text = re.sub(r"```(?:json)?|```", " ", raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}

    out: dict = {}

    words = data.get("text")
    if isinstance(words, str) and words.strip():
        out["text"] = words.strip()[:120]

    for key in ("min_amount", "max_amount"):
        value = data.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            out[key] = round(float(value), 2)
        elif isinstance(value, str):
            cleaned = re.sub(r"[^0-9.]", "", value)
            if cleaned:
                try:
                    out[key] = round(float(cleaned), 2)
                except ValueError:
                    pass
    # A model that returns them backwards should not produce an empty screen.
    if "min_amount" in out and "max_amount" in out and out["min_amount"] > out["max_amount"]:
        out["min_amount"], out["max_amount"] = out["max_amount"], out["min_amount"]

    direction = data.get("direction")
    if isinstance(direction, str) and direction.strip().lower() in DIRECTIONS:
        out["direction"] = direction.strip().lower()

    for key in ("category", "account"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()[:80]

    year = data.get("year")
    if isinstance(year, str) and year.isdigit():
        year = int(year)
    if not isinstance(year, int) or not (1970 <= year <= today.year + 1):
        year = None

    period = data.get("period") if isinstance(data.get("period"), str) else None
    start_date, end_date = resolve_period(period, year, today)
    if start_date:
        out["start"] = start_date.isoformat()
    if end_date:
        out["end"] = end_date.isoformat()

    return {key: value for key, value in out.items() if key in ALLOWED}
