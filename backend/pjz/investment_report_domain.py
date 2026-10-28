"""Read-only period attribution and current allocation, with exact integer amounts."""

from __future__ import annotations

from datetime import date
from typing import Any

from pjz.domain import RuleError
from pjz.investment_domain import holding_share_bps
from pjz.report_domain import calendar_range

KIND_LABELS = {"stock": "股票", "etf": "ETF", "fund": "公募基金"}
ACTION_LABELS = {
    "opening": "期初持仓",
    "buy": "买入／申购",
    "sell": "卖出／赎回",
    "cash_dividend": "现金分红",
    "reinvest": "基金分红再投",
    "split": "份额折算",
}


def investment_bounds(
    period: str, anchor: date, start: date | None, end: date | None, today: date
) -> tuple[date, date, date]:
    if period in ("month", "year"):
        first, last = calendar_range(period, anchor)
    elif period == "custom" and start is not None and end is not None:
        first, last = start, end
    else:
        raise RuleError("INVESTMENT_REPORT_INVALID_PERIOD")
    if first > last:
        raise RuleError("INVESTMENT_REPORT_INVALID_PERIOD")
    if first > today:
        raise RuleError("REPORT_FUTURE_PERIOD")
    return first, min(last, today), last


def period_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = dict.fromkeys(
        (
            "buy_outflow_fen",
            "sell_inflow_fen",
            "realized_fen",
            "cash_dividends_fen",
            "reinvested_dividends_fen",
            "fees_fen",
            "cash_delta_fen",
        ),
        0,
    )
    count = 0
    for row in rows:
        if row["status"] != "active":
            continue
        count += 1
        cash = int(row["cash_delta_fen"])
        values["cash_delta_fen"] += cash
        values["fees_fen"] += int(row["costs_fen"])
        action = row["action"]
        if action == "buy":
            values["buy_outflow_fen"] -= cash
        elif action == "sell":
            values["sell_inflow_fen"] += cash
            values["realized_fen"] += int(row["realized_fen"])
        elif action == "cash_dividend":
            values["cash_dividends_fen"] += int(row["gross_fen"])
        elif action == "reinvest":
            values["reinvested_dividends_fen"] += int(row["gross_fen"])
    values["realized_and_dividends_fen"] = (
        values["realized_fen"] + values["cash_dividends_fen"] + values["reinvested_dividends_fen"]
    )
    return {"record_count": count, **{key: str(value) for key, value in values.items()}}


def current_allocation(
    positions: list[dict[str, Any]],
    accounts: dict[str, dict[str, Any]],
    instruments: dict[str, dict[str, Any]],
    total: int,
    complete: bool,
) -> list[dict[str, Any]]:
    result = []
    for group_by in ("instrument", "account", "kind"):
        buckets: dict[str, list[dict[str, Any]]] = {}
        for p in positions:
            asset = instruments[p["instrument_id"]]
            identifier = (
                p["instrument_id"]
                if group_by == "instrument"
                else p["account_id"]
                if group_by == "account"
                else asset["kind"]
            )
            buckets.setdefault(identifier, []).append(p)
        for identifier, items in buckets.items():
            label = (
                instruments[identifier]["name"] + " · " + instruments[identifier]["code"]
                if group_by == "instrument"
                else accounts[identifier]["name"]
                if group_by == "account"
                else KIND_LABELS[identifier]
            )
            missing = sum(p["value_fen"] is None for p in items)
            known = sum(int(p["value_fen"]) for p in items if p["value_fen"] is not None)
            dates = sorted(
                p["price_date"]
                for p in items
                if p["value_fen"] is not None and p["price_date"] is not None
            )
            result.append(
                {
                    "group_by": group_by,
                    "id": identifier,
                    "label": label,
                    "value_fen": None if missing else str(known),
                    "known_value_fen": str(known),
                    "missing_price_count": missing,
                    "position_count": len(items),
                    "share_bps": holding_share_bps(None if missing else known, total, complete),
                    "price_start": dates[0] if dates else None,
                    "price_end": dates[-1] if dates else None,
                }
            )
    return sorted(
        result,
        key=lambda r: (
            r["group_by"],
            r["value_fen"] is None,
            -int(r["known_value_fen"]),
            r["label"],
            r["id"],
        ),
    )
