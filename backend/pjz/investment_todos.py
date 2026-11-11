"""Read-only local investment tasks, evaluated from one ledger snapshot."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from pjz.accounting import fetch_all
from pjz.investments import Investments

TodoKind = Literal["recurring", "missing_price", "stale_price", "unknown_cost"]


@dataclass(frozen=True)
class InvestmentTodo:
    kind: TodoKind
    id: str
    title: str
    detail: str
    count: int
    account_id: str | None = None
    instrument_id: str | None = None
    plan_id: str | None = None
    start: str | None = None
    end: str | None = None
    required_from: str | None = None


@dataclass(frozen=True)
class InvestmentTodos:
    as_of: str
    revision: int
    items: list[InvestmentTodo]


def investment_todos(service: Investments, today: date | None = None) -> InvestmentTodos:
    day = today or date.today()
    with service.accounting.engine.connect() as connection:
        connection.exec_driver_sql("BEGIN")
        snapshot = service.snapshot(connection, as_of=day.isoformat())
        plans = fetch_all(
            connection,
            "SELECT p.id,p.name,p.paused,a.archived OR c.archived AS blocked,"
            "COUNT(d.id) AS count,MIN(d.scheduled_date) AS first "
            "FROM investment_plans p JOIN investment_drafts d ON d.plan_id=p.id "
            "JOIN accounts a ON a.id=p.account_id "
            "JOIN accounts c ON c.id=COALESCE(p.cash_account_id,p.account_id) "
            "WHERE p.deleted=0 AND d.status='pending' AND d.scheduled_date<=:today "
            "GROUP BY p.id ORDER BY first,p.id",
            {"today": day.isoformat()},
        )
        items = []
        for plan in plans:
            first = date.fromisoformat(plan["first"])
            end = min(day, first + timedelta(days=365))
            notes = [f"最早 {first.isoformat()}"]
            if plan["paused"]:
                notes.append("计划已暂停，已有草稿仍待核对")
            if plan["blocked"]:
                notes.append("涉及已归档账户，请先恢复账户")
            if end < day:
                notes.append("先查看最早 366 天，处理后可继续")
            items.append(
                InvestmentTodo(
                    "recurring",
                    plan["id"],
                    plan["name"],
                    "；".join(notes),
                    plan["count"],
                    plan_id=plan["id"],
                    start=first.isoformat(),
                    end=end.isoformat(),
                )
            )
        assets = {i["id"]: i for i in snapshot["instruments"]}
        accounts = {a["id"]: a for a in service.accounting.account_rows(connection)}
        price_groups: dict[str, list[dict[str, Any]]] = {}
        for position in snapshot["positions"]:
            if position["quantity"] == "0":
                continue
            asset = assets[position["instrument_id"]]
            account = accounts[position["account_id"]]
            if position["cost_fen"] is None:
                items.append(
                    InvestmentTodo(
                        "unknown_cost",
                        account["id"] + ":" + asset["id"],
                        asset["name"],
                        account["name"] + " · 剩余成本尚未补齐",
                        1,
                        account_id=account["id"],
                        instrument_id=asset["id"],
                    )
                )
            price_groups.setdefault(asset["id"], []).append(position)
        for identifier, positions in price_groups.items():
            missing = any(p["value_fen"] is None for p in positions)
            price_day = positions[0]["price_date"]
            if not missing and (
                price_day is None or price_day >= (day - timedelta(days=7)).isoformat()
            ):
                continue
            names = sorted({accounts[p["account_id"]]["name"] for p in positions})
            required = max(
                (p["valuation_required_from"] for p in positions if p["valuation_required_from"]),
                default=None,
            )
            detail = "涉及 " + "、".join(names)
            detail += (
                (" · 需补录事件后有效价格" if required else " · 尚无有效价格")
                if missing
                else " · 最近 " + price_day
            )
            items.append(
                InvestmentTodo(
                    "missing_price" if missing else "stale_price",
                    identifier,
                    assets[identifier]["name"],
                    detail,
                    1,
                    instrument_id=identifier,
                    required_from=required,
                )
            )
        return InvestmentTodos(
            day.isoformat(),
            connection.exec_driver_sql("SELECT revision FROM ledger").scalar_one(),
            items,
        )
