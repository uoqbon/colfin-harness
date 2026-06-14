"""Number extraction tolerant of legacy ASP formatting.

Values arrive as display text: thousands commas, leading '+', trailing '%',
peso signs, and two uses of parentheses — accounting negatives `(3,500.00)`
versus decorated percentages `(+1.07%)`. Parentheses mean negative only when
the inner text carries no explicit sign.
"""

from decimal import Decimal, InvalidOperation

_STRIP = str.maketrans("", "", ",₱ \xa0")
_EMPTY = {"", "-", "--", "N/A", "n/a"}


def to_decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    s = raw.strip()
    if s in _EMPTY:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
        if not s.startswith(("+", "-")):
            negative = True
    s = s.rstrip("%").translate(_STRIP)
    if s.startswith("+"):
        s = s[1:]
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative and value > 0 else value


def to_int(raw: str | None) -> int | None:
    value = to_decimal(raw)
    return int(value) if value is not None else None


def numbers_in(cells: list[str]) -> list[Decimal]:
    """All parseable numbers in a row, in cell order."""
    return [v for v in (to_decimal(c) for c in cells) if v is not None]
