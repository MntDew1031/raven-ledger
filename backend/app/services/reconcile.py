"""
Does this account add up?

Five separate classes of bug have corrupted numbers in this ledger, and every
one of them was invisible until a figure happened to look odd to a person:

- a positive amount filed into a spending category ("INTERNET PAYMENT" → Utilities)
- both legs of a card payment counted, once as a bill and once as income
- the same charge posted twice when it settled
- outflows in an income category counted as spending
- a keyword match that never looked at the amount

They share a shape: the *transactions* stop agreeing with the *balance*, and
nothing says so. This is the check that says so.

**What it compares.** For an account with a starting point, the balance implied
by every transaction on it against the balance the account claims. A gap means
one of three things, and the wording says which is likeliest rather than just
printing a number:

- transactions are missing (a gap the size of one plausible charge),
- something is counted twice (a gap exactly equal to an existing transaction),
- or the starting balance was never right.

**What it does not do.** It never corrects anything. A reconciliation that
silently adjusts a balance to match its own arithmetic is a reconciliation that
can never find anything again.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Transaction
from app.services.splits import countable

# Below this, a gap is rounding or a pending charge rather than a fault. Set in
# money rather than percent: a dollar out on a $200 account matters as much as
# a dollar out on a $20,000 one, and a percentage would hide the second.
TOLERANCE = Decimal("1.00")

# A duplicate is suspected when the gap matches a single transaction to the
# cent. Anything within this of an exact match counts, to survive rounding.
MATCH_SLACK = Decimal("0.01")


async def check_account(
    db: AsyncSession, account: Account, today: date
) -> dict:
    """
    Compare an account's stated balance with the sum of what is recorded.

    Only meaningful for accounts Raven holds the whole history of. A Plaid
    account synced from a cursor may legitimately begin mid-stream, so the
    comparison is reported as "cannot tell" rather than as a discrepancy — a
    check that cries wolf on every connected account is a check nobody reads.
    """
    total = Decimal(
        await db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.account_id == account.id,
                Transaction.household_id == account.household_id,
                countable(),
            )
        )
        or 0
    )
    count = (
        await db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.account_id == account.id,
                countable(),
            )
        )
        or 0
    )
    stated = Decimal(account.current_balance or 0)

    if not account.is_manual:
        return {
            "account_id": str(account.id),
            "name": account.name,
            # Carried so the panel can tell two identically named cards apart
            # the same way every other list does.
            "owner_name": account.owner_name,
            "mask": account.mask,
            "status": "not_checkable",
            "reason": (
                "Connected accounts start from wherever the bank's feed began, "
                "so the transactions here are not the whole history and cannot "
                "be expected to add up to the balance."
            ),
            "stated_balance": str(stated),
            "transaction_total": str(total),
            "transactions": count,
        }

    if count == 0:
        return {
            "account_id": str(account.id),
            "name": account.name,
            # Carried so the panel can tell two identically named cards apart
            # the same way every other list does.
            "owner_name": account.owner_name,
            "mask": account.mask,
            "status": "empty",
            "reason": "Nothing recorded on this account yet.",
            "stated_balance": str(stated),
            "transaction_total": "0.00",
            "transactions": 0,
        }

    implied = (stated - total).quantize(Decimal("0.01"))

    result = {
        "account_id": str(account.id),
        "name": account.name,
        "owner_name": account.owner_name,
        "mask": account.mask,
        "stated_balance": str(stated),
        "transaction_total": str(total.quantize(Decimal("0.01"))),
        "implied_opening_balance": str(implied),
        "transactions": count,
    }

    if account.opening_balance is None:
        # Without an opening balance there is no right answer to compare
        # against: `stated - total` *is* the opening balance, not a fault.
        # Calling it drift would make this fire on every account forever, which
        # is the fastest way to make a warning worthless.
        result["status"] = "needs_opening_balance"
        result["reason"] = (
            f"Raven cannot tell yet. Based on what is recorded, this account "
            f"held {implied:,.2f} before the first transaction — set that as "
            "the opening balance and every future check becomes meaningful."
        )
        result["suggested_opening_balance"] = str(implied)
        return result

    difference = (implied - Decimal(account.opening_balance)).quantize(
        Decimal("0.01")
    )
    result["opening_balance"] = str(account.opening_balance)

    if abs(difference) <= TOLERANCE:
        result["status"] = "balanced"
        result["reason"] = (
            "The recorded transactions account for the balance."
        )
        return result

    # A gap that exactly matches one recorded transaction is the signature of a
    # duplicate, or of one entry that should not be there.
    # Compared on magnitude: an extra *charge* makes the balance drift the
    # opposite way from the charge's own sign, so matching the signed values
    # never fires on the case it exists to catch.
    twin = await db.scalar(
        select(Transaction.id).where(
            Transaction.account_id == account.id,
            func.abs(func.abs(Transaction.amount) - abs(difference))
            <= MATCH_SLACK,
            countable(),
        )
    )

    result["status"] = "drifted"
    result["difference"] = str(difference)
    if twin is not None:
        result["reason"] = (
            f"The balance is out by {abs(difference):,.2f}, which is exactly "
            "one of the transactions on this account. That usually means the "
            "same thing was recorded twice, or one entry does not belong."
        )
        result["likely"] = "duplicate"
    else:
        result["reason"] = (
            f"The balance is out by {abs(difference):,.2f}. Either something "
            "is missing, or the opening balance was never quite right — "
            "adjusting the account's balance will hide this rather than "
            "explain it."
        )
        result["likely"] = "missing_or_opening"
    return result


async def check_household(
    db: AsyncSession, household_id: uuid.UUID, today: date
) -> dict:
    accounts = (
        await db.scalars(
            select(Account).where(
                Account.household_id == household_id,
                Account.is_hidden.is_(False),
            )
        )
    ).all()
    checks = [await check_account(db, account, today) for account in accounts]
    drifted = [c for c in checks if c["status"] == "drifted"]
    return {
        "checked_at": today.isoformat(),
        "accounts": checks,
        "drifted": len(drifted),
        "balanced": len([c for c in checks if c["status"] == "balanced"]),
        "not_checkable": len(
            [c for c in checks if c["status"] == "not_checkable"]
        ),
        "needs_opening_balance": len(
            [c for c in checks if c["status"] == "needs_opening_balance"]
        ),
    }
