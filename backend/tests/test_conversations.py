"""
Conversations that survive a refresh, and memories that must be agreed to.

The assistant used to keep its messages in the browser: reloading threw the
conversation away, and every chat started knowing nothing.
"""

import inspect

import pytest

from app.services import conversations
from app.services.assistant import split_suggested_memory


class TestThreadTitles:
    def test_uses_the_question(self):
        assert conversations.title_from("What did I spend on food?") == (
            "What did I spend on food?"
        )

    def test_collapses_whitespace(self):
        assert conversations.title_from("  how   much\nis left ") == (
            "how much is left"
        )

    def test_long_questions_are_cut_at_a_word(self):
        question = "why " * 60
        title = conversations.title_from(question)
        assert len(title) <= conversations.TITLE_MAX + 1
        assert "wh…" not in title  # never mid-word

    def test_empty_falls_back(self):
        assert conversations.title_from("   ") == "New conversation"


class TestSuggestedMemories:
    """
    The model may propose a memory. It is parsed out of the reply so the marker
    never reaches the reader, and it arrives as a suggestion — a misheard
    sentence must not quietly become something Raven believes about your money.
    """

    def test_marker_is_stripped_from_the_reply(self):
        text, fact = split_suggested_memory(
            "You spent $40 at Costco.\nREMEMBER: Costco trips are groceries."
        )
        assert "REMEMBER" not in text
        assert text == "You spent $40 at Costco."
        assert fact == "Costco trips are groceries."

    def test_no_marker_means_no_suggestion(self):
        text, fact = split_suggested_memory("Just an answer.")
        assert text == "Just an answer."
        assert fact is None

    @pytest.mark.parametrize("quoted", ['"a fact"', "'a fact'", "- a fact"])
    def test_surrounding_punctuation_is_trimmed(self, quoted):
        _, fact = split_suggested_memory(f"Answer.\nREMEMBER: {quoted}")
        assert fact == "a fact"

    def test_a_lone_marker_yields_nothing(self):
        text, fact = split_suggested_memory("Answer.\nREMEMBER:")
        assert fact is None
        assert text == "Answer."


class TestOnlyConfirmedMemoriesReachTheModel:
    def test_the_query_requires_confirmation(self):
        source = inspect.getsource(conversations.active_memories)
        assert "confirmed_at.is_not(None)" in source
        assert "is_active.is_(True)" in source

    def test_rendering_is_empty_without_memories(self):
        assert conversations.render_memories([]) == ""

    def test_context_is_bounded(self):
        """A long conversation must not crowd out the ledger snapshot."""
        assert conversations.MAX_CONTEXT_MESSAGES <= 24
        assert conversations.MAX_MEMORIES_IN_CONTEXT <= 60


class TestMemoriesLiveInRavensDatabase:
    """
    Alex asked whether mem0 would conflict. It would not, but financial facts
    belong beside the financial data: here they inherit the nightly dump that
    proves itself by restoring, the household scoping, and the encryption key.
    They are read out through the existing API keys instead.
    """

    def test_the_module_does_not_reach_for_an_external_service(self):
        # The docstring names mem0 precisely to explain why it is not used, so
        # check the imports rather than the prose.
        import ast

        tree = ast.parse(inspect.getsource(conversations))
        imported = {
            name.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for name in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        for foreign in ("mem0", "httpx", "requests", "openai"):
            assert foreign not in imported

    def test_memories_are_household_scoped(self):
        source = inspect.getsource(conversations.active_memories)
        assert "household_id" in source


class TestReasoningModelsDoNotLeakTheirScratchpad:
    """
    Alex's node runs Qwen3.6, which thinks aloud before answering. His first
    real conversation came back beginning "<think> Here's a thinking process:
    1. **Analyze User Input:**" — not an answer to a question about money.
    Caught by talking to the live model, not by reading the code.
    """

    def test_a_closed_block_is_removed(self):
        from app.services.ai import strip_reasoning

        assert (
            strip_reasoning("<think>step one\nstep two</think>\n\nYou spent $40.")
            == "You spent $40."
        )

    def test_an_unclosed_block_is_removed(self):
        """A generation cut short by max_tokens never closes the tag."""
        from app.services.ai import strip_reasoning

        assert strip_reasoning("<think>cut off mid-thought") == ""

    @pytest.mark.parametrize("tag", ["think", "thinking", "reasoning"])
    def test_the_common_spellings(self, tag):
        from app.services.ai import strip_reasoning

        assert strip_reasoning(f"<{tag}>x</{tag}>Answer") == "Answer"

    def test_ordinary_text_is_untouched(self):
        from app.services.ai import strip_reasoning

        assert strip_reasoning("You spent $40 at Costco.") == (
            "You spent $40 at Costco."
        )

    def test_it_is_applied_where_replies_are_read(self):
        import inspect

        from app.services import ai

        assert "strip_reasoning(" in inspect.getsource(ai._complete)


class TestTheModelIsChosenNotHardcoded:
    """
    Changing the model meant editing a manifest and restarting two
    deployments, which is a poor fit for something you want to try three of in
    an evening. The batch size moves with it because the right value depends
    entirely on the model.
    """

    def test_only_the_intended_settings_are_writable(self):
        """
        An allowlist, so a new setting has to be considered before it becomes
        reachable rather than becoming reachable the moment someone adds a key.
        """
        from app.services.runtime_settings import AI_MIN_BATCH, AI_MODEL, WRITABLE

        assert WRITABLE == {AI_MODEL, AI_MIN_BATCH}

    def test_the_endpoint_is_not_writable(self):
        """
        A model name is a choice between what the server already offers. An
        endpoint is where the household's financial data gets sent, and a text
        box that redirects it is an exfiltration path with a save button.
        """
        from app.services.runtime_settings import WRITABLE

        for forbidden in ("llm_base_url", "ai.endpoint", "endpoint", "ai.api_key"):
            assert forbidden not in WRITABLE

    def test_writing_an_unknown_key_is_refused(self):
        import asyncio

        from app.services.runtime_settings import put

        async def attempt():
            await put(None, "ai.endpoint", "http://evil.example", None)

        try:
            asyncio.run(attempt())
        except ValueError:
            return
        raise AssertionError("an unlisted setting was accepted")

    def test_changing_it_is_operator_only(self):
        """
        The model is one choice for the whole install, so it is gated on the
        deployment's operator list rather than a household role.

        Matched on the call, not on its arguments: the guard now takes what it
        is refusing so the message can name it, and a test pinned to
        `_require_operator(auth)` exactly would fail on that alone.
        """
        import inspect

        from app.api import system

        assert "_require_operator(auth" in inspect.getsource(
            system.write_ai_config
        )

    def test_a_refusal_names_what_it_refused(self):
        """
        Answering "instance-wide backups are managed by the server operator"
        to somebody who just picked a model describes a feature they were not
        using, so the real reason never reaches them. That is exactly how a
        model choice that was being refused read as a picker doing nothing.
        """
        import types

        import pytest
        from fastapi import HTTPException

        from app.api.system import _require_operator

        nobody = types.SimpleNamespace(
            user=types.SimpleNamespace(email="member@example.com"),
            via_api_key=False,
        )
        with pytest.raises(HTTPException) as refused:
            _require_operator(nobody, doing="AI settings")
        assert "AI settings" in refused.value.detail
        # And it says how to allow it, rather than leaving a dead end.
        assert "OPERATOR_EMAILS" in refused.value.detail

    def test_reading_it_is_not(self):
        """"Which model answered that" is a fair question for anyone signed in."""
        import inspect

        assert "_require_operator" not in inspect.getsource(
            __import__("app.api.system", fromlist=["x"]).read_ai_config
        )

    def test_a_stored_batch_size_out_of_range_degrades_rather_than_breaks(self):
        import inspect

        from app.services import runtime_settings

        source = inspect.getsource(runtime_settings.effective_min_batch)
        assert "max(" in source and "min(" in source


class TestRuntimeSettingsAreSharedAcrossProcesses:
    """
    The backend saves the model while the worker categorizes. A process-local
    cache cannot be invalidated across that boundary, so it made the worker
    keep using the previous model until its container restarted.
    """

    def test_a_later_read_observes_a_change_made_by_another_process(self):
        import asyncio

        from app.services import runtime_settings

        class SharedSetting:
            value = None

            async def get(self, _model, _key):
                return self.value

        async def check():
            db = SharedSetting()
            first = await runtime_settings.get(db, "ai.model", "llama3.2")
            db.value = type("Row", (), {"value": {"value": "qwen"}})()
            second = await runtime_settings.get(db, "ai.model", None)
            return first, second

        first, second = asyncio.run(check())
        assert first == "llama3.2"
        assert second == "qwen"

    def test_the_process_local_cache_is_gone(self):
        from app.services import runtime_settings

        assert not hasattr(runtime_settings, "_cache")

    def test_the_page_can_still_tell_where_a_value_came_from(self):
        import inspect

        from app.services import runtime_settings

        source = inspect.getsource(runtime_settings.snapshot)
        assert '"chosen here" if stored_model else "deployment"' in source


class TestTheEndpointIsNotHandedOutWithTheModel:
    """
    Audit finding: `/system/ai/config` returned the LLM endpoint URL to any
    authenticated caller, including a read-only API key. That is an address on
    the household's own LAN, and a token given to Open WebUI has no business
    learning the shape of the network it sits in.
    """

    def test_the_snapshot_hides_it_by_default(self):
        import inspect

        from app.services import runtime_settings

        source = inspect.getsource(runtime_settings.snapshot)
        assert "reveal_endpoint: bool = False" in source
        assert "if reveal_endpoint else None" in source

    def test_whether_one_is_configured_is_still_reported(self):
        """Hiding the address should not hide that the feature works."""
        import inspect

        from app.services import runtime_settings

        assert "endpoint_configured" in inspect.getsource(runtime_settings.snapshot)

    def test_only_operators_see_it(self):
        import inspect

        from app.api import system

        source = inspect.getsource(system.read_ai_config)
        assert "_is_operator_context(auth)" in source
        assert "reveal_endpoint=operator" in source


class TestASandboxIsAFullCopy:
    """
    Audit finding: `create_sandbox` predates income sources and goals and never
    learned about them, so a copied ledger opened with no expected income and a
    blank forecast — the things a what-if is actually about.
    """

    def test_income_sources_are_copied(self):
        import inspect

        from app.services import sandbox

        assert "IncomeSource(" in inspect.getsource(sandbox.create_sandbox)

    def test_goals_are_copied(self):
        import inspect

        from app.services import sandbox

        assert "Goal(" in inspect.getsource(sandbox.create_sandbox)

    def test_a_copied_goal_drops_its_account_link(self):
        """
        The account belongs to the real ledger; carrying the id would make a
        sandbox read a live balance.
        """
        import inspect

        source = inspect.getsource(
            __import__("app.services.sandbox", fromlist=["x"]).create_sandbox
        )
        assert "account_id=None" in source
