import uuid
from decimal import Decimal

from app.models import RuleMatchType
from app.services.categorizer import Rule, choose_category, normalize_merchant


def test_normalize_merchant_removes_noise():
    assert normalize_merchant("COSTCO WHSE #1043") == "costco whse"
    assert normalize_merchant("LYFT   *RIDE THU") == "lyft ride thu"


def test_order_references_collapse_to_one_merchant():
    """
    Regression: Amazon puts a per-order reference in the descriptor, so every
    single charge normalized to its own merchant. That meant a merchant
    decision never applied to the next charge and the model was re-asked
    forever — the exact thing merchant memory exists to stop.
    """
    keys = {
        normalize_merchant(value)
        for value in (
            "AMZN Mktp US*2K4L9",
            "AMZN Mktp US*9XQ22",
            "AMZN Mktp US*7BB01",
        )
    }
    assert keys == {"amzn mktp us"}


def test_store_numbers_collapse_to_one_merchant():
    keys = {
        normalize_merchant(value)
        for value in ("TRADER JOE'S #219", "TRADER JOE'S #402")
    }
    assert keys == {"trader joe s"}


def test_real_names_containing_digits_survive():
    # A number that starts the name is part of it; one that follows the name is
    # a store number. That distinction is what keeps 7-Eleven and 5 Guys intact
    # while still collapsing "TRADER JOE'S #219".
    assert normalize_merchant("1PASSWORD SUBSCRIPTION") == "1password subscription"
    assert normalize_merchant("7-ELEVEN 22461") == "7 eleven"
    assert normalize_merchant("5 GUYS BURGERS 88") == "5 guys burgers"


def test_a_descriptor_that_is_only_a_reference_still_keys_on_something():
    # Stripping everything would collapse unrelated merchants into one blank
    # key, which is worse than keeping the reference.
    assert normalize_merchant("4H2K9") == "4h2k9"


def test_household_rule_wins_before_keyword_model():
    dining = uuid.uuid4()
    grocery = uuid.uuid4()
    result = choose_category(
        "Costco Food Court",
        Decimal("-18.42"),
        [
            Rule(
                category_id=dining,
                match_type=RuleMatchType.contains,
                pattern="costco food court",
            )
        ],
        {"food & household": grocery},
    )
    assert result == (dining, "household_rule")


def test_keyword_fallback_handles_grocery():
    grocery = uuid.uuid4()
    category_id, source = choose_category(
        "Whole Foods Market",
        Decimal("-92.18"),
        [],
        {"food & household": grocery},
    )
    assert category_id == grocery
    assert source == "keyword_model"


def test_rule_pattern_validation_rejects_bad_regex():
    import pytest
    from fastapi import HTTPException

    from app.api.rules import _validate_pattern
    from app.models import RuleMatchType

    _validate_pattern(RuleMatchType.regex, r"^AMZN.*")
    _validate_pattern(RuleMatchType.contains, "(unclosed")  # not a regex: fine

    with pytest.raises(HTTPException) as failure:
        _validate_pattern(RuleMatchType.regex, "(unclosed")
    assert failure.value.status_code == 422


def test_rule_matching_semantics():
    import uuid
    from decimal import Decimal

    from app.models import RuleMatchType
    from app.services.categorizer import Rule, normalize_merchant, rule_matches

    def rule(match_type, pattern, **bounds):
        return Rule(
            category_id=uuid.uuid4(),
            match_type=match_type,
            pattern=pattern,
            **bounds,
        )

    merchant = normalize_merchant("CHIPOTLE #1234 ONLINE")
    assert rule_matches(rule(RuleMatchType.contains, "chipotle"), merchant, Decimal("-12"))
    assert rule_matches(rule(RuleMatchType.exact, "Chipotle Online"), normalize_merchant("CHIPOTLE ONLINE"), Decimal("-12"))
    assert rule_matches(rule(RuleMatchType.regex, r"chipotle|qdoba"), merchant, Decimal("-12"))
    # Amount bounds compare absolute values.
    assert not rule_matches(
        rule(RuleMatchType.contains, "chipotle", min_amount=Decimal("50")),
        merchant,
        Decimal("-12"),
    )
    assert rule_matches(
        rule(RuleMatchType.contains, "chipotle", max_amount=Decimal("50")),
        merchant,
        Decimal("-12"),
    )


def test_pathological_regex_times_out_instead_of_blocking():
    import uuid
    from decimal import Decimal

    from app.models import RuleMatchType
    from app.services.categorizer import Rule, rule_matches

    pathological = Rule(
        category_id=uuid.uuid4(),
        match_type=RuleMatchType.regex,
        pattern=r"^(a+)+$",
    )
    assert not rule_matches(pathological, "a" * 500 + "!", Decimal("-1"))


def test_a_rule_outranks_a_guess_but_never_a_person():
    """
    Regression: creating "always categorize Southwest like this" appeared to do
    nothing. `categorize_uncategorized` only ever looked at rows whose category
    was NULL, so every Southwest charge the AI or the keyword table had already
    labelled kept the wrong category and the rule looked broken.

    A rule is an explicit human instruction and must beat a guess. A category a
    person chose by hand, or that came from splitting, must still win.
    """
    from app.services.categorizer import HUMAN_SOURCES

    for guess in ("ai", "keyword_model", "provider_category", "merchant_memory"):
        assert guess not in HUMAN_SOURCES, f"{guess} must be overridable by a rule"
    for chosen in ("manual", "split"):
        assert chosen in HUMAN_SOURCES, f"{chosen} must survive a rule run"


class TestTheCodeActuallyRuns:
    """
    1.53.0 added a liability-account lookup to `categorize_uncategorized` and
    never imported `Account`. Every call raised `NameError` inside the worker,
    so **all** deterministic categorization was dead: rules, merchant memory,
    Plaid's own category, and the transfer flag that keeps a savings transfer
    out of income. Nothing said so — the job failed in a container nobody
    watches, and the endpoint that queues it had already returned 202.

    The test that was supposed to cover it asserted
    `"liability_accounts" in inspect.getsource(...)`. A string is present in
    source whether or not the module can execute, so it passed for four
    releases. That is the lesson: a test that reads source proves the code was
    written, never that it works.

    `ruff --select F` is the check that would have caught it, in milliseconds,
    the moment it was typed. It stays in the suite so the next one is caught
    the same way.
    """

    def test_no_undefined_names_anywhere_in_the_app(self):
        import subprocess
        import sys
        from pathlib import Path

        app = Path(__file__).resolve().parent.parent / "app"
        result = subprocess.run(
            [
                sys.executable, "-m", "ruff", "check",
                "--select", "F", "--no-cache",
                "--output-format", "concise", str(app),
            ],
            capture_output=True,
            text=True,
        )
        if "No module named" in result.stderr:
            raise AssertionError(
                "ruff is not installed — run "
                "`pip install -r requirements-dev.txt`. This check is not "
                "optional: it is the one that catches a NameError before it "
                "reaches the worker."
            )
        assert result.returncode == 0, result.stdout or result.stderr
