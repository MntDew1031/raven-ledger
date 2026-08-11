import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Date, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Category, CategoryGroup, Transaction
from app.security import AuthContext, current_auth
from app.services.spending_scope import (
    is_income,
    is_spending,
    liability_account_ids,
    switched_off_category_ids,
    budget_month_of,
)
from app.services.splits import countable

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/cash-flow")
async def cash_flow(
    start: date,
    end: date,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    # Income and spending are each summed under the *shared* predicate rather
    # than by sign. Written out by hand here, this chart disagreed with the
    # dashboard about the same month in two ways at once: a $38.50 fuel refund
    # filed under Transportation was counted as income, and a $250 payroll
    # reversal — negative, in an income category — was counted as spending. It
    # is the same mistake `spending_scope` was created to end, surviving in the
    # one report nobody re-read.
    month = func.date_trunc("month", Transaction.posted_date)
    rows = await db.execute(
        select(
            month.label("month"),
            func.coalesce(
                func.sum(
                    case(
                        (is_income(auth.household_id), Transaction.amount),
                        else_=0,
                    )
                ),
                0,
            ).label("income"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            is_spending(auth.household_id),
                            func.abs(Transaction.amount),
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("spending"),
        )
        .where(
            Transaction.household_id == auth.household_id,
            Transaction.posted_date >= start,
            Transaction.posted_date <= end,
        )
        .group_by(month)
        .order_by(month)
    )
    return [dict(row._mapping) for row in rows]


@router.get("/spending")
async def spending_by_category(
    start: date,
    end: date,
    use_budget_month: bool = False,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Spending by category between two dates.

    `use_budget_month` is **off by default and only the budget page turns it
    on.** With it off this asks what it has always asked: what was spent in
    these dates. With it on it asks a different question — which month's plan
    does this count against — so a rent charge posting on 1 August but paid
    from July's pay lands in July.

    A new parameter rather than a change in behaviour, so that every other
    caller of this endpoint keeps the answer it already had. Reports are
    history; only the budget is a plan.
    """
    if use_budget_month:
        # Compare month to month: the caller passes a first-and-last-day range,
        # and an assigned `budget_month` is stored as a month start.
        # `Category` is passed so a category's standing offset applies — the
        # join below is already there, so this costs nothing.
        effective = budget_month_of(category=Category)
        window = and_(
            effective >= func.date_trunc("month", cast(start, Date)),
            effective <= func.date_trunc("month", cast(end, Date)),
        )
    else:
        window = and_(
            Transaction.posted_date >= start,
            Transaction.posted_date <= end,
        )
    rows = await db.execute(
        select(
            Category.name,
            Category.color,
            func.sum(func.abs(Transaction.amount)).label("amount"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .where(
            Transaction.household_id == auth.household_id,
            window,
            is_spending(auth.household_id),
        )
        .group_by(Category.id)
        .order_by(func.sum(func.abs(Transaction.amount)).desc())
    )
    return [dict(row._mapping) for row in rows]


@router.get("/trends")
async def category_trends(
    start: date,
    end: date,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    period_days = (end - start).days + 1
    previous_start = start - timedelta(days=period_days)
    previous_end = start - timedelta(days=1)
    rows = await db.execute(
        select(
            Category.name,
            func.sum(
                case(
                    (
                        (Transaction.posted_date >= start)
                        & (Transaction.posted_date <= end),
                        func.abs(Transaction.amount),
                    ),
                    else_=0,
                )
            ).label("current"),
            func.sum(
                case(
                    (
                        (Transaction.posted_date >= previous_start)
                        & (Transaction.posted_date <= previous_end),
                        func.abs(Transaction.amount),
                    ),
                    else_=0,
                )
            ).label("previous"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .where(
            Transaction.household_id == auth.household_id,
            Transaction.posted_date >= previous_start,
            Transaction.posted_date <= end,
            is_spending(auth.household_id),
        )
        .group_by(Category.id)
    )
    result = []
    for name, current, previous in rows:
        current_value = Decimal(current or 0)
        previous_value = Decimal(previous or 0)
        change = (
            ((current_value - previous_value) / previous_value) * 100
            if previous_value
            else None
        )
        result.append(
            {
                "name": name,
                "current": current_value,
                "previous": previous_value,
                "change_percent": change,
            }
        )
    return sorted(result, key=lambda item: abs(item["change_percent"] or 0), reverse=True)


@router.get("/anomalies")
async def spending_anomalies(
    start: date,
    end: date,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    history_start = start - timedelta(days=120)
    transactions = (
        await db.scalars(
            select(Transaction)
            .where(
                Transaction.household_id == auth.household_id,
                Transaction.posted_date >= history_start,
                Transaction.posted_date <= end,
                is_spending(auth.household_id),
            )
            .order_by(Transaction.posted_date.asc())
        )
    ).all()
    prior: dict[str, list[Decimal]] = defaultdict(list)
    current = []
    for transaction in transactions:
        key = (
            transaction.normalized_merchant
            or transaction.merchant_name
            or transaction.original_description
        ).lower()
        if transaction.posted_date < start:
            prior[key].append(abs(transaction.amount))
        else:
            current.append((transaction, key))

    anomalies = []
    duplicate_dates: dict[tuple[str, Decimal], date] = {}
    for transaction, key in current:
        amount = abs(transaction.amount)
        history = prior.get(key, [])
        if len(history) >= 2:
            average = sum(history, Decimal("0")) / len(history)
            if average and amount >= average * Decimal("1.5") and amount - average >= 20:
                anomalies.append(
                    {
                        "type": "amount_spike",
                        "transaction_id": transaction.id,
                        "merchant": transaction.merchant_name
                        or transaction.original_description,
                        "amount": amount,
                        "message": (
                            f"{round((amount / average - 1) * 100)}% above "
                            f"the recent average of ${average:.2f}"
                        ),
                    }
                )
        duplicate_key = (key, amount)
        previous_duplicate_date = duplicate_dates.get(duplicate_key)
        if (
            previous_duplicate_date
            and (transaction.posted_date - previous_duplicate_date).days <= 2
        ):
            anomalies.append(
                {
                    "type": "possible_duplicate",
                    "transaction_id": transaction.id,
                    "merchant": transaction.merchant_name
                    or transaction.original_description,
                    "amount": amount,
                    "message": "Possible duplicate amount and merchant this period",
                }
            )
        duplicate_dates[duplicate_key] = transaction.posted_date
    return anomalies[:10]


@router.get("/cash-flow-sankey")
async def cash_flow_sankey(
    start: date,
    end: date,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Where a month's money came from and where it went, as a flow.

    Returns nodes and links already in the index form the chart library wants,
    so the browser does no reshaping — the arithmetic that has to agree with the
    rest of the app stays on this side of the wire.

    The shape mirrors how people describe it out loud: each income category
    feeds one "Income" hub, the hub feeds each spending group, each group feeds
    its own categories, and whatever is left over becomes a savings branch.

    Carries the same guards as every other money query here: split parents are
    excluded so their lines are not counted twice, and transfers and
    budget-excluded rows never appear — moving money between your own accounts
    is not income and not spending.
    """
    base = (
        Transaction.household_id == auth.household_id,
        Transaction.posted_date >= start,
        Transaction.posted_date <= end,
        Transaction.excluded_from_budget.is_(False),
        Transaction.is_transfer.is_(False),
        countable(),
        # A category switched off wholesale should not appear on the diagram
        # either — the whole point of excluding it is that it is not your money
        # moving.
        or_(
            Transaction.category_id.is_(None),
            Transaction.category_id.not_in(
                switched_off_category_ids(auth.household_id)
            ),
        ),
    )

    rows = (
        await db.execute(
            select(
                CategoryGroup.name.label("group_name"),
                CategoryGroup.is_income.label("is_income"),
                Category.name.label("category_name"),
                Category.color.label("color"),
                # Sign matters here in a way abs() destroyed. Grouped by
                # is_income and summed as magnitudes, a -$250 payroll reversal
                # sitting in an income category was *added to income* — the
                # diagram showed $250 arriving that had in fact left. Each side
                # now counts only the direction it is about, and a category
                # whose flows all cancel drops out below.
                func.sum(
                    case(
                        (
                            CategoryGroup.is_income.is_(True),
                            case(
                                (Transaction.amount > 0, Transaction.amount),
                                else_=0,
                            ),
                        ),
                        else_=case(
                            (
                                Transaction.amount < 0,
                                func.abs(Transaction.amount),
                            ),
                            else_=0,
                        ),
                    )
                ).label("amount"),
            )
            .join(Category, Category.id == Transaction.category_id)
            .join(CategoryGroup, CategoryGroup.id == Category.group_id)
            .where(*base)
            .group_by(
                CategoryGroup.name,
                CategoryGroup.is_income,
                Category.name,
                Category.color,
            )
            # A category whose flows cancel out contributes nothing; with the
            # sign handling above it now sums to exactly zero rather than to
            # some magnitude, and a zero-width band is just a stray label.
            .having(
                func.sum(
                    case(
                        (
                            CategoryGroup.is_income.is_(True),
                            case(
                                (Transaction.amount > 0, Transaction.amount),
                                else_=0,
                            ),
                        ),
                        else_=case(
                            (
                                Transaction.amount < 0,
                                func.abs(Transaction.amount),
                            ),
                            else_=0,
                        ),
                    )
                )
                > 0
            )
        )
    ).all()

    # Uncategorized money still happened. Leaving it out would make the diagram
    # disagree with the totals on the same screen, which is worse than an
    # unflattering "Uncategorized" branch.
    uncategorized = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    case((Transaction.amount > 0, Transaction.amount), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.amount < 0, func.abs(Transaction.amount)),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(
            *base,
            Transaction.category_id.is_(None),
            or_(
                Transaction.amount < 0,
                Transaction.account_id.not_in(
                    liability_account_ids(auth.household_id)
                ),
            ),
        )
    )
    loose_income, loose_spending = uncategorized.one()

    nodes: list[dict] = []
    links: list[dict] = []
    # Keyed by (kind, name), not name alone. A household whose income category
    # is literally called "Income" collided with the hub, and the diagram drew
    # a link from the hub to itself — which also doubled everything leaving it.
    # Display names may repeat; the chart identifies nodes by index.
    index: dict[tuple[str, str], int] = {}

    def node(name: str, kind: str, color: str | None = None) -> int:
        key = (kind, name)
        if key not in index:
            index[key] = len(nodes)
            nodes.append({"name": name, "kind": kind, "color": color})
        return index[key]

    income_rows = [row for row in rows if row.is_income]
    expense_rows = [row for row in rows if not row.is_income]

    total_income = sum(Decimal(row.amount) for row in income_rows) + Decimal(
        loose_income
    )
    total_expenses = sum(Decimal(row.amount) for row in expense_rows) + Decimal(
        loose_spending
    )

    # Nothing to draw. Say so plainly rather than returning an empty diagram
    # that looks like a rendering failure.
    if total_income <= 0 and total_expenses <= 0:
        return {
            "total_income": "0.00",
            "total_expenses": "0.00",
            "net_income": "0.00",
            "savings_rate": 0.0,
            "nodes": [],
            "links": [],
        }

    hub = node("Total income", "hub")

    for row in income_rows:
        links.append(
            {
                "source": node(row.category_name, "income", row.color),
                "target": hub,
                "value": float(row.amount),
            }
        )
    if Decimal(loose_income) > 0:
        links.append(
            {
                "source": node("Uncategorized income", "income"),
                "target": hub,
                "value": float(loose_income),
            }
        )

    grouped: dict[str, list] = {}
    for row in expense_rows:
        grouped.setdefault(row.group_name, []).append(row)

    for group_name, members in grouped.items():
        group_total = sum(Decimal(row.amount) for row in members)
        group_node = node(group_name, "group")
        links.append(
            {"source": hub, "target": group_node, "value": float(group_total)}
        )
        for row in members:
            links.append(
                {
                    "source": group_node,
                    "target": node(row.category_name, "category", row.color),
                    "value": float(row.amount),
                }
            )

    if Decimal(loose_spending) > 0:
        links.append(
            {
                "source": hub,
                "target": node("Uncategorized spending", "group"),
                "value": float(loose_spending),
            }
        )

    net = total_income - total_expenses
    if net > 0:
        links.append(
            {"source": hub, "target": node("Savings", "savings"), "value": float(net)}
        )

    return {
        "total_income": f"{total_income:.2f}",
        "total_expenses": f"{total_expenses:.2f}",
        "net_income": f"{net:.2f}",
        # Share of what came in that was not spent. Negative when a month spent
        # more than it earned, which is a real answer and should not be hidden.
        "savings_rate": float(
            round(net / total_income * 100, 1) if total_income > 0 else 0
        ),
        "nodes": nodes,
        "links": links,
    }


@router.get("/by-person")
async def spending_by_person(
    start: date,
    end: date,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Spending attributed to each member, with a shared bucket.

    Useful once more than one person is in the household; before that it is a
    single row saying "Shared", which is correct and uninteresting.
    """
    from app.services.attribution import by_person

    return await by_person(db, auth.household_id, start, end)


@router.get("/category/{category_id}")
async def category_detail(
    category_id: uuid.UUID,
    months: int = Query(default=6, ge=2, le=24),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Why is this category's number what it is.

    Until now the only way to answer that was to go and filter the transaction
    list by hand. Three things answer it between them: the month-by-month
    shape, which merchants make it up, and the largest individual charges —
    a category is usually either a habit or one big thing, and the two call for
    different responses.
    """
    from datetime import date as _date

    from app.services.spending_scope import is_spending

    category = await db.get(Category, category_id)
    if category is None or category.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such category")

    today = _date.today()
    start = (today.replace(day=1) - timedelta(days=months * 31)).replace(day=1)
    scope = (
        Transaction.household_id == auth.household_id,
        Transaction.category_id == category_id,
        Transaction.posted_date >= start,
        is_spending(auth.household_id),
    )

    month = func.date_trunc("month", Transaction.posted_date)
    trend = (
        await db.execute(
            select(month.label("month"), func.sum(func.abs(Transaction.amount)))
            .where(*scope)
            .group_by(month)
            .order_by(month)
        )
    ).all()

    merchants = (
        await db.execute(
            select(
                func.coalesce(
                    Transaction.merchant_name, Transaction.original_description
                ).label("merchant"),
                func.sum(func.abs(Transaction.amount)).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .where(*scope)
            .group_by("merchant")
            .order_by(func.sum(func.abs(Transaction.amount)).desc())
            .limit(8)
        )
    ).all()

    largest = (
        await db.scalars(
            select(Transaction)
            .where(*scope)
            .order_by(func.abs(Transaction.amount).desc())
            .limit(5)
        )
    ).all()

    values = [Decimal(row[1] or 0) for row in trend]
    typical = sorted(values)[len(values) // 2] if values else Decimal("0")

    return {
        "id": str(category.id),
        "name": category.name,
        "color": category.color,
        "months": [
            {"month": row[0].date().isoformat(), "amount": str(row[1] or 0)}
            for row in trend
        ],
        # The median, not the mean: one holiday should not become "typical".
        "typical_month": str(typical),
        "merchants": [
            {
                "merchant": row[0] or "Unknown",
                "total": str(row[1]),
                "count": row[2],
            }
            for row in merchants
        ],
        "largest": [
            {
                "id": str(item.id),
                "merchant": item.merchant_name or item.original_description,
                "amount": str(item.amount),
                "posted_date": item.posted_date.isoformat(),
            }
            for item in largest
        ],
    }
