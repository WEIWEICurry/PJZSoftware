"""Pure scheduling rules; generated dates are suggestions, never transactions."""

from datetime import date, timedelta
from typing import Any

from pjz.domain import RuleError


def schedule(start: date, end: date, first: date, frequency: str, weekday: int) -> list[str]:
    if (
        start > end
        or (end - start).days > 365
        or frequency not in ("daily", "weekdays", "weekly")
        or not 0 <= weekday <= 6
    ):
        raise RuleError("RECURRING_INVALID_RANGE")
    day = max(start, first)
    result = []
    while day <= end:
        if (
            frequency == "daily"
            or frequency == "weekdays"
            and day.weekday() < 5
            or frequency == "weekly"
            and day.weekday() == weekday
        ):
            result.append(day.isoformat())
        if day == date.max:
            break
        day += timedelta(days=1)
    return result


def validate_recurring_rows(plans: list[dict[str, Any]], drafts: list[dict[str, Any]]) -> None:
    """Validate restored nonfinancial facts and event identities without changing balances."""
    from pjz.domain import MAX_FEN

    try:
        by_id = {p["id"]: p for p in plans}
        for p in plans:
            if (
                not isinstance(p["name"], str)
                or type(p["weekday"]) is not int
                or type(p["amount_fen"]) is not int
                or type(p["costs_fen"]) is not int
            ):
                raise ValueError("types")
            if p.get("deleted", 0) and not p["paused"]:
                raise ValueError("deleted plan must be paused")
            first = date.fromisoformat(p["start_date"])
            schedule(first, first, first, p["frequency"], p["weekday"])
            if (
                not p["name"].strip()
                or len(p["name"]) > 80
                or p["account_kind"] in ("liability", "receivable")
                or p["asset_kind"] != "fund"
            ):
                raise ValueError("plan")
            if p["start_date"] < p["opening_date"]:
                raise ValueError("opening")
            if not 0 <= p["costs_fen"] < p["amount_fen"] <= MAX_FEN:
                raise ValueError("amount")
        for d in drafts:
            p = by_id[d["plan_id"]]
            if type(d["amount_fen"]) is not int or type(d["costs_fen"]) is not int:
                raise ValueError("types")
            day = date.fromisoformat(d["scheduled_date"])
            if day > date.today() or d["scheduled_date"] < p["start_date"]:
                raise ValueError("date")
            if not 0 <= d["costs_fen"] < d["amount_fen"] <= MAX_FEN:
                raise ValueError("amount")
            if d["status"] == "confirmed":
                if (
                    d["action"] != "buy"
                    or d["event_account"] != p["account_id"]
                    or d["event_asset"] != p["instrument_id"]
                    or d["effective_date"] < d["scheduled_date"]
                ):
                    raise ValueError("event")
                if d["nav_date"] and date.fromisoformat(d["nav_date"]) > date.fromisoformat(
                    d["effective_date"]
                ):
                    raise ValueError("nav")
            elif d["event_id"] or d["nav_date"]:
                raise ValueError("status")
    except (KeyError, TypeError, ValueError) as error:
        raise RuleError("RECURRING_INVALID_FACTS") from error
