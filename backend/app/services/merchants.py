"""
Merchant text normalization.

Its own module because several services need it and they need each other:
memory looks merchants up, the categorizer writes them, rules match on them.
Keeping the one pure function they share down here means none of them has to
import another.
"""

import re

# Tokens that mix letters and at least two digits are reference numbers, not
# names: "2k4l9" and "9xq22" are two Amazon orders at one shop, and treating
# them as two merchants meant the same question was asked over and over.
# Requiring two digits keeps real names — "1password", "7eleven" — intact.
_REFERENCE_TOKEN = re.compile(r"^(?=.*[a-z])(?=(?:\D*\d){2,})[a-z0-9]{4,}$")


def normalize_merchant(value: str) -> str:
    """
    Reduce a bank descriptor to something stable enough to key on.

    Lowercases, strips punctuation, and removes the parts that differ between
    two charges at the same shop: store numbers, terminal ids, and order
    references. What survives is the merchant, so "AMZN Mktp US*2K4L9" and
    "AMZN Mktp US*9XQ22" are one merchant rather than two.
    """
    normalized = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    normalized = re.sub(r"\b\d{4,}\b", " ", normalized)
    tokens = normalized.split()
    kept = [
        token
        for index, token in enumerate(tokens)
        if not _REFERENCE_TOKEN.match(token)
        # A short number after the name is a store number — "TRADER JOE'S #219".
        # A short number that *starts* the name is part of it: 7-Eleven, 5 Guys.
        and not (index > 0 and token.isdigit())
    ]
    # A descriptor that is nothing but a reference — "SQ 4H2K9" — still has to
    # key on something, so fall back rather than returning an empty string and
    # collapsing every such merchant into one.
    return " ".join(kept or tokens)
