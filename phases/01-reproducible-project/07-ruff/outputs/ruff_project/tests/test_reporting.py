from decimal import Decimal

from reporting import average


def test_average() -> None:
    assert average([Decimal("10"), Decimal("20")]) == Decimal("15")
