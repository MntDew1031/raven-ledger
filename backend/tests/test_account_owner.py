"""
Whose account is this?

Alex and Jordan each hold a Chase Prime and a Discover it. Four accounts, two
names between them, and Plaid cannot say which is whose — the holder name it
reports is the bank's formatting of a joint title as often as not, and absent
entirely on many institutions.

What Raven can know is who was signed in when the connection was made. These
tests pin the three properties that makes useful:

- the owner is recorded on the connection and stamped onto its accounts,
- a re-sync never overwrites an owner set by hand,
- and a sandbox copy keeps it, or the same two cards become indistinguishable
  the moment you copy them.
"""

import inspect
import pathlib


class TestTheLinkingPersonIsRecorded:
    def test_the_connection_stores_who_linked_it(self):
        from app.models import InstitutionConnection

        assert hasattr(InstitutionConnection, "linked_by_user_id")

    def test_the_endpoint_passes_the_signed_in_person(self):
        """
        Not the household — the household is both of them, which is the whole
        ambiguity this exists to resolve.
        """
        from app.api import plaid

        source = inspect.getsource(plaid.exchange)
        assert "linked_by_user_id=auth.user.id" in source

    def test_the_schema_and_the_migration_agree(self):
        """
        `database/schema.sql` bootstraps a fresh database in a single pass and
        is not generated from the migrations, so a column added to one and not
        the other is invisible until an install that never ran the migration
        hits a missing column.
        """
        root = pathlib.Path(__file__).resolve().parents[2]
        schema = (root / "database/schema.sql").read_text()
        migration = (
            root
            / "backend/migrations/versions/20260803_11_connection_owner.py"
        ).read_text()
        assert "linked_by_user_id" in schema
        assert "linked_by_user_id" in migration


class TestSyncingStampsTheOwnerButNeverReclaimsIt:
    def test_a_created_account_gets_the_linking_person(self):
        from app.services import plaid_service

        source = inspect.getsource(plaid_service.sync_connection)
        assert "owner_user_id=connection.linked_by_user_id" in source

    def test_a_later_sync_does_not_overwrite_it(self):
        """
        The stamp is a guess. A joint account linked by one person belongs to
        both, so once the account exists whose it is becomes the household's
        decision — and `on_conflict_do_update` must not put it back.
        """
        from app.services import plaid_service

        source = inspect.getsource(plaid_service.sync_connection)
        conflict = source.split("on_conflict_do_update", 1)[1]
        assert "owner_user_id" not in conflict.split("returning", 1)[0]


class TestASandboxKeepsTheOwner:
    def test_the_copy_carries_it(self):
        from app.services import sandbox

        assert "owner_user_id=account.owner_user_id" in inspect.getsource(
            sandbox.create_sandbox
        )


class TestTheOwnerIsReadableWithoutASecondRequest:
    def test_an_account_can_name_its_owner(self):
        from app.models import Account

        assert isinstance(Account.owner_name, property)

    def test_the_response_carries_it(self):
        """
        Resolved from the relationship rather than stored, so renaming
        yourself in the profile page renames you on every account at once.
        """
        from app.schemas import AccountResponse

        assert "owner_name" in AccountResponse.model_fields

    def test_the_owner_is_loaded_eagerly(self):
        """
        A lazy load here would be IO inside serialization, which async
        SQLAlchemy refuses outright — the account list would 500 rather than
        merely be slow.
        """
        from app.models import Account

        assert Account.__mapper__.relationships["owner"].lazy == "selectin"
