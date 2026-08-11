import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountKind, NetWorthSnapshot


async def record_net_worth_snapshot(
    db: AsyncSession,
    household_id: uuid.UUID,
    snapshot_date: date | None = None,
) -> None:
    totals = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Account.kind == AccountKind.asset, Account.current_balance),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Account.kind == AccountKind.liability,
                            func.abs(Account.current_balance),
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(
            Account.household_id == household_id,
            Account.is_hidden.is_(False),
        )
    )
    assets, liabilities = (Decimal(value) for value in totals.one())
    statement = insert(NetWorthSnapshot).values(
        household_id=household_id,
        snapshot_date=snapshot_date or date.today(),
        assets=assets,
        liabilities=liabilities,
        net_worth=assets - liabilities,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[
            NetWorthSnapshot.household_id,
            NetWorthSnapshot.snapshot_date,
        ],
        set_={
            "assets": statement.excluded.assets,
            "liabilities": statement.excluded.liabilities,
            "net_worth": statement.excluded.net_worth,
        },
    )
    await db.execute(statement)
