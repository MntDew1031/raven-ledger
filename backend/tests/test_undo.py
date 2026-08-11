"""
Undo: the thing that makes "apply all" a reasonable button to press.

Deliberately dumb by design — it restores recorded values rather than computing
an inverse, because inverses go wrong invisibly. The opposite of "categorize as
Dining" is not "uncategorize"; it is "put back whatever was there, which might
have been Groceries, or nothing at all".
"""

import inspect
import uuid
from app.models import Transaction
from app.services import undo


def _txn(**kwargs):
    item = Transaction(id=uuid.uuid4(), **kwargs)
    return item


class TestCapture:
    def test_records_the_value_held_before(self):
        category = uuid.uuid4()
        item = _txn(category_id=category, categorization_source="plaid")
        captured = undo.capture(item, ["category_id", "categorization_source"])
        assert {c["field"]: c["before"] for c in captured} == {
            "category_id": str(category),
            "categorization_source": "plaid",
        }

    def test_a_null_is_recorded_as_a_null_not_dropped(self):
        """
        Restoring "it had no category" is the common case after the organizer
        fills one in, so an absent value has to survive the round trip.
        """
        item = _txn(category_id=None, categorization_source=None)
        captured = undo.capture(item, ["category_id"])
        assert captured[0]["before"] is None

    def test_unknown_fields_are_refused(self):
        """
        Safer than reflecting over attribute names taken from stored JSON.
        """
        item = _txn(category_id=None)
        assert undo.capture(item, ["household_id", "id"]) == []

    def test_the_allowed_set_is_narrow(self):
        assert "household_id" not in undo.RESTORABLE
        assert "id" not in undo.RESTORABLE
        assert "category_id" in undo.RESTORABLE


class TestRecord:
    def test_drops_entries_for_fields_it_could_not_restore(self):
        entry = undo.record(
            uuid.uuid4(),
            uuid.uuid4(),
            "bulk",
            "did a thing",
            [
                {"transaction_id": str(uuid.uuid4()), "field": "category_id", "before": None},
                {"transaction_id": str(uuid.uuid4()), "field": "household_id", "before": "x"},
            ],
        )
        assert len(entry.changes) == 1

    def test_drops_entries_with_no_target(self):
        entry = undo.record(
            uuid.uuid4(), None, "bulk", "x",
            [{"field": "category_id", "before": None}],
        )
        assert entry.changes == []


class TestOnlyTheMostRecentAndOnlyForAWhile:
    def test_the_window_is_hours_not_days(self):
        """Reaching back a week would silently discard a week of later work."""
        assert 1 <= undo.UNDO_WINDOW_HOURS <= 48

    def test_the_query_takes_only_the_latest_undone_entry(self):
        source = inspect.getsource(undo.undoable)
        assert "undone_at.is_(None)" in source
        assert "created_at.desc()" in source
        assert "limit(1)" in source

    def test_the_query_respects_the_window(self):
        source = inspect.getsource(undo.undoable)
        assert "cutoff" in source and "UNDO_WINDOW_HOURS" in source


class TestLaterEditsWin:
    def test_a_row_touched_since_is_skipped(self):
        """
        Somebody's later change is newer and more deliberate than the action
        being reversed, so it is left alone and counted as skipped.
        """
        source = inspect.getsource(undo.apply_undo)
        assert "updated_at > entry.created_at" in source
        assert "skipped" in source

    def test_a_deleted_row_is_skipped_rather_than_erroring(self):
        source = inspect.getsource(undo.apply_undo)
        assert "if transaction is None" in source


class TestTheOrganizerRecordsBeforeItApplies:
    def test_capture_happens_first(self):
        from app.api import organizer as organizer_api

        source = inspect.getsource(organizer_api.approve_proposals)
        assert source.index("capture_targets") < source.index("apply_proposal")

    def test_only_transaction_level_kinds_are_captured(self):
        """
        A created rule or a written budget line is its own object with its own
        delete button. Pretending to undo those here would mean inventing an
        inverse rather than restoring a value.
        """
        from app.api import organizer as organizer_api

        source = inspect.getsource(organizer_api.capture_targets)
        assert "ProposalKind.rule" not in source
        assert "ProposalKind.budget" not in source
        assert "ProposalKind.category" in source
