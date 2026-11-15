"""Named scenario values and data paths for the demos.

These numbers are ILLUSTRATIVE inputs for the fake-data demos, not chosen business rules. The core
modules never import this file: they receive policies as parameters, so tests and a future real
configuration can supply different values without editing library code.
"""

from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data"

# Publication order matters: the last file is treated as the newest version.
PRICE_LIST_FILES = (
    DATA_DIRECTORY / "price_list_v1.json",
    DATA_DIRECTORY / "price_list_v2.json",
    DATA_DIRECTORY / "price_list_v3.json",
)
USERS_FILE = DATA_DIRECTORY / "users.json"
COST_SHEET_FILE = DATA_DIRECTORY / "cost_sheet.json"

# Pricing and approval (illustrative).
DEMO_MAX_DISCOUNT = Decimal("0.30")
DEMO_VAT_RATE = Decimal("0.10")
DEMO_AUTO_APPROVE_THRESHOLD = Decimal("0.10")
DEMO_AUTO_APPROVE_RULE_ID = "demo-low-discount-policy"

# Simulated agent's volume-discount table (illustrative): (rule id, minimum quantity, discount).
DEMO_LIST_PRICE_RULE_ID = "demo-list-price"
DEMO_REQUESTED_DISCOUNT_RULE_ID = "demo-customer-requested"
DEMO_VOLUME_RULES = (
    ("demo-volume-10", 10, Decimal("0.05")),
    ("demo-volume-50", 50, Decimal("0.15")),
)

# A human typing a discount by hand still needs a rule id in the evidence (illustrative).
DEMO_MANUAL_DISCOUNT_RULE_ID = "demo-manual-discount"
