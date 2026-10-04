"""Money helpers. All arithmetic happens on integer paise; conversion happens only at the edges."""


def paise_to_amount(paise: int) -> float:
    """Convert integer paise to a rupee value suitable for JSON (e.g. 125050 -> 1250.5)."""
    return round(paise / 100, 2)


def format_inr(paise: int) -> str:
    """Format paise as Indian rupees with Indian digit grouping, e.g. 12345678 -> '₹1,23,456.78'."""
    sign = "-" if paise < 0 else ""
    rupees, remainder = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return f"{sign}₹{digits}.{remainder:02d}"
