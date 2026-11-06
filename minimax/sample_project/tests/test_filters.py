"""Tests of the order helpers.

``test_filter_by_country`` is the target feature test of the development task:
it fails while the behaviour is missing and passes once it is implemented.
The remaining tests are the regression suite and must keep passing.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from orders.filters import Order, filter_by_amount, filter_by_status, sum_by_currency  # noqa: E402


def _orders() -> list[Order]:
    return [
        Order("o-1", "DE", 1000, "paid", "EUR"),
        Order("o-2", "de", 2500, "paid", "EUR"),
        Order("o-3", "US", 3000, "pending", "USD"),
        Order("o-4", "FR", 700, "paid", ""),
    ]


def test_filter_by_status_keeps_exact_matches() -> None:
    paid = filter_by_status(_orders(), "paid")
    assert [order.order_id for order in paid] == ["o-1", "o-2", "o-4"]
    assert filter_by_status(_orders(), "missing") == []


def test_filter_by_amount_uses_a_lower_bound() -> None:
    rich = filter_by_amount(_orders(), 1000)
    assert [order.order_id for order in rich] == ["o-1", "o-2", "o-3"]
    assert filter_by_amount(_orders(), 100000) == []


def test_sum_by_currency_reports_cents_and_uses_other() -> None:
    assert sum_by_currency(_orders()) == {"EUR": 3500, "USD": 3000, "OTHER": 700}


def test_filter_by_country_ignores_case_and_padding() -> None:
    from orders.filters import filter_by_country

    selected = filter_by_country(_orders(), " de ")
    assert [order.order_id for order in selected] == ["o-1", "o-2"]
    assert filter_by_country(_orders(), "jp") == []


def test_filter_by_country_does_not_mutate_the_input() -> None:
    from orders.filters import filter_by_country

    orders = _orders()
    before = list(orders)
    filter_by_country(orders, "US")
    assert orders == before
