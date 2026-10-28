"""Exact, framework-free moving weighted investment cost calculations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

from pjz.domain import MAX_FEN, RuleError


def decimal_value(value: str) -> Decimal:
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?", value):
        raise RuleError("INVESTMENT_INVALID_DECIMAL")
    result = Decimal(value)
    if result <= 0:
        raise RuleError("INVESTMENT_INVALID_DECIMAL")
    return result


def decimal_text(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else str(value)


def rounded(value: Decimal) -> int:
    result = int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if abs(result) > MAX_FEN:
        raise RuleError("AMOUNT_OUT_OF_RANGE")
    return result


def holding_share_bps(value: int | None, total: int, complete: bool) -> str | None:
    """A missing valuation makes the portfolio denominator unknown, not zero."""
    if not complete or value is None or total <= 0:
        return None
    with localcontext() as context:
        context.prec = 64
        return str(
            int(
                (Decimal(value) * 10000 / Decimal(total)).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
            )
        )


@dataclass
class Position:
    quantity: Decimal = Decimal(0)
    cost: int | None = 0
    realized: int = 0
    started: bool = False

    def apply(self, action: str, quantity: str, gross: int, fee: int, cost: int | None) -> int:
        units = decimal_value(quantity)
        if any(type(v) is not int or not 0 <= v <= MAX_FEN for v in (gross, fee)):
            raise RuleError("INVALID_AMOUNT")
        if cost is not None and (type(cost) is not int or not 0 <= cost <= MAX_FEN):
            raise RuleError("INVALID_AMOUNT")
        with localcontext() as context:
            context.prec = 64
            if action == "opening":
                if self.started or gross or fee:
                    raise RuleError("INVESTMENT_OPENING_ORDER")
                self.cost = cost
                self.quantity = units
                cash = 0
            elif action == "buy":
                if gross <= 0 or cost is not None:
                    raise RuleError("INVALID_AMOUNT")
                cash = -(gross + fee)
                if self.cost is not None:
                    self.cost += gross + fee
                self.quantity += units
            elif action == "sell":
                if gross <= 0 or fee > gross or cost is not None:
                    raise RuleError("INVALID_AMOUNT")
                if units > self.quantity:
                    raise RuleError("INVESTMENT_INSUFFICIENT_QUANTITY")
                if self.cost is None:
                    raise RuleError("INVESTMENT_COST_REQUIRED")
                allocated = (
                    self.cost
                    if units == self.quantity
                    else rounded(Decimal(self.cost) * units / self.quantity)
                )
                cash = gross - fee
                self.cost -= allocated
                self.realized += cash - allocated
                self.quantity -= units
            else:
                raise RuleError("INVALID_EVENT")
            self.started = True
            if self.quantity > Decimal("999999999999.99999999"):
                raise RuleError("AMOUNT_OUT_OF_RANGE")
            if abs(cash) > MAX_FEN or (self.cost is not None and self.cost > MAX_FEN):
                raise RuleError("AMOUNT_OUT_OF_RANGE")
            if abs(self.realized) > MAX_FEN:
                raise RuleError("AMOUNT_OUT_OF_RANGE")
            return cash

    def market_value(self, price: str) -> int:
        with localcontext() as context:
            context.prec = 64
            return rounded(self.quantity * decimal_value(price) * 100)
