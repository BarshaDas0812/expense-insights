"""Domain constants shared across validation, persistence and the AI assistant."""

CATEGORIES = (
    "Food",
    "Travel",
    "Office",
    "Software",
    "Utilities",
    "Marketing",
    "Other",
)

PAYMENT_METHODS = (
    "Cash",
    "Card",
    "UPI",
    "Bank Transfer",
)

CURRENCY_CODE = "INR"

# Amounts are stored as integer paise (1 INR = 100 paise) to avoid float rounding errors.
MAX_AMOUNT_PAISE = 1_000_000_000_00  # ₹1,000,000,000.00 (sanity upper bound)
MAX_DESCRIPTION_LENGTH = 255

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
