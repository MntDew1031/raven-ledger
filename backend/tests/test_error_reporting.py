"""
A failure nobody anticipated has to be reportable.

Alex hit `Internal Server Error` on the assistant three separate times. Each
round of diagnosis started from nothing, because FastAPI's default gives the
same six words for a missing column, a Redis outage and a typo — and none of it
reproduced against a stub, since the cause was in his data or environment
rather than in a path a fixture can reach.

Ruled out by reproduction before this was written: reasoning-model reply shapes
(think-only, null content, no choices) and seven malformed `PROPOSE:` payloads.
All returned 200. The cause is somewhere a stub cannot go, so the application
has to say what it was.
"""

import asyncio
import json


class _Request:
    method = "POST"

    class url:
        path = "/api/v1/assistant/ask"


def _call(exc: Exception):
    from app.main import unhandled_exception

    response = asyncio.run(unhandled_exception(_Request(), exc))
    return response, json.loads(response.body.decode())


class TestAnUnhandledFailureNamesItself:
    def test_it_is_still_a_five_hundred(self):
        response, _ = _call(RuntimeError("boom"))
        assert response.status_code == 500

    def test_it_names_the_exception_type(self):
        """
        "Internal Server Error" is true of every failure and useful for none.
        The type alone turns a blank report into a starting point.
        """
        _, body = _call(KeyError("category_id"))
        assert "KeyError" in body["detail"]

    def test_it_carries_a_reference_that_is_in_the_log(self):
        """
        He reads the reference off the screen; the traceback is findable by it
        without asking him to reproduce anything.
        """
        import re

        _, body = _call(ValueError("bad"))
        assert re.search(r"Reference [0-9a-f]{8}", body["detail"])

    def test_it_does_not_leak_the_exception_text(self):
        """
        Exception messages routinely carry row values, and this is a
        household's financial data. The type and a reference are enough to
        start from; the detail belongs in the log.
        """
        _, body = _call(ValueError("merchant='TRADER JOES' amount=-412.55"))
        assert "TRADER JOES" not in body["detail"]
        assert "412.55" not in body["detail"]

    def test_two_failures_get_different_references(self):
        _, first = _call(RuntimeError("a"))
        _, second = _call(RuntimeError("b"))
        assert first["detail"] != second["detail"]
