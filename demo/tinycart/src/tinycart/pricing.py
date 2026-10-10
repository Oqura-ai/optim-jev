"""Pricing primitives. Every monetary value is stored as integer cents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CartLine:
    sku: str
    unit_price_cents: int
    quantity: int


def line_total(unit_price_cents: int, quantity: int) -> int:
    """Return a line total after validating its integer inputs."""
    if unit_price_cents < 0:
        raise ValueError("unit price cannot be negative")
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    return unit_price_cents * quantity


def cart_total(lines: list[CartLine]) -> int:
    """Return the total price of all cart lines in cents."""
    return sum(line_total(line.unit_price_cents, line.quantity) for line in lines)


def vip_price(price_cents: int, discount_percent: int) -> int:
    """Return the price in cents after a whole-number percentage VIP discount."""
    if price_cents < 0:
        raise ValueError("price cannot be negative")
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("discount percent must be between 0 and 100")
    discount = price_cents * discount_percent // 100
    return max(0, price_cents - discount)
