"""
Plaid's own category, translated into this household's categories.

Every synced transaction arrives with a `personal_finance_category` such as
`FOOD_AND_DRINK_GROCERIES`. It was being discarded. It is free, it is available
before any model runs, and on ordinary merchants it is right more often than a
small local model guessing from a mangled descriptor string.

Plaid's taxonomy cannot be mapped to categories directly, because a household
names its own. So each Plaid code maps to an ordered list of *word stems*, and
those are matched against whatever categories this household actually has. A
household with "Food & Household" and one with "Groceries" both resolve
`FOOD_AND_DRINK_GROCERIES`, and a household with neither gets nothing rather
than a wrong answer.
"""

import uuid

# Detailed codes first: where Plaid distinguishes something that matters —
# groceries from restaurants, rent from utilities — the detail is the signal
# and the primary is too coarse to use.
DETAILED_HINTS: dict[str, tuple[str, ...]] = {
    "FOOD_AND_DRINK_GROCERIES": ("grocer", "food", "household", "supermarket"),
    "FOOD_AND_DRINK_RESTAURANT": ("dining", "restaurant", "eating out", "food"),
    "FOOD_AND_DRINK_FAST_FOOD": ("dining", "restaurant", "fast food", "food"),
    "FOOD_AND_DRINK_COFFEE": ("coffee", "dining", "restaurant", "food"),
    "FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR": ("alcohol", "dining", "fun", "food"),
    "RENT_AND_UTILITIES_RENT": ("rent", "housing", "mortgage"),
    "RENT_AND_UTILITIES_INTERNET_AND_CABLE": ("internet", "utilit", "subscription"),
    "RENT_AND_UTILITIES_TELEPHONE": ("phone", "utilit", "subscription"),
    "TRANSPORTATION_GAS": ("gas", "fuel", "transport", "auto", "car"),
    "TRANSPORTATION_PARKING": ("parking", "transport", "auto", "car"),
    "TRANSPORTATION_PUBLIC_TRANSIT": ("transit", "transport"),
    "TRANSPORTATION_TAXIS_AND_RIDE_SHARES": ("rideshare", "transport", "transit"),
    "ENTERTAINMENT_TV_AND_MOVIES": ("subscription", "streaming", "entertainment", "fun"),
    "ENTERTAINMENT_MUSIC_AND_AUDIO": ("subscription", "streaming", "entertainment", "fun"),
    "GENERAL_SERVICES_INSURANCE": ("insurance", "non-monthly", "required"),
    "GENERAL_MERCHANDISE_SUPERSTORES": ("household", "grocer", "shopping", "food"),
    "GENERAL_MERCHANDISE_ONLINE_MARKETPLACES": ("shopping", "household", "fun"),
    "LOAN_PAYMENTS_MORTGAGE_PAYMENT": ("mortgage", "housing", "debt"),
    "LOAN_PAYMENTS_STUDENT_LOAN_PAYMENT": ("student", "debt", "loan"),
    "LOAN_PAYMENTS_CAR_PAYMENT": ("car", "auto", "debt", "transport"),
    "MEDICAL_PRIMARY_CARE": ("medical", "health", "doctor"),
    "MEDICAL_PHARMACIES_AND_SUPPLEMENTS": ("pharmacy", "medical", "health"),
}

# Primaries are the fallback, and several are deliberately absent. A category
# guessed wrongly is worse than one left blank: blank shows up in the review
# queue and gets fixed, wrong shows up in a budget and gets believed.
PRIMARY_HINTS: dict[str, tuple[str, ...]] = {
    "INCOME": ("income", "paycheck", "salary", "earnings"),
    "LOAN_PAYMENTS": ("debt", "loan", "mortgage"),
    "BANK_FEES": ("fee", "bank charge", "non-monthly"),
    "ENTERTAINMENT": ("entertainment", "fun", "recreation", "hobby"),
    "FOOD_AND_DRINK": ("food", "dining", "grocer", "restaurant"),
    "GENERAL_MERCHANDISE": ("shopping", "merchandise", "household"),
    "HOME_IMPROVEMENT": ("home", "housing", "maintenance", "improvement"),
    "MEDICAL": ("medical", "health", "doctor", "pharmacy"),
    "PERSONAL_CARE": ("personal care", "grooming", "fitness", "gym"),
    "GOVERNMENT_AND_NON_PROFIT": ("tax", "government", "charity", "giving", "donation"),
    "TRANSPORTATION": ("transport", "gas", "fuel", "auto", "car", "transit"),
    "TRAVEL": ("travel", "vacation", "trip", "flight"),
    "RENT_AND_UTILITIES": ("utilit", "rent", "housing"),
    # GENERAL_SERVICES is a catch-all covering everything from a haircut to a
    # lawyer, and TRANSFER_IN/TRANSFER_OUT say nothing about purpose. Both are
    # left for a person or the model.
}

# Codes that reliably mean money moving between a household's own accounts.
# Everything else under TRANSFER_* can be a real inflow or outflow.
#
# `LOAN_PAYMENTS_CREDIT_CARD_PAYMENT` belongs here and its absence was a real
# bug: it fell through to the LOAN_PAYMENTS primary and resolved to "Debt
# Payments", so paying a card off was recorded as spending — while the matching
# leg landing on the card was recorded as income. The same $702.69 appeared
# under Bills and subscriptions *and* under Recurring income.
#
# It is a transfer even when only one side is connected. The expense was
# recognised when the card was charged; counting the payment as well would
# charge the household twice for one purchase.
ACCOUNT_TRANSFER_CODES = frozenset(
    {
        "TRANSFER_IN_ACCOUNT_TRANSFER",
        "TRANSFER_OUT_ACCOUNT_TRANSFER",
        "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT",
    }
)


def hints_for(provider_category: str | None) -> tuple[str, ...]:
    """Word stems to look for in a category name, best first."""
    if not provider_category:
        return ()
    code = provider_category.strip().upper()
    if code in DETAILED_HINTS:
        return DETAILED_HINTS[code]
    for primary, hints in PRIMARY_HINTS.items():
        if code == primary or code.startswith(f"{primary}_"):
            return hints
    return ()


def is_account_transfer(provider_category: str | None) -> bool:
    return bool(provider_category) and provider_category.strip().upper() in (
        ACCOUNT_TRANSFER_CODES
    )


def is_income_code(provider_category: str | None) -> bool:
    return bool(provider_category) and provider_category.strip().upper().startswith(
        "INCOME"
    )


def resolve(
    provider_category: str | None,
    category_name_map: dict[str, uuid.UUID],
    income_category_ids: frozenset[uuid.UUID] = frozenset(),
    *,
    is_inflow: bool | None = None,
) -> uuid.UUID | None:
    """
    Pick the household category that best fits Plaid's code, or nothing.

    `is_inflow` guards the one mistake this mapping can make that a person
    would notice immediately: putting a refund in an income category, or a
    paycheck in a spending one. When the sign disagrees with the category's
    group, no category is better than the wrong one.
    """
    for hint in hints_for(provider_category):
        for name, category_id in category_name_map.items():
            if hint not in name:
                continue
            if is_inflow is not None:
                income_side = category_id in income_category_ids
                if income_side != is_inflow:
                    continue
            return category_id
    return None
