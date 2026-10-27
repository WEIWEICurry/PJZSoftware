"""Pure source validation, canonical identity and report coverage rules."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from pjz.domain import MAX_FEN, RuleError

MAX_SOURCE = 512 * 1024


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuleError("HISTORY_INVALID_FILE")
        result[key] = value
    return result


def amount(value: Any) -> int:
    if type(value) is int:
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 13:
        result = int(value)
    else:
        raise RuleError("HISTORY_INVALID_AMOUNT")
    if not 0 <= result <= MAX_FEN:
        raise RuleError("HISTORY_INVALID_AMOUNT")
    return result


def overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return bool(
        a["direction"] == b["direction"]
        and a["category_id"] == b["category_id"]
        and a["period_start"] <= b["period_end"]
        and b["period_start"] <= a["period_end"]
    )


def parse_source(payload: bytes) -> tuple[list[dict[str, Any]], str]:
    if len(payload) > MAX_SOURCE:
        raise RuleError("HISTORY_FILE_TOO_LARGE")
    try:
        value = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=unique_object)
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["currency"] != "CNY"
            or value["amount_unit"] != "fen"
            or value["record_type"]
            not in ("monthly_category_expense_summary", "monthly_category_summary")
        ):
            raise RuleError("HISTORY_UNSUPPORTED_FORMAT")
        periods = value["periods"]
        if not isinstance(periods, list) or not 1 <= len(periods) <= 24:
            raise RuleError("HISTORY_INVALID_FILE")
        result: list[dict[str, Any]] = []
        for period in periods:
            start = date.fromisoformat(period["start_date"])
            end = date.fromisoformat(period["end_date"])
            if (
                start > end
                or (start.year, start.month) != (end.year, end.month)
                or end > date.today()
            ):
                raise RuleError("HISTORY_INVALID_PERIOD")
            direction = period.get("direction", "expense")
            if direction not in ("income", "expense") or (
                value["record_type"] == "monthly_category_expense_summary"
                and direction != "expense"
            ):
                raise RuleError("HISTORY_INVALID_FILE")
            if value["record_type"] == "monthly_category_summary" and "direction" not in period:
                raise RuleError("HISTORY_INVALID_FILE")
            refs = period.get("source_images", [])
            if (
                not isinstance(refs, list)
                or len(refs) > 50
                or any(not isinstance(ref, str) or not 1 <= len(ref) <= 200 for ref in refs)
            ):
                raise RuleError("HISTORY_INVALID_FILE")
            categories = period["categories"]
            if not isinstance(categories, list) or not 1 <= len(categories) <= 100:
                raise RuleError("HISTORY_INVALID_FILE")
            total = 0
            for item in categories:
                name = item["category"]
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
                    raise RuleError("HISTORY_INVALID_FILE")
                cents = amount(item["amount_fen"])
                total += cents
                row = {
                    "period_start": start.isoformat(),
                    "period_end": end.isoformat(),
                    "direction": direction,
                    "source_category": name.strip(),
                    "amount_fen": cents,
                    "source_refs": refs,
                    "mapping_key": direction + ":" + name.strip(),
                }
                # A source category cannot claim the same date twice, even before mapping.
                if any(
                    overlaps(
                        {**row, "category_id": name.strip()},
                        {**other, "category_id": other["source_category"]},
                    )
                    for other in result
                ):
                    raise RuleError("HISTORY_SOURCE_OVERLAP")
                result.append(row)
            if total != amount(period["displayed_total_fen"]):
                raise RuleError("HISTORY_TOTAL_MISMATCH")
        if len(result) > 500:
            raise RuleError("HISTORY_INVALID_FILE")
        canonical = sorted(
            [
                r["period_start"],
                r["period_end"],
                r["direction"],
                r["source_category"],
                r["amount_fen"],
            ]
            for r in result
        )
        digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False).encode()).hexdigest()
        return result, digest
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, AttributeError) as error:
        if isinstance(error, RuleError):
            raise
        raise RuleError("HISTORY_INVALID_FILE") from error


def event_direction(row: dict[str, Any]) -> str | None:
    if row["kind"] == "income":
        return "income"
    if row["kind"] in ("expense", "refund") or (
        row["kind"] == "transfer" and int(row["fee_fen"]) != 0
    ):
        return "expense"
    return None


def event_amount(row: dict[str, Any]) -> int:
    if row["kind"] == "transfer":
        return int(row["fee_fen"])
    return int(row["amount_fen"]) * (-1 if row["kind"] == "refund" else 1)


def covered(row: dict[str, Any], summaries: list[dict[str, Any]]) -> bool:
    direction = event_direction(row)
    return any(
        item["category_id"] == row["category_id"]
        and item["direction"] == direction
        and item["period_start"] <= row["effective_date"] <= item["period_end"]
        for item in summaries
    )
