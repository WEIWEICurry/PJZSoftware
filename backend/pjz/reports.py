"""Snapshot reports and precise, formula-safe CSV exports."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from pjz.accounting import Accounting, fetch_all
from pjz.domain import RuleError
from pjz.history_domain import covered, event_amount, event_direction
from pjz.report_domain import aggregate, changes, report_range, trend_ranges


class Reports:
    def __init__(self, accounting: Accounting) -> None:
        self.accounting = accounting

    @staticmethod
    def load(
        connection: Connection,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        events = fetch_all(
            connection,
            "SELECT * FROM financial_events WHERE status='active' "
            "ORDER BY effective_date DESC,sequence DESC",
        )
        history = fetch_all(
            connection,
            "SELECT s.*,b.filename FROM historical_summaries s "
            "JOIN import_batches b ON b.id=s.batch_id WHERE b.status='active'",
        )
        categories = {r["id"]: r for r in fetch_all(connection, "SELECT * FROM categories")}
        accounts = {r["id"]: r for r in fetch_all(connection, "SELECT * FROM accounts")}
        return events, history, categories, accounts

    def get(self, period: str, anchor: date) -> dict[str, Any]:
        bounds = report_range(period, anchor, date.today())
        with self.accounting.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            events, history, categories, _ = self.load(connection)
            current = aggregate(bounds["start"], bounds["end"], events, history)
            previous = (
                aggregate(bounds["previous"][0], bounds["previous"][1], events, history)
                if bounds["previous"]
                else None
            )
            for row in current["categories"]:
                row["category_name"] = categories[row["category_id"]]["name"]
            if previous:
                for row in previous["categories"]:
                    row["category_name"] = categories[row["category_id"]]["name"]
            trends = []
            for start, end in trend_ranges(period, bounds["start"], bounds["calendar_end"]):
                if start > bounds["end"]:
                    trends.append(
                        {
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                            "income_fen": None,
                            "expense_fen": None,
                            "surplus_fen": None,
                            "known_income_fen": "0",
                            "known_expense_fen": "0",
                            "status": "future",
                        }
                    )
                else:
                    point = aggregate(start, min(end, bounds["end"]), events, history)
                    trends.append(
                        {
                            **point,
                            "status": "unallocated"
                            if point["income_fen"] is None or point["expense_fen"] is None
                            else "recorded",
                        }
                    )
            ranges = [
                {
                    "start": s["period_start"],
                    "end": s["period_end"],
                    "direction": s["direction"],
                    "category_name": categories[s["category_id"]]["name"],
                    "source": s["filename"],
                    "amount_fen": str(s["amount_fen"]),
                    "allocated": bounds["start"].isoformat() <= s["period_start"]
                    and s["period_end"] <= bounds["end"].isoformat(),
                }
                for s in history
                if s["period_start"] <= current["end"] and s["period_end"] >= current["start"]
            ]
            return {
                "period": period,
                "calendar_end": bounds["calendar_end"].isoformat(),
                "current": current,
                "previous": previous,
                "changes": changes(current, previous),
                "trend": trends,
                "history_ranges": ranges,
            }

    @staticmethod
    def records(
        start: date,
        end: date,
        events: list[dict[str, Any]],
        history: list[dict[str, Any]],
        categories: dict[str, Any],
        accounts: dict[str, Any],
        category_id: str | None,
        direction: str | None,
    ) -> list[dict[str, Any]]:
        left, right = start.isoformat(), end.isoformat()
        result = []
        for event in events:
            kind = event_direction(event)
            if not kind or not left <= event["effective_date"] <= right:
                continue
            if (category_id and event["category_id"] != category_id) or (
                direction and kind != direction
            ):
                continue
            excluded = covered(event, history)
            result.append(
                {
                    "id": event["id"],
                    "start": event["effective_date"],
                    "end": event["effective_date"],
                    "direction": kind,
                    "category_id": event["category_id"],
                    "category_name": categories[event["category_id"]]["name"],
                    "account_name": accounts[event["account_id"]]["name"],
                    "note": event["note"],
                    "source": "转账手续费" if event["kind"] == "transfer" else "逐笔流水",
                    "amount_fen": str(event_amount(event)),
                    "counted_fen": "0" if excluded else str(event_amount(event)),
                    "status": "covered" if excluded else "included",
                }
            )
        for item in history:
            if item["period_start"] > right or item["period_end"] < left:
                continue
            if (category_id and item["category_id"] != category_id) or (
                direction and item["direction"] != direction
            ):
                continue
            included = left <= item["period_start"] and item["period_end"] <= right
            result.append(
                {
                    "id": item["id"],
                    "start": item["period_start"],
                    "end": item["period_end"],
                    "direction": item["direction"],
                    "category_id": item["category_id"],
                    "category_name": categories[item["category_id"]]["name"],
                    "account_name": "",
                    "note": "原分类：" + item["source_category"],
                    "source": "历史汇总：" + item["filename"],
                    "amount_fen": str(item["amount_fen"]),
                    "counted_fen": str(item["amount_fen"]) if included else None,
                    "status": "included" if included else "unallocated",
                }
            )
        return sorted(result, key=lambda row: (row["start"], row["id"]), reverse=True)

    def entries(
        self,
        period: str,
        anchor: date,
        category_id: str | None = None,
        direction: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        bounds = report_range(period, anchor, date.today())
        with self.accounting.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            events, history, categories, accounts = self.load(connection)
            rows = self.records(
                bounds["start"],
                bounds["end"],
                events,
                history,
                categories,
                accounts,
                category_id,
                direction,
            )
        return {"items": rows[offset : offset + limit], "total": len(rows)}

    def export(
        self, period: str, anchor: date, category_id: str | None, direction: str | None
    ) -> bytes:
        bounds = report_range(period, anchor, date.today())
        with self.accounting.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            rows = self.records(
                bounds["start"], bounds["end"], *self.load(connection), category_id, direction
            )
        if len(rows) > 50000:
            raise RuleError("REPORT_EXPORT_TOO_LARGE")
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "报表开始",
                "报表截止",
                "记录开始",
                "记录截止",
                "方向",
                "分类",
                "账户",
                "来源",
                "备注",
                "原金额（元）",
                "计入金额（元）",
                "统计状态",
                "记录ID",
            ]
        )
        labels = {
            "included": "计入",
            "covered": "已被历史汇总覆盖",
            "unallocated": "原汇总无法分配到所选期间",
        }
        for row in rows:
            text_values = [
                str(bounds["start"]),
                str(bounds["end"]),
                row["start"],
                row["end"],
                "收入" if row["direction"] == "income" else "支出",
                row["category_name"],
                row["account_name"],
                row["source"],
                row["note"],
            ]
            safe = [
                ("'" + value)
                if value.lstrip().startswith(("=", "+", "-", "@"))
                or value.startswith(("\t", "\r", "\n"))
                else value
                for value in text_values
            ]
            writer.writerow(
                [
                    *safe,
                    format(Decimal(row["amount_fen"]) / 100, ".2f"),
                    ""
                    if row["counted_fen"] is None
                    else format(Decimal(row["counted_fen"]) / 100, ".2f"),
                    labels[row["status"]],
                    row["id"],
                ]
            )
        return output.getvalue().encode("utf-8-sig")
