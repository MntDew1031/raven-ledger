import json
import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import plaid
import jwt
from plaid.api import plaid_api
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.webhook_verification_key_get_request import (
    WebhookVerificationKeyGetRequest,
)
from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Account,
    AccountKind,
    AccountType,
    InstitutionConnection,
    Transaction,
)
from app.security import decrypt_secret, encrypt_secret
from app.services.net_worth import record_net_worth_snapshot

settings = get_settings()
_webhook_keys: dict[str, tuple[dict, float]] = {}


def plaid_client() -> plaid_api.PlaidApi:
    if not settings.plaid_client_id or not settings.plaid_secret:
        raise RuntimeError("Plaid credentials are not configured")
    host = (
        plaid.Environment.Sandbox
        if settings.plaid_environment == "sandbox"
        else plaid.Environment.Production
    )
    configuration = plaid.Configuration(
        host=host,
        api_key={
            "clientId": settings.plaid_client_id,
            "secret": settings.plaid_secret,
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def _link_options() -> dict:
    """
    Optional Link parameters. `redirect_uri` is what lets an OAuth institution
    return the user to Raven Ledger after they authenticate at their bank,
    which is required for OAuth banks in a mobile browser. Plaid rejects the
    request if either value is sent empty, so absent keys stay absent.
    """
    options: dict = {}
    if settings.plaid_webhook_url:
        options["webhook"] = settings.plaid_webhook_url
    if settings.plaid_redirect_uri:
        options["redirect_uri"] = settings.plaid_redirect_uri
    return options


def create_link_token(user_id: uuid.UUID) -> str:
    optional = _link_options()
    request = LinkTokenCreateRequest(
        products=[
            Products("transactions"),
        ],
        optional_products=[
            Products("investments"),
            Products("liabilities"),
        ],
        client_name="Raven Ledger",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=str(user_id)),
        **optional,
    )
    return plaid_client().link_token_create(request).to_dict()["link_token"]


def create_update_link_token(
    user_id: uuid.UUID,
    encrypted_access_token: str,
) -> str:
    optional = _link_options()
    request = LinkTokenCreateRequest(
        client_name="Raven Ledger",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=str(user_id)),
        access_token=decrypt_secret(encrypted_access_token),
        **optional,
    )
    return plaid_client().link_token_create(request).to_dict()["link_token"]


def plaid_error_details(exc: Exception) -> tuple[str, str]:
    body = getattr(exc, "body", None)
    if body:
        try:
            payload = json.loads(body)
            code = payload.get("error_code") or "PLAID_ERROR"
            message = (
                payload.get("display_message")
                or payload.get("error_message")
                or "Plaid could not complete the request"
            )
            return str(code), str(message)
        except (TypeError, ValueError):
            pass
    return "PLAID_ERROR", "Plaid could not complete the request"


def verify_webhook(payload: bytes, verification_token: str | None) -> bool:
    if not verification_token:
        return False
    try:
        header = jwt.get_unverified_header(verification_token)
        if header.get("alg") != "ES256" or not header.get("kid"):
            return False
        key_id = str(header["kid"])
        cached = _webhook_keys.get(key_id)
        if cached and cached[1] > time.time():
            key = cached[0]
        else:
            response = plaid_client().webhook_verification_key_get(
                WebhookVerificationKeyGetRequest(key_id=key_id)
            ).to_dict()
            key = response["key"]
            expired_at = key.get("expired_at")
            if expired_at is not None and float(expired_at) <= time.time():
                return False
            _webhook_keys[key_id] = (key, time.time() + 24 * 60 * 60)

        public_key = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(key))
        claims = jwt.decode(
            verification_token,
            public_key,
            algorithms=["ES256"],
            options={
                "require": ["iat", "request_body_sha256"],
                "verify_exp": False,
            },
        )
        issued_at = float(claims["iat"])
        now = time.time()
        if issued_at > now + 30 or now - issued_at > 5 * 60:
            return False
        expected_hash = str(claims["request_body_sha256"])
        actual_hash = hashlib.sha256(payload).hexdigest()
        return hmac.compare_digest(actual_hash, expected_hash)
    except (KeyError, TypeError, ValueError, jwt.PyJWTError, plaid.ApiException):
        return False


async def exchange_public_token(
    db: AsyncSession,
    household_id: uuid.UUID,
    public_token: str,
    institution_name: str | None,
    linked_by_user_id: uuid.UUID | None = None,
) -> InstitutionConnection:
    response = plaid_client().item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    ).to_dict()
    connection = InstitutionConnection(
        household_id=household_id,
        provider_item_id=response["item_id"],
        institution_name=institution_name,
        encrypted_access_token=encrypt_secret(response["access_token"]),
        linked_by_user_id=linked_by_user_id,
    )
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return connection


async def remove_connection(
    db: AsyncSession,
    connection: InstitutionConnection,
    remove_remote: bool = True,
) -> None:
    if remove_remote:
        plaid_client().item_remove(
            ItemRemoveRequest(
                access_token=decrypt_secret(connection.encrypted_access_token)
            )
        )
    accounts = (
        await db.scalars(
            select(Account).where(Account.connection_id == connection.id)
        )
    ).all()
    for account in accounts:
        account.connection_id = None
        account.provider_account_id = None
        account.is_manual = True
        account.last_synced_at = None
    await db.delete(connection)
    await db.commit()


def _account_kind(account_type: str) -> AccountKind:
    return (
        AccountKind.liability
        if account_type in {"credit", "loan"}
        else AccountKind.asset
    )


def _account_type(account_type: str, subtype: str | None) -> AccountType:
    if account_type == "depository":
        return (
            AccountType.savings
            if subtype in {"savings", "money market"}
            else AccountType.checking
        )
    if account_type == "credit":
        return AccountType.credit
    if account_type == "investment":
        return AccountType.investment
    if subtype == "mortgage":
        return AccountType.mortgage
    if account_type == "loan":
        return AccountType.debt
    return AccountType.other


def _provider_category(item: dict) -> str | None:
    """
    Plaid's own categorization, kept verbatim.

    The SDK returns `personal_finance_category` as an object on live responses
    and a plain dict on replayed ones, so both are read. The detailed code is
    preferred: `FOOD_AND_DRINK_GROCERIES` distinguishes a supermarket from a
    restaurant, while its primary does not.
    """
    raw = item.get("personal_finance_category")
    if raw is None:
        return None
    if isinstance(raw, dict):
        value = raw.get("detailed") or raw.get("primary")
    else:
        value = getattr(raw, "detailed", None) or getattr(raw, "primary", None)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:120]


def _transactions_sync_request(
    access_token: str, cursor: str | None
) -> TransactionsSyncRequest:
    """
    Build a `/transactions/sync` request.

    A newly linked institution has no cursor yet. The Plaid SDK types `cursor`
    as `str` and rejects `None` outright, so the very first sync has to omit the
    field rather than pass an empty value.
    """
    if cursor:
        return TransactionsSyncRequest(
            access_token=access_token, cursor=cursor, count=500
        )
    return TransactionsSyncRequest(access_token=access_token, count=500)


async def sync_connection(
    db: AsyncSession, connection: InstitutionConnection
) -> int:
    client = plaid_client()
    access_token = decrypt_secret(connection.encrypted_access_token)
    cursor = connection.cursor
    added: list[dict] = []
    modified: list[dict] = []
    removed: list[dict] = []
    account_payload: dict[str, dict] = {}

    account_response = client.accounts_get(
        AccountsGetRequest(access_token=access_token)
    ).to_dict()
    for account in account_response.get("accounts", []):
        account_payload[account["account_id"]] = account

    while True:
        response = client.transactions_sync(
            _transactions_sync_request(access_token, cursor)
        ).to_dict()
        for account in response.get("accounts", []):
            account_payload[account["account_id"]] = account
        added.extend(response.get("added", []))
        modified.extend(response.get("modified", []))
        removed.extend(response.get("removed", []))
        cursor = response["next_cursor"]
        if not response.get("has_more"):
            break

    account_ids: dict[str, uuid.UUID] = {}
    for provider_id, item in account_payload.items():
        kind = _account_kind(item["type"])
        raw_balance = Decimal(str(item["balances"].get("current") or 0))
        balance = -raw_balance if kind == AccountKind.liability else raw_balance
        statement = insert(Account).values(
            household_id=connection.household_id,
            connection_id=connection.id,
            provider_account_id=provider_id,
            name=item["name"],
            official_name=item.get("official_name"),
            institution_name=connection.institution_name,
            mask=item.get("mask"),
            type=_account_type(item["type"], item.get("subtype")),
            subtype=item.get("subtype"),
            kind=kind,
            is_on_budget=item["type"] in {"depository", "credit"},
            current_balance=balance,
            available_balance=item["balances"].get("available"),
            credit_limit=item["balances"].get("limit"),
            currency=item["balances"].get("iso_currency_code") or "USD",
            last_synced_at=datetime.now(timezone.utc),
            # Only on insert. Deliberately absent from the update below: once
            # an account exists, whose it is becomes the household's decision,
            # and re-syncing must not overwrite "shared" back to whoever
            # happened to link the institution.
            owner_user_id=connection.linked_by_user_id,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_accounts_household_provider",
            set_={
                "current_balance": statement.excluded.current_balance,
                "available_balance": statement.excluded.available_balance,
                "credit_limit": statement.excluded.credit_limit,
                "last_synced_at": statement.excluded.last_synced_at,
            },
        ).returning(Account.id)
        account_ids[provider_id] = (await db.execute(statement)).scalar_one()

    for item in added + modified:
        provider_account_id = item["account_id"]
        account_id = account_ids.get(provider_account_id)
        if not account_id:
            account_id = await db.scalar(
                select(Account.id).where(
                    Account.household_id == connection.household_id,
                    Account.provider_account_id == provider_account_id,
                )
            )
        if not account_id:
            continue
        # Plaid uses positive amounts for outflow. Raven uses negative outflow.
        amount = -Decimal(str(item["amount"]))
        statement = insert(Transaction).values(
            provider_category=_provider_category(item),
            household_id=connection.household_id,
            account_id=account_id,
            provider_transaction_id=item["transaction_id"],
            pending_provider_transaction_id=item.get("pending_transaction_id"),
            merchant_name=item.get("merchant_name") or item.get("name"),
            original_description=item.get("original_description") or item["name"],
            amount=amount,
            currency=item.get("iso_currency_code") or "USD",
            posted_date=item["date"],
            authorized_date=item.get("authorized_date"),
            pending=item.get("pending", False),
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_transactions_account_provider",
            set_={
                "merchant_name": statement.excluded.merchant_name,
                # Leave a corrected amount alone. Plaid's sign is not always
                # what a household means by it, and re-reverting somebody's fix
                # on every sync is worse than a stale cent.
                "amount": case(
                    (Transaction.amount_overridden.is_(True), Transaction.amount),
                    else_=statement.excluded.amount,
                ),
                "posted_date": statement.excluded.posted_date,
                "pending": statement.excluded.pending,
                # Plaid refines its guess once a pending charge posts, so the
                # later value is the better one.
                "provider_category": statement.excluded.provider_category,
            },
        )
        await db.execute(statement)

    removed_ids = [item["transaction_id"] for item in removed]
    if removed_ids:
        existing = (
            await db.scalars(
                select(Transaction).where(
                    Transaction.household_id == connection.household_id,
                    Transaction.provider_transaction_id.in_(removed_ids),
                )
            )
        ).all()
        for transaction in existing:
            await db.delete(transaction)

    connection.cursor = cursor
    connection.last_synced_at = datetime.now(timezone.utc)
    connection.status = "healthy"
    connection.error_code = None
    await db.flush()
    await record_net_worth_snapshot(db, connection.household_id)
    await db.commit()
    return len(added) + len(modified)
