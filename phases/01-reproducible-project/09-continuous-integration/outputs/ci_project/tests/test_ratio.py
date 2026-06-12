import pytest

from ratio import ratio


def test_ratio() -> None:
    assert ratio(1, 4) == pytest.approx(0.25)


@pytest.mark.parametrize(("part", "total"), [(-1, 4), (1, 0), (5, 4)])
def test_invalid_ratio(part: int, total: int) -> None:
    with pytest.raises(ValueError):
        ratio(part, total)
