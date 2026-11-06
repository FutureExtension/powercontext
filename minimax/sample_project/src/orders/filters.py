"""Order filtering helpers.

The project is intentionally small: it exists so that a development task can be
completed against real code with real tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Order:
    """One order line as stored by the sample project."""

    order_id: str
    country: str
    amount_cents: int
    status: str
    currency: str


def _normalize_country(value: str | None) -> str | None:
    """Return the comparable form of a country code.

    Textual comparisons ignore case and surrounding whitespace, so ``" de "``
    and ``"DE"`` normalise to the same value.  ``None`` is not a country and
    stays ``None`` so that it never matches a requested country.
    """

    if value is None:
        return None
    return value.strip().casefold()


def filter_by_country(orders: Iterable[Order], country: str) -> list[Order]:
    """Return the orders whose country matches ``country``.

    The comparison ignores case and surrounding whitespace on both sides, so
    ``filter_by_country(orders, " de ")`` keeps the orders stored as ``"DE"``
    and ``"de"``.  The input is never modified and the result keeps the order
    of the input.  An unknown country yields an empty list; ``None`` is not
    accepted as the requested country.
    """

    if country is None:
        raise TypeError("country must be a string, not None")

    wanted = _normalize_country(country)
    return [
        order
        for order in orders
        if _normalize_country(order.country) == wanted
    ]


def filter_by_status(orders: Iterable[Order], status: str) -> list[Order]:
    """Return the orders whose status matches ``status`` exactly."""

    return [order for order in orders if order.status == status]


def filter_by_amount(orders: Iterable[Order], min_cents: int) -> list[Order]:
    """Return the orders whose amount reaches ``min_cents``."""

    return [order for order in orders if order.amount_cents >= min_cents]


def sum_by_currency(orders: Iterable[Order]) -> Mapping[str, int]:
    """Sum the order amounts per currency, in cents.

    An empty currency is reported under ``OTHER`` so that the totals of the
    known currencies always add up to the total of the input.
    """

    totals: dict[str, int] = {}
    for order in orders:
        key = order.currency or "OTHER"
        totals[key] = totals.get(key, 0) + order.amount_cents
    return totals
