from decimal import Decimal

import pytest

from app.money import MoneyError, money, quantity, round_cents, sum_money, to_str


def test_float_is_rejected():
    with pytest.raises(MoneyError):
        money(0.1)
    with pytest.raises(MoneyError):
        money(19000.0)


def test_bool_is_rejected():
    with pytest.raises(MoneyError):
        money(True)


def test_decimal_strings_are_exact():
    # 0.1 + 0.2 is not 0.3 in binary float; it must be exactly 0.30 here.
    assert sum_money([money("0.10"), money("0.20")]) == Decimal("0.30")
    assert to_str(money("0.10") + money("0.20")) == "0.30"


def test_many_small_amounts_do_not_drift():
    total = sum_money([money("0.01")] * 100_000)
    assert total == Decimal("1000.00")


def test_normalises_to_two_places():
    assert to_str(money("19000")) == "19000.00"
    assert to_str(money(25000)) == "25000.00"
    assert to_str(money(" 4000.5 ")) == "4000.50"


def test_more_than_two_decimal_places_is_rejected_not_rounded():
    with pytest.raises(MoneyError):
        money("10.005")
    with pytest.raises(MoneyError):
        money("0.001")


def test_trailing_zero_precision_is_fine():
    assert money("10.000") == Decimal("10.00")


@pytest.mark.parametrize("bad", ["", "  ", "abc", "1,000", "NaN", "Infinity", "-inf", None, [1]])
def test_invalid_inputs_rejected(bad):
    with pytest.raises(MoneyError):
        money(bad)


def test_numeric_14_2_range_enforced():
    assert money("999999999999.99") == Decimal("999999999999.99")
    with pytest.raises(MoneyError):
        money("1000000000000.00")


def test_round_cents_is_explicit_half_up():
    assert round_cents(Decimal("2") * Decimal("0.125")) == Decimal("0.25")
    assert round_cents(Decimal("3") * Decimal("33.335")) == Decimal("100.01")
    assert round_cents(Decimal("0.005")) == Decimal("0.01")
    with pytest.raises(MoneyError):
        round_cents(0.5)  # type: ignore[arg-type]


def test_quantity_rules():
    assert quantity("2") == Decimal("2.000")
    assert quantity("1.5") == Decimal("1.500")
    for bad in ("0", "-1", "1.0001", 1.5):
        with pytest.raises(MoneyError):
            quantity(bad)


def test_seed_invariant_in_pure_decimal():
    bill, payable, queried, paid = (money(v) for v in ("25000", "19000", "2000", "4000"))
    assert bill == payable + queried + paid
