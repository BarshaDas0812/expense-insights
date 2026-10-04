"""Deterministic demo data spread over the last four months."""
import random
from datetime import date, timedelta

from . import repository

SAMPLES = {
    "Food": [("Team lunch", 1200, 4500), ("Client dinner", 2500, 8000), ("Office snacks", 300, 1500)],
    "Travel": [("Flight to Bengaluru", 4500, 12000), ("Cab to client site", 250, 900),
               ("Hotel stay, Mumbai", 3500, 9000), ("Train tickets", 600, 2500)],
    "Office": [("Printer paper and toner", 800, 3500), ("Desk chair", 4000, 12000),
               ("Stationery", 200, 900)],
    "Software": [("Design tool subscription", 1500, 4000), ("Cloud hosting", 2000, 9000),
                 ("Accounting software", 1000, 3000)],
    "Utilities": [("Electricity bill", 2500, 6000), ("Internet bill", 1000, 2500),
                  ("Phone recharge", 300, 800)],
    "Marketing": [("Social media ads", 3000, 15000), ("Printed brochures", 1500, 5000),
                  ("Event booth", 8000, 25000)],
    "Other": [("Courier charges", 150, 800), ("Bank charges", 50, 500)],
}
PAYMENT_BY_CATEGORY = {
    "Food": ["UPI", "Card", "Cash"],
    "Travel": ["Card", "UPI"],
    "Office": ["Card", "UPI", "Bank Transfer"],
    "Software": ["Card"],
    "Utilities": ["UPI", "Bank Transfer"],
    "Marketing": ["Card", "Bank Transfer"],
    "Other": ["Cash", "UPI"],
}


def seed(conn, today: date, count: int = 45, rng_seed: int = 42) -> int:
    rng = random.Random(rng_seed)
    categories = list(SAMPLES)
    weights = [5, 4, 3, 3, 3, 2, 1]
    for _ in range(count):
        category = rng.choices(categories, weights)[0]
        description, low, high = rng.choice(SAMPLES[category])
        rupees = rng.randint(low, high)
        paise = rupees * 100 + rng.choice([0, 0, 0, 50, 99])
        repository.create_expense(conn, {
            "date": (today - timedelta(days=rng.randint(0, 120))).isoformat(),
            "category": category,
            "description": description,
            "amount_paise": paise,
            "payment_method": rng.choice(PAYMENT_BY_CATEGORY[category]),
        })
    return count
