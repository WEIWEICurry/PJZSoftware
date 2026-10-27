"""Optional monthly expense budgets, without changes to cash or financial facts."""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from pjz.accounting import Accounting, fetch_all, now
from pjz.domain import MAX_FEN, RuleError
from pjz.report_domain import aggregate, budget_usage, calendar_range
from pjz.reports import Reports


def budget_month(value: str) -> date:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise RuleError("BUDGET_INVALID_MONTH")
    try:
        return date.fromisoformat(value + "-01")
    except ValueError as error:
        raise RuleError("BUDGET_INVALID_MONTH") from error


class Budgets:
    def __init__(self, accounting: Accounting) -> None:
        self.accounting = accounting

    def get(self, month: str) -> dict[str, Any]:
        start = budget_month(month)
        _, end = calendar_range("month", start)
        today = date.today()
        with self.accounting.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            revision = connection.execute(text("SELECT revision FROM ledger")).scalar_one()
            rows = fetch_all(
                connection,
                "SELECT b.*,c.name AS category_name FROM category_budgets b "
                "JOIN categories c ON c.id=b.category_id WHERE month=:month ORDER BY c.name",
                {"month": month},
            )
            events, history, _, _ = Reports.load(connection)
            values = []
            for row in rows:
                if row["limit_fen"] is None or start > today:
                    values.append({**row, **budget_usage(row["limit_fen"], None, start > today)})
                    continue
                result = aggregate(
                    start, min(end, today), events, history, row["category_id"], "expense"
                )
                values.append({**row, **budget_usage(row["limit_fen"], result["expense_fen"])})
            return {
                "month": month,
                "ledger_revision": revision,
                "as_of": min(end, today).isoformat(),
                "items": values,
            }

    def save(
        self, month: str, category_id: str, limit: str | None, revision: int, key: str
    ) -> dict[str, Any]:
        budget_month(month)

        def action(connection: Connection) -> dict[str, Any]:
            categories = fetch_all(
                connection, "SELECT * FROM categories WHERE id=:id", {"id": category_id}
            )
            if (
                not categories
                or categories[0]["direction"] != "expense"
                or (limit is not None and categories[0]["archived"])
            ):
                raise RuleError("BUDGET_CATEGORY_INVALID")
            if limit is not None and not 0 < int(limit) <= MAX_FEN:
                raise RuleError("BUDGET_INVALID_LIMIT")
            rows = fetch_all(
                connection,
                "SELECT * FROM category_budgets WHERE month=:month AND category_id=:category",
                {"month": month, "category": category_id},
            )
            before = rows[0] if rows else None
            if revision != (before["revision"] if before else 0):
                raise RuleError("REVISION_CONFLICT")
            identifier = before["id"] if before else str(uuid.uuid4())
            payload = {
                "id": identifier,
                "month": month,
                "category": category_id,
                "limit": int(limit) if limit is not None else None,
                "at": now(),
            }
            if before:
                connection.execute(
                    text(
                        "UPDATE category_budgets SET limit_fen=:limit,revision=revision+1,"
                        "updated_at=:at WHERE id=:id"
                    ),
                    payload,
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO category_budgets VALUES (:id,(SELECT id FROM ledger),"
                        ":month,:category,:limit,1,:at,:at)"
                    ),
                    payload,
                )
            self.accounting.audit(
                connection,
                identifier,
                "save_budget",
                before,
                {"month": month, "category_id": category_id, "limit_fen": limit},
            )
            return {"id": identifier}

        return self.accounting.command(
            key,
            "save_budget",
            {"month": month, "category_id": category_id, "limit_fen": limit, "revision": revision},
            action,
        )

    def copy_previous(self, month: str, revision: int, key: str) -> dict[str, Any]:
        start = budget_month(month)
        if start == date.min:
            raise RuleError("BUDGET_INVALID_MONTH")
        previous = (start - timedelta(days=1)).isoformat()[:7]

        def action(connection: Connection) -> dict[str, Any]:
            if connection.execute(text("SELECT revision FROM ledger")).scalar_one() != revision:
                raise RuleError("REVISION_CONFLICT")
            source = fetch_all(
                connection,
                "SELECT b.* FROM category_budgets b JOIN categories c ON c.id=b.category_id "
                "WHERE b.month=:month AND b.limit_fen IS NOT NULL AND c.archived=0",
                {"month": previous},
            )
            copied = 0
            for row in source:
                existing = fetch_all(
                    connection,
                    "SELECT * FROM category_budgets WHERE month=:month AND category_id=:category",
                    {"month": month, "category": row["category_id"]},
                )
                if existing and existing[0]["limit_fen"] is not None:
                    continue
                identifier = existing[0]["id"] if existing else str(uuid.uuid4())
                params = {
                    "id": identifier,
                    "month": month,
                    "category": row["category_id"],
                    "limit": row["limit_fen"],
                    "at": now(),
                }
                if existing:
                    connection.execute(
                        text(
                            "UPDATE category_budgets SET limit_fen=:limit,revision=revision+1,"
                            "updated_at=:at WHERE id=:id"
                        ),
                        params,
                    )
                else:
                    connection.execute(
                        text(
                            "INSERT INTO category_budgets VALUES (:id,(SELECT id FROM ledger),"
                            ":month,:category,:limit,1,:at,:at)"
                        ),
                        params,
                    )
                self.accounting.audit(
                    connection,
                    identifier,
                    "copy_budget",
                    existing[0] if existing else None,
                    {"month": month, "limit_fen": str(row["limit_fen"]), "from_month": previous},
                )
                copied += 1
            return {"copied": copied}

        return self.accounting.command(
            key, "copy_budgets", {"month": month, "revision": revision}, action
        )

    @staticmethod
    def verify(connection: Connection) -> None:
        rows = fetch_all(
            connection,
            "SELECT b.*,c.direction FROM category_budgets b "
            "JOIN categories c ON c.id=b.category_id",
        )
        for row in rows:
            budget_month(row["month"])
            if (
                row["direction"] != "expense"
                or row["revision"] < 1
                or (
                    row["limit_fen"] is not None
                    and (type(row["limit_fen"]) is not int or not 0 < row["limit_fen"] <= MAX_FEN)
                )
            ):
                raise RuleError("BUDGET_INVALID_DATA")
