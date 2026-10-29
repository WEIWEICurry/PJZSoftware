"""Historical boundary views using the shared investment replay, without writes."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection

from pjz.investment_report_domain import boundary_profit
from pjz.investments import Investments


def period_performance(
    investments: Investments,
    connection: Connection,
    first: date,
    last: date,
    matches: Callable[[dict[str, Any]], bool],
    active: list[dict[str, Any]],
    accounts: dict[str, Any],
    assets: dict[str, Any],
) -> dict[str, Any]:
    def boundary(day: str) -> dict[str, Any]:
        positions, _, _ = investments.replay_details(connection, day)
        snapshot = investments.snapshot(connection, positions, day)
        items = []
        known, missing = 0, 0
        for p in snapshot["positions"]:
            if p["quantity"] == "0" or not matches(p):
                continue
            # Historical performance requires a confirmed price for this exact boundary.
            amount = p["value_fen"] if p["price_date"] == day else None
            reason = (
                "ready"
                if amount is not None
                else "missing_boundary_price"
                if p["price_date"] != day
                else "event_requires_confirmation"
            )
            known += int(amount) if amount is not None else 0
            missing += int(amount is None)
            items.append(
                {
                    "account_id": p["account_id"],
                    "account_name": accounts[p["account_id"]]["name"],
                    "instrument_id": p["instrument_id"],
                    "instrument_name": assets[p["instrument_id"]]["name"],
                    "code": assets[p["instrument_id"]]["code"],
                    "quantity": p["quantity"],
                    "cost_fen": p["cost_fen"],
                    "value_fen": amount,
                    "price_date": p["price_date"],
                    "status": reason,
                }
            )
        items.sort(key=lambda p: (p["code"], p["account_id"]))
        return {
            "as_of_date": day,
            "value_fen": None if missing else str(known),
            "known_value_fen": str(known),
            "missing_price_count": missing,
            "positions": items,
        }

    before = (first - timedelta(days=1)).isoformat() if first > date.min else ""
    beginning, ending = boundary(before), boundary(last.isoformat())
    opening_count = sum(r["action"] == "opening" for r in active)
    cash = sum(int(r["cash_delta_fen"]) for r in active)
    status, profit = boundary_profit(
        beginning["value_fen"], ending["value_fen"], cash, opening_count
    )
    return {
        "beginning": beginning,
        "ending": ending,
        "cash_delta_fen": str(cash),
        "total_profit_fen": None if profit is None else str(profit),
        "status": status,
        "opening_count": opening_count,
    }
