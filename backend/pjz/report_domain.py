"""Pure calendar, report coverage and integer/Decimal aggregation rules."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pjz.domain import MAX_FEN, RuleError
from pjz.history_domain import covered, event_amount, event_direction


def rounded_ratio(numerator: int, denominator: int) -> int:
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )


def calendar_range(period: str, anchor: date) -> tuple[date, date]:
    try:
        if period == "day":
            return anchor, anchor
        if period == "week":
            start = anchor - timedelta(days=anchor.weekday())
            return start, start + timedelta(days=6)
        if period == "month":
            return anchor.replace(day=1), anchor.replace(
                day=calendar.monthrange(anchor.year, anchor.month)[1]
            )
        if period == "year":
            return date(anchor.year, 1, 1), date(anchor.year, 12, 31)
    except (ValueError, OverflowError) as error:
        raise RuleError("REPORT_INVALID_PERIOD") from error
    raise RuleError("REPORT_INVALID_PERIOD")


def report_range(period: str, anchor: date, today: date) -> dict[str, Any]:
    start, calendar_end = calendar_range(period, anchor)
    if start > today:
        raise RuleError("REPORT_FUTURE_PERIOD")
    end = min(calendar_end, today)
    previous = None
    if start > date.min:
        previous_start, previous_end = calendar_range(period, start - timedelta(days=1))
        if end < calendar_end:
            previous_end = min(previous_end, previous_start + (end - start))
        previous = (previous_start, previous_end)
    return {"start": start, "end": end, "calendar_end": calendar_end, "previous": previous}


def aggregate(
    start: date,
    end: date,
    events: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    category_id: str | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    left, right = start.isoformat(), end.isoformat()
    history = [
        s
        for s in summaries
        if s["period_start"] <= right
        and s["period_end"] >= left
        and (not category_id or s["category_id"] == category_id)
        and (not direction or s["direction"] == direction)
    ]
    groups: dict[tuple[str, str], dict[str, Any]] = {}

    def group(kind: str, identifier: str) -> dict[str, Any]:
        key = (kind, identifier)
        if key not in groups:
            groups[key] = {
                "direction": kind,
                "category_id": identifier,
                "known": 0,
                "history": 0,
                "details": 0,
                "unknown": False,
            }
        return groups[key]

    covered_count = detail_count = 0
    for event in events:
        kind = event_direction(event)
        if (
            event["status"] != "active"
            or not kind
            or not left <= event["effective_date"] <= right
            or (category_id and event["category_id"] != category_id)
            or (direction and kind != direction)
        ):
            continue
        target = group(kind, event["category_id"])
        if covered(event, history):
            covered_count += 1
            continue
        cents = event_amount(event)
        target["known"] += cents
        target["details"] += cents
        detail_count += 1
    for item in history:
        target = group(item["direction"], item["category_id"])
        if left <= item["period_start"] and item["period_end"] <= right:
            target["known"] += int(item["amount_fen"])
            target["history"] += int(item["amount_fen"])
        else:
            target["unknown"] = True
    unknown = {
        kind: any(g["unknown"] for g in groups.values() if g["direction"] == kind)
        for kind in ("income", "expense")
    }
    known = {
        kind: sum(g["known"] for g in groups.values() if g["direction"] == kind)
        for kind in ("income", "expense")
    }
    positives = {
        kind: sum(max(g["known"], 0) for g in groups.values() if g["direction"] == kind)
        for kind in ("income", "expense")
    }
    categories = []
    for g in sorted(
        groups.values(), key=lambda item: (item["direction"], -item["known"], item["category_id"])
    ):
        denominator = positives[g["direction"]]
        categories.append(
            {
                "direction": g["direction"],
                "category_id": g["category_id"],
                "amount_fen": None if g["unknown"] else str(g["known"]),
                "known_fen": str(g["known"]),
                "historical_fen": str(g["history"]),
                "detail_fen": str(g["details"]),
                "share_bps": None
                if unknown[g["direction"]]
                else rounded_ratio(max(g["known"], 0) * 10000, denominator)
                if denominator
                else 0,
            }
        )
    income = None if unknown["income"] else str(known["income"])
    expense = None if unknown["expense"] else str(known["expense"])
    days = (end - start).days + 1
    return {
        "start": left,
        "end": right,
        "income_fen": income,
        "expense_fen": expense,
        "surplus_fen": None
        if income is None or expense is None
        else str(int(income) - int(expense)),
        "known_income_fen": str(known["income"]),
        "known_expense_fen": str(known["expense"]),
        "daily_expense_fen": None if expense is None else str(rounded_ratio(int(expense), days)),
        "day_count": days,
        "covered_count": covered_count,
        "detail_count": detail_count,
        "historical_count": len(history),
        "categories": categories,
    }


def trend_ranges(period: str, start: date, calendar_end: date) -> list[tuple[date, date]]:
    if period == "year":
        return [calendar_range("month", date(start.year, month, 1)) for month in range(1, 13)]
    return [
        (start + timedelta(days=offset), start + timedelta(days=offset))
        for offset in range((calendar_end - start).days + 1)
    ]


def changes(current: dict[str, Any], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    result = []
    for metric in ("income", "expense", "surplus"):
        now = current[metric + "_fen"]
        before = previous[metric + "_fen"] if previous else None
        difference = int(now) - int(before) if now is not None and before is not None else None
        result.append(
            {
                "metric": metric,
                "delta_fen": str(difference) if difference is not None else None,
                "change_bps": str(rounded_ratio(difference * 10000, abs(int(before))))
                if difference is not None and before is not None and int(before)
                else None,
            }
        )
    return result


def budget_usage(
    limit: int | None, net_expense: str | None, future: bool = False
) -> dict[str, Any]:
    if limit is not None and not 0 < limit <= MAX_FEN:
        raise RuleError("BUDGET_INVALID_LIMIT")
    base = {
        "limit_fen": str(limit) if limit is not None else None,
        "net_expense_fen": None,
        "used_fen": None,
        "remaining_fen": None,
        "over_fen": None,
        "used_bps": None,
    }
    if limit is None or future or net_expense is None:
        return {**base, "status": "unset" if limit is None else "future" if future else "unknown"}
    used = max(int(net_expense), 0)
    return {
        **base,
        "net_expense_fen": net_expense,
        "used_fen": str(used),
        "remaining_fen": str(limit - used),
        "over_fen": str(max(used - limit, 0)),
        "used_bps": str(rounded_ratio(used * 10000, limit)),
        "status": "over"
        if used > limit
        else "exhausted"
        if used == limit
        else "near"
        if used * 100 >= limit * 80
        else "normal",
    }
